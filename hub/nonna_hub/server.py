"""The hub server: listener phones stream audio over a WebSocket, as docs/api-contract.md describes.

Each phone's audio becomes household events (YAMNet, categories, merger), printed with the room.
Help words (E3) and alerts (E5) build on this.
"""

import asyncio
import contextlib
import secrets
import socket
import time
from dataclasses import dataclass, field
from importlib.metadata import version

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from nonna_hub.audio import SAMPLE_RATE, WindowSlicer
from nonna_hub.categories import Categorizer
from nonna_hub.events import Event, EventMerger
from nonna_hub.protocol import (
    CLOSE_BAD_HELLO,
    CLOSE_REPLACED,
    FRAME_BYTES,
    PROTOCOL_VERSION,
    AskPlayed,
    Heartbeat,
    Hello,
    Light,
    Room,
    now_ms,
    parse_frame,
    parse_message,
)
from nonna_hub.sound import HOP_SAMPLES, SoundClassifier

HELLO_TIMEOUT_S = 10
ASK_TIMEOUT_MS = 20_000  # the contract treats a check as failed after 20 s without ask_played

# Until E8 reads the home's check-in text and language from Firestore.
CHECKIN_TEXT = "Are you okay?"
CHECKIN_LANG = "en-US"


@dataclass
class Listener:
    websocket: WebSocket
    hello: Hello
    slicer: WindowSlicer
    events: EventMerger
    connected_since_ms: int = field(default_factory=now_ms)
    next_seq: int = 0
    last_frame_ms: int | None = None
    frames_received: int = 0
    frames_missing: int = 0
    battery_pct: int | None = None
    paused: bool = False
    pending_ask_id: str | None = None
    pending_ask_sent_ms: int = 0

    @property
    def room(self) -> str:
        return self.hello.room

    def ask_pending(self) -> bool:
        return self.pending_ask_id is not None and now_ms() - self.pending_ask_sent_ms < ASK_TIMEOUT_MS


class Hub:
    def __init__(self, token: str, hub_id: str, classifier: SoundClassifier):
        self._token = token.encode()
        self.hub_id = hub_id
        self.classifier = classifier
        self.categorizer = Categorizer(classifier.labels)
        self.listeners: dict[str, Listener] = {}  # by room: one listener per room
        self.started_ms = now_ms()

    def token_matches(self, token: str) -> bool:
        return secrets.compare_digest(token.encode(), self._token)

    async def serve_listener(self, websocket: WebSocket) -> None:
        scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not self.token_matches(token):
            await websocket.close()  # closing before accepting refuses the upgrade with HTTP 403
            return
        await websocket.accept()
        listener = None
        try:
            hello = await self._receive_hello(websocket)
            if hello is None:
                return
            await self._replace_older_connections(hello)
            listener = Listener(websocket, hello, self._new_slicer(), EventMerger(self.classifier.window_ms))
            self.listeners[hello.room] = listener
            await websocket.send_json(
                {
                    "type": "welcome",
                    "protocol": PROTOCOL_VERSION,
                    "hub_id": self.hub_id,
                    "hub_time_ms": now_ms(),
                    "paused": False,  # the family's pause arrives with the Firestore sync (E8)
                }
            )
            phone = hello.device_model or "unknown phone"
            print(f"{hello.room:<12} connected: {phone}, app {hello.app_version or '?'}")
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self._handle_frame(listener, message["bytes"])
                elif message.get("text") is not None:
                    await self._handle_text(listener, message["text"])
        except WebSocketDisconnect:
            pass
        finally:
            if listener:
                for event in listener.events.close_all():
                    print_event(listener.room, event)
                if self.listeners.get(listener.room) is listener:
                    del self.listeners[listener.room]
                    print(f"{listener.room:<12} disconnected")

    async def ask(self, listener: Listener, reason: str) -> str:
        """Tell a phone to play the check-in question (the voice check in docs/api-contract.md)."""
        ask_id = f"{listener.room}-{now_ms()}"
        await listener.websocket.send_json(
            {"type": "ask", "ask_id": ask_id, "reason": reason, "text": CHECKIN_TEXT, "lang": CHECKIN_LANG}
        )
        listener.pending_ask_id = ask_id
        listener.pending_ask_sent_ms = now_ms()
        print(f"{listener.room:<12} asked: {CHECKIN_TEXT}")
        return ask_id

    def devices(self) -> list[dict]:
        return [
            {
                "device_id": str(listener.hello.device_id),
                "room": listener.room,
                "connected_since_ms": listener.connected_since_ms,
                "last_frame_ms": listener.last_frame_ms,
                "frames_received": listener.frames_received,
                "frames_missing": listener.frames_missing,
                "battery_pct": listener.battery_pct,
                "paused": listener.paused,
            }
            for listener in self.listeners.values()
        ]

    async def _receive_hello(self, websocket: WebSocket) -> Hello | None:
        try:
            message = await asyncio.wait_for(websocket.receive(), HELLO_TIMEOUT_S)
        except TimeoutError:
            await refuse(websocket, f"no hello within {HELLO_TIMEOUT_S} s")
            return None
        if message["type"] == "websocket.disconnect":
            return None
        if message.get("text") is None:
            await refuse(websocket, "audio before hello")
            return None
        try:
            return Hello.model_validate_json(message["text"])
        except ValidationError as error:
            await refuse(websocket, describe(error))
            return None

    async def _replace_older_connections(self, hello: Hello) -> None:
        """Keep one listener per room; a phone that reconnects also replaces its own older connection."""
        for older in list(self.listeners.values()):
            if older.room == hello.room or older.hello.device_id == hello.device_id:
                del self.listeners[older.room]
                print(f"{older.room:<12} replaced by a newer connection")
                with contextlib.suppress(WebSocketDisconnect):
                    await older.websocket.close(CLOSE_REPLACED, "replaced by a newer connection")

    async def _handle_frame(self, listener: Listener, frame: bytes) -> None:
        if len(frame) != FRAME_BYTES:
            message = f"frame must be {FRAME_BYTES} bytes, got {len(frame)}"
            await send_error(listener.websocket, "bad_frame", message)
            return
        capture_ms, seq, samples = parse_frame(frame)
        if seq != listener.next_seq:
            # Frames were skipped, so the audio is no longer continuous: start the windows afresh.
            listener.frames_missing += max(0, seq - listener.next_seq)
            listener.slicer = self._new_slicer()
        listener.next_seq = seq + 1
        listener.frames_received += 1
        listener.last_frame_ms = now_ms()

        frame_start = listener.slicer.samples_pushed
        for start, window in listener.slicer.push(samples):
            window_ms = capture_ms + (start - frame_start) * 1000 // SAMPLE_RATE
            detections = self.categorizer.detect(self.classifier.scores(window))
            for event in listener.events.push(window_ms, detections):
                print_event(listener.room, event)

    async def _handle_text(self, listener: Listener, text: str) -> None:
        try:
            message = parse_message(text)
        except ValueError as error:
            await send_error(listener.websocket, "bad_message", describe(error))
            return
        match message:
            case Heartbeat():
                listener.battery_pct = message.battery_pct
                listener.paused = message.paused
                charging = ", charging" if message.charging else ""
                paused = ", paused" if message.paused else ""
                print(f"{listener.room:<12} heartbeat: battery {message.battery_pct}%{charging}{paused}")
            case Light():
                print(f"{listener.room:<12} light {message.state} ({message.lux:.0f} lux) at {clock(message.ts_ms)}")
            case AskPlayed() if message.ask_id == listener.pending_ask_id:
                listener.pending_ask_id = None
                outcome = "played" if message.ok else f"not played ({message.reason or 'no reason given'})"
                print(f"{listener.room:<12} check-in question {outcome}")

    def _new_slicer(self) -> WindowSlicer:
        return WindowSlicer(window=self.classifier.window_samples, hop=HOP_SAMPLES)


def create_app(hub: Hub) -> FastAPI:
    app = FastAPI(title="Nonna Watch hub")
    bearer = HTTPBearer(auto_error=False)

    def require_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
        if credentials is None or not hub.token_matches(credentials.credentials):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or wrong token")

    @app.get("/health")
    def health() -> dict:
        uptime_s = (now_ms() - hub.started_ms) // 1000
        return {"status": "ok", "hub_id": hub.hub_id, "version": version("nonna-hub"), "uptime_s": uptime_s}

    @app.get("/devices", dependencies=[Depends(require_token)])
    def devices() -> list[dict]:
        return hub.devices()

    @app.post("/ask", dependencies=[Depends(require_token)])
    async def ask(room: Room) -> dict:
        listener = hub.listeners.get(room)
        if listener is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no listener is connected in {room}")
        if listener.ask_pending():
            raise HTTPException(status.HTTP_409_CONFLICT, f"{room} has not answered the previous ask yet")
        try:
            return {"ask_id": await hub.ask(listener, reason="manual")}
        except WebSocketDisconnect:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"the {room} listener just left") from None

    @app.websocket("/ws/listener")
    async def listener_socket(websocket: WebSocket) -> None:
        await hub.serve_listener(websocket)

    return app


def serve(token: str, hub_id: str, port: int) -> None:
    hub = Hub(token, hub_id, SoundClassifier())
    print(f"Phones connect to ws://{lan_address()}:{port}/ws/listener with HUB_TOKEN from hub/.env")
    uvicorn.run(create_app(hub), host="0.0.0.0", port=port)


async def refuse(websocket: WebSocket, reason: str) -> None:
    await send_error(websocket, "bad_hello", reason)
    short_reason = reason.encode()[:120].decode(errors="ignore")  # a close reason may be at most 123 bytes
    await websocket.close(CLOSE_BAD_HELLO, short_reason)


async def send_error(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json({"type": "error", "code": code, "message": message})


def describe(error: ValueError) -> str:
    """One short line for the phone's log, such as "room: Input should be 'kitchen', ..."."""
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return f"{where}: {first['msg']}" if where else first["msg"]
    return str(error)


def print_event(room: str, event: Event) -> None:
    print(f"{room:<12} {clock(event.start_ms)} to {clock(event.end_ms)}   {event.summary()}")


def clock(epoch_ms: int) -> str:
    """Local time with tenths of a second, such as 14:03:12.5."""
    return time.strftime("%H:%M:%S", time.localtime(epoch_ms / 1000)) + f".{epoch_ms % 1000 // 100}"


def lan_address() -> str:
    """This laptop's address on the Wi-Fi or hotspot. Connecting a UDP socket sends no packet."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"
