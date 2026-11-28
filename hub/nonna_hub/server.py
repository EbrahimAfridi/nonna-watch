"""The hub server: listener phones stream audio over a WebSocket, as docs/api-contract.md describes.

Each phone's audio becomes household events (YAMNet) and help words (VAD and Whisper), printed with
the room. The detection rules turn them into alerts for the family's Telegram group, with the voice
check ("Are you okay?") before or after them as CONTEXT.md section 4 says.
"""

import asyncio
import contextlib
import secrets
import socket
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from importlib.metadata import version

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from nonna_cloud.checks import Checker
from nonna_cloud.routine import Finding
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnected

from nonna_hub.audio import SAMPLE_RATE, WindowSlicer
from nonna_hub.categories import Categorizer
from nonna_hub.events import Event, EventMerger
from nonna_hub.help_words import DEFAULT_HELP_WORDS
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
from nonna_hub.cloud_sync import CloudSync, listener_id, timestamp
from nonna_hub.rules import CHECK_AFTER, CHECK_FIRST, Alert, RoomRules, follow_up_message
from nonna_hub.sound import HOP_SAMPLES, SoundClassifier
from nonna_hub.speech import SpeechListener, Transcriber, Utterance
from nonna_hub.telegram import Telegram, TelegramError
from nonna_hub.voice_check import (
    ANSWER_WAIT_S,
    ASK_PLAYED_TIMEOUT_S,
    QUESTIONS,
    VoiceCheck,
    is_question,
    starts_during_question,
)

HELLO_TIMEOUT_S = 10
OFFLINE_AFTER_MS = 5 * 60_000  # CONTEXT.md section 4: no heartbeat from a listener for 5 min
HEARTBEAT_MS = 5 * 60_000  # the hub's Firestore heartbeats, which the cloud and the family app read
WATCH_EVERY_S = 30
ROUTINE_EVERY_S = 15 * 60  # E9: B's routine and silence checks (cloud/), in billing Path B

# The phone hung up, or the hub itself closed that connection because a newer one replaced it
# (Starlette raises WebSocketDisconnected for a socket the app already closed).
PHONE_GONE = (WebSocketDisconnect, WebSocketDisconnected)


@dataclass
class Listener:
    websocket: WebSocket
    hello: Hello
    slicer: WindowSlicer
    events: EventMerger
    speech: SpeechListener
    rules: RoomRules = field(default_factory=RoomRules)
    voice_check: VoiceCheck | None = None  # at most one check per room at a time
    connected_since_ms: int = field(default_factory=now_ms)
    next_seq: int = 0
    last_frame_ms: int | None = None
    frames_received: int = 0
    frames_missing: int = 0
    battery_pct: int | None = None
    paused: bool = False

    @property
    def room(self) -> str:
        return self.hello.room


class Hub:
    def __init__(
        self,
        token: str,
        hub_id: str,
        classifier: SoundClassifier,
        new_speech_listener: Callable[[], SpeechListener],
        send_alert: Callable[[str], None] | None = None,
        checkin_language: str = "en",
        sync: CloudSync | None = None,
        checker: Checker | None = None,
    ):
        self._token = token.encode()
        self.hub_id = hub_id
        self.classifier = classifier
        self.categorizer = Categorizer(classifier.labels)
        self._new_speech_listener = new_speech_listener
        self._send_alert = send_alert
        self._sync = sync
        self._checker = checker
        self._findings_done: set[str] = set()  # alert ids answered fine or sent, so not asked again
        self._heartbeat_ms = 0  # when the hub last wrote its heartbeats
        self._question = QUESTIONS[checkin_language]
        self._tasks: set[asyncio.Task] = set()  # background work, held so it is not garbage-collected
        self.listeners: dict[str, Listener] = {}  # by room: one listener per room
        self.last_heard_ms: dict[str, int] = {}  # by room, kept after a phone leaves to notice it is gone
        self._offline: set[str] = set()  # rooms already reported offline
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
            listener = Listener(
                websocket,
                hello,
                self._new_slicer(),
                EventMerger(self.classifier.window_ms),
                self._new_speech_listener(),
            )
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
            self._heard_from(hello.room)
            self._write_phone(hello.room)  # the family app sees a new phone at once, not at the next heartbeat
            try:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    self._heard_from(listener.room)
                    if message.get("bytes") is not None:
                        await self._handle_frame(listener, message["bytes"])
                    elif message.get("text") is not None:
                        await self._handle_text(listener, message["text"])
            except PHONE_GONE:
                pass  # gone in the middle of a reply; what it said last is written down below
            # A phone that drops right after "aiuto" must still raise the help word.
            for said in await asyncio.to_thread(listener.speech.flush):
                await self._on_speech(listener, said)
        except PHONE_GONE:
            pass
        finally:
            if listener:
                for event in listener.events.close_all():
                    self._event_ended(listener, event)
                if self.listeners.get(listener.room) is listener:
                    del self.listeners[listener.room]
                    print(f"{listener.room:<12} disconnected")

    async def start_voice_check(
        self,
        listener: Listener,
        alert: Alert | None = None,
        alert_sent: bool = False,
        reason: str = "manual",
        detected: tuple[int, int] | None = None,
    ) -> VoiceCheck:
        """Have the phone ask "Are you okay?", then wait for the answer in the background."""
        text, lang = self._question
        check = VoiceCheck(f"{listener.room}-{now_ms()}", alert.kind if alert else reason, alert, alert_sent, detected)
        listener.voice_check = check
        try:
            ask = {"type": "ask", "ask_id": check.ask_id, "reason": check.reason, "text": text, "lang": lang}
            await listener.websocket.send_json(ask)
        except PHONE_GONE:
            listener.voice_check = None
            raise
        print(f"{listener.room:<12} asked: {text}")
        self._in_background(self._finish_voice_check(listener, check))
        return check

    async def stop(self) -> None:
        """Give the queued Firestore writes a few seconds when the hub stops; offline, they are lost."""
        if self._sync:
            await asyncio.to_thread(self._sync.flush, 5)

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
                with contextlib.suppress(*PHONE_GONE):
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
            listener.speech.reset()
        listener.next_seq = seq + 1
        listener.frames_received += 1
        listener.last_frame_ms = now_ms()

        alerts = []
        frame_start = listener.slicer.samples_pushed
        for start, window in listener.slicer.push(samples):
            window_ms = capture_ms + (start - frame_start) * 1000 // SAMPLE_RATE
            detections = self.categorizer.detect(self.classifier.scores(window))
            for event in listener.events.push(window_ms, detections):
                self._event_ended(listener, event)
            alerts += listener.rules.on_window(window_ms, detections)
        await self._act_on(listener, alerts)
        # Whisper takes about a second, so it runs off the event loop and other rooms keep going.
        for said in await asyncio.to_thread(listener.speech.push, samples, capture_ms):
            await self._on_speech(listener, said)

    async def _on_speech(self, listener: Listener, said: Utterance) -> None:
        check = listener.voice_check
        if check and is_question(said, check.sent_ms, check.ended_ms):
            return  # the phone's own question, which can contain "aiuto" or "bene"
        print_help(listener.room, said)
        if check:
            check.hear(said)
        await self._act_on(listener, listener.rules.on_speech(said))

    async def _act_on(self, listener: Listener, alerts: list[Alert]) -> None:
        """Send each alert, with the voice check first or after it (CONTEXT.md section 4)."""
        # Ask through the room's current phone: audio left over from a replaced connection can still
        # raise an alert, but only the connection that replaced it can play the question.
        asker = self.listeners.get(listener.room, listener)
        for alert in alerts:
            if alert.kind in CHECK_FIRST and asker.voice_check is None:
                try:
                    # Timed now: Experiment 1 measures detection, not how long she takes to answer.
                    await self.start_voice_check(asker, alert, detected=(listener.last_frame_ms, now_ms()))
                except PHONE_GONE:
                    self._raise_alert(listener, replace(alert, check_outcome="not_played"))
                continue
            # Also reached by a thud or glass while a check is already running: alert straight away.
            checking = alert.kind in CHECK_AFTER and asker.voice_check is None
            self._raise_alert(listener, alert, checking=checking)
            if checking:
                try:
                    await self.start_voice_check(asker, alert, alert_sent=True)
                except PHONE_GONE:
                    self._update_alert(listener.room, alert, {"voiceCheck": {"asked": True, "result": "not_played"}})

    async def _finish_voice_check(self, listener: Listener, check: VoiceCheck) -> None:
        try:
            played = await asyncio.wait_for(check.played, ASK_PLAYED_TIMEOUT_S)
            if played.ok:
                outcome, detail = await asyncio.wait_for(check.answered, ANSWER_WAIT_S)
            else:
                outcome, detail = "not_played", played.reason
        except TimeoutError:
            outcome, detail = ("no_answer", "") if check.ended_ms is not None else ("not_played", "no ask_played")
        finally:
            if listener.voice_check is check:
                listener.voice_check = None
        print(f"{listener.room:<12} {clock(now_ms())}   CHECK        {check.reason}: {outcome} {detail}".rstrip())
        check.done.set_result((outcome, detail))
        if outcome == "fine" and check.alert:
            # Otherwise a real fall or "aiuto" within a minute of "sto bene" would be swallowed.
            listener.rules.reassured(check.alert.kind)

        if check.alert is None:
            return  # asked for through POST /ask: the line above is the whole result
        if not check.alert_sent:
            if outcome != "fine":
                self._raise_alert(listener, replace(check.alert, check_outcome=outcome), detected=check.detected)
            return
        stored = {"voiceCheck": {"asked": True, "result": outcome}}
        if outcome == "fine":
            print(f"{listener.room:<12} {clock(check.alert.at_ms)}   FOLLOW-UP    answered \"{detail}\"")
            message = follow_up_message(check.alert, listener.room, detail)
            stored["followUp"] = message
            self._deliver_later(listener.room, check.alert.at_ms, message)
        self._update_alert(listener.room, check.alert, stored)

    async def watch_listeners(self) -> None:
        """Every 30 s, report rooms whose phone went quiet; every 5 minutes, write the heartbeats."""
        while True:
            for room, heard_ms in self.last_heard_ms.items():
                if room not in self._offline and now_ms() - heard_ms >= OFFLINE_AFTER_MS:
                    self._offline.add(room)
                    self._announce(room, Alert("offline", heard_ms))
            if now_ms() - self._heartbeat_ms >= HEARTBEAT_MS:
                self._write_heartbeats()
            await asyncio.sleep(WATCH_EVERY_S)

    async def watch_routines(self) -> None:
        """Every 15 minutes, B's routine and silence checks, asking "Are you okay?" first as the table says."""
        while self._checker:
            await asyncio.sleep(ROUTINE_EVERY_S)
            try:
                for finding in await asyncio.to_thread(self._checker.run):
                    await self._on_finding(finding)
            except (Exception, SystemExit) as error:  # nonna_cloud exits on a missing home: keep the hub up
                print(f"Routine checks failed, trying again in 15 minutes: {error}")

    async def _on_finding(self, finding: Finding) -> None:
        # The checker finds a missed routine again on every run until an alert exists for it today.
        if finding.alert_id in self._findings_done:
            return
        place = finding.room or "home"
        voice_result = await self._ask_about(finding) if finding.voice_check else None
        if voice_result == "busy":
            return  # asked on the next run instead of reported without asking
        self._findings_done.add(finding.alert_id)
        if voice_result == "fine":
            print(f"{place:<12} {clock(now_ms())}   CHECK        {finding.type}: fine, not reported")
            return
        at_ms = int(finding.time.timestamp() * 1000)
        after_check = f" after the check: {voice_result}" if voice_result else ""
        print(f"{place:<12} {clock(at_ms)}   ALERT        {finding.type}{after_check}")
        self._deliver_later(place, at_ms, finding.message)  # the family hears it even if Firestore is down
        try:
            await asyncio.to_thread(self._checker.report, finding, voice_result)
        except Exception as error:
            print(f"{place:<12} {clock(at_ms)}   NOT STORED   {finding.alert_id}: {error}")

    async def _ask_about(self, finding: Finding) -> str | None:
        """Ask in the finding's room, or in every room when the whole home is silent. Help anywhere wins.

        None means no phone to ask through; "busy" means every phone is already in another check.
        """
        rooms = [finding.room] if finding.room else list(self.listeners)
        phones = [self.listeners[room] for room in rooms if room in self.listeners]
        if not phones:
            return None
        askers = [listener for listener in phones if listener.voice_check is None]
        if not askers:
            return "busy"
        outcomes = await asyncio.gather(*(self._ask_and_wait(listener, finding.type) for listener in askers))
        for outcome in ("help", "fine"):
            if outcome in outcomes:
                return outcome
        return outcomes[0]

    async def _ask_and_wait(self, listener: Listener, reason: str) -> str:
        try:
            check = await self.start_voice_check(listener, reason=reason)
        except PHONE_GONE:
            return "not_played"
        outcome, _detail = await check.done
        return outcome

    def _write_heartbeats(self) -> None:
        """devices/hub, which the cloud watches to notice a dead hub, and one document per room's phone."""
        self._heartbeat_ms = now_ms()
        if not self._sync:
            return
        hub = {"kind": "hub", "room": "", "lastHeartbeat": timestamp(self._heartbeat_ms), "online": True, "target": "hub"}
        self._sync.device(self.hub_id, hub)
        for room in self.last_heard_ms:
            self._write_phone(room)

    def _write_phone(self, room: str) -> None:
        if not self._sync:
            return
        phone = {
            "kind": "listener",
            "room": room,
            "lastHeartbeat": timestamp(self.last_heard_ms[room]),
            "online": room not in self._offline,
            "target": "hub",
        }
        listener = self.listeners.get(room)
        if listener and listener.battery_pct is not None:
            phone["battery"] = listener.battery_pct
        self._sync.device(listener_id(room), phone)

    def _heard_from(self, room: str) -> None:
        self.last_heard_ms[room] = now_ms()
        if room in self._offline:
            self._offline.discard(room)
            self._announce(room, Alert("back_online", now_ms()))

    def _announce(self, room: str, alert: Alert) -> None:
        """A phone went quiet or came back: there is no sound behind it to time."""
        print(f"{room:<12} {clock(alert.at_ms)}   ALERT        {alert.kind}")
        if self._sync:
            self._sync.alert(room, alert, voice_check=None, timings=None)
            self._sync.device(listener_id(room), {"online": alert.kind == "back_online"})
        self._deliver_later(room, alert.at_ms, alert.message(room))

    def _raise_alert(
        self,
        listener: Listener,
        alert: Alert,
        checking: bool = False,
        detected: tuple[int, int] | None = None,
    ) -> None:
        """Print the alert with how long it took to get here, store it, then send it without waiting."""
        received_ms, detected_ms = detected or (listener.last_frame_ms, now_ms())
        received_s = (received_ms - alert.at_ms) / 1000
        detected_s = (detected_ms - alert.at_ms) / 1000
        after_check = f"after the check: {alert.check_outcome}" if alert.check_outcome else ""
        what = " ".join(part for part in (alert.kind, alert.detail, after_check) if part)
        timing = f"received +{received_s:.1f} s, detected +{detected_s:.1f} s"
        print(f"{listener.room:<12} {clock(alert.at_ms)}   ALERT        {what}   {timing}")
        if self._sync:
            timings = {"capturedMs": alert.at_ms, "hubReceivedMs": received_ms, "aiDoneMs": detected_ms}
            voice_check = alert.check_outcome or ("pending" if checking else None)
            self._sync.alert(listener.room, alert, voice_check, timings)
        self._deliver_later(listener.room, alert.at_ms, alert.message(listener.room), timed_alert=alert)

    def _update_alert(self, room: str, alert: Alert, fields: dict) -> None:
        if self._sync:
            self._sync.update_alert(room, alert, fields)

    def _event_ended(self, listener: Listener, event: Event) -> None:
        print_event(listener.room, event)
        check = listener.voice_check
        if check and starts_during_question(event.start_ms, check.sent_ms, check.ended_ms):
            return  # the phone playing "Are you okay?" is not activity in the home
        if self._sync:
            self._sync.event(listener.room, event)

    def _deliver_later(self, room: str, at_ms: int, text: str, timed_alert: Alert | None = None) -> None:
        if self._send_alert:
            self._in_background(self._deliver(room, at_ms, text, timed_alert))

    async def _deliver(self, room: str, at_ms: int, text: str, timed_alert: Alert | None) -> None:
        try:
            await asyncio.to_thread(self._send_alert, text)
        except (OSError, TelegramError) as error:
            print(f"{room:<12} {clock(at_ms)}   NOT SENT     {error}")
            return
        sent_ms = now_ms()
        print(f"{room:<12} {clock(at_ms)}   SENT         +{(sent_ms - at_ms) / 1000:.1f} s after the sound")
        if timed_alert:
            self._update_alert(room, timed_alert, {"timings": {"alertSentMs": sent_ms}})

    def _in_background(self, work: Coroutine) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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
            case AskPlayed():
                self._on_ask_played(listener, message)

    def _on_ask_played(self, listener: Listener, message: AskPlayed) -> None:
        check = listener.voice_check
        if check is None or message.ask_id != check.ask_id or check.played.done():
            return
        if message.ok:
            check.ended_ms = message.ended_ms or now_ms()
        check.played.set_result(message)
        outcome = "played" if message.ok else f"not played ({message.reason or 'no reason given'})"
        print(f"{listener.room:<12} check-in question {outcome}")

    def _new_slicer(self) -> WindowSlicer:
        return WindowSlicer(window=self.classifier.window_samples, hop=HOP_SAMPLES)


def create_app(hub: Hub) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        watchers = [asyncio.create_task(hub.watch_listeners()), asyncio.create_task(hub.watch_routines())]
        yield
        for watcher in watchers:
            watcher.cancel()
        await hub.stop()

    app = FastAPI(title="Nonna Watch hub", lifespan=lifespan)
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
        if listener.voice_check:
            raise HTTPException(status.HTTP_409_CONFLICT, f"a voice check is already running in {room}")
        try:
            return {"ask_id": (await hub.start_voice_check(listener)).ask_id}
        except PHONE_GONE:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"the {room} listener just left") from None

    @app.websocket("/ws/listener")
    async def listener_socket(websocket: WebSocket) -> None:
        await hub.serve_listener(websocket)

    return app


def serve(
    token: str,
    hub_id: str,
    port: int,
    languages: list[str],
    telegram: Telegram | None,
    sync: CloudSync | None,
    routine_checks: bool = False,
) -> None:
    transcriber = Transcriber()
    hub = Hub(
        token,
        hub_id,
        SoundClassifier(),
        lambda: SpeechListener(transcriber, languages, DEFAULT_HELP_WORDS),
        send_alert=telegram.send if telegram else None,
        checkin_language=languages[0],
        sync=sync,
        checker=Checker(sync.db, sync.home_id) if sync and routine_checks else None,
    )
    print(f"Phones connect to ws://{lan_address()}:{port}/ws/listener with HUB_TOKEN from hub/.env")
    print(f"Listening for help words in: {', '.join(languages)}. Check-in question: {QUESTIONS[languages[0]][0]}")
    if telegram:
        print("Alerts go to the Telegram group in TELEGRAM_CHAT_ID")
    else:
        print("Telegram is not set up, so alerts only appear here (see hub/README.md)")
    if sync:
        print(f"Events, alerts and heartbeats go to Firestore under homes/{sync.home_id}")
    else:
        print("Firestore is not set up, so nothing is stored in the cloud (see hub/README.md)")
    if routine_checks:
        print("Routine and silence checks run here every 15 minutes (billing Path B)")
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


def print_help(room: str, said: Utterance) -> None:
    """Only speech with a help word is shown, so the hub keeps no running record of what is said."""
    if not said.help_words:
        return
    texts = "   ".join(f"[{language}] {text}" for language, text in said.texts.items())
    when = f"{clock(said.start_ms)} to {clock(said.end_ms)}"
    print(f"{room:<12} {when}   HELP         {', '.join(said.help_words)}   {texts}")


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
