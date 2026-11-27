"""A stand-in listener phone: streams audio files or the laptop mic to a hub, as the Android app will.

It speaks protocol 1 (docs/api-contract.md), so the hub can be tested before the app exists.
"""

import asyncio
import contextlib
import json
import sys
import time
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from nonna_hub.audio import SAMPLE_RATE, file_chunks, microphone_chunks
from nonna_hub.protocol import PROTOCOL_VERSION, encode_frame, now_ms

HEARTBEAT_EVERY_FRAMES = 30  # one per 30 s of audio, like the app
PRETEND_PLAYBACK_S = 2


def run(hub_url: str, token: str, room: str, files: list[Path]) -> None:
    if files:
        chunks = paced([chunk for path in files for chunk in file_chunks(path)])
    else:
        chunks = microphone_chunks()
    try:
        asyncio.run(stream(hub_url, token, room, chunks))
    except KeyboardInterrupt:
        pass
    except InvalidStatus as error:
        sys.exit(f"The hub refused the connection: HTTP {error.response.status_code} (wrong token?)")
    except ConnectionClosed as error:
        sys.exit(f"The hub closed the connection: {error}")
    except OSError as error:
        sys.exit(f"Cannot reach the hub at {hub_url}: {str(error) or 'no welcome within 10 s'}")


def paced(chunks: Iterable[np.ndarray]) -> Iterator[np.ndarray]:
    """Release one chunk per second, as a phone recording in real time does."""
    for chunk in chunks:
        time.sleep(1)
        yield chunk


async def stream(hub_url: str, token: str, room: str, chunks: Iterator[np.ndarray]) -> None:
    async with connect(hub_url, additional_headers={"Authorization": f"Bearer {token}"}) as hub:
        hello = {
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "device_id": str(uuid.uuid4()),
            "room": room,
            "sample_rate": SAMPLE_RATE,
            "app_version": "fake-phone",
            "device_model": "laptop",
        }
        await hub.send(json.dumps(hello))
        print(f"hub: {await asyncio.wait_for(hub.recv(), timeout=10)}")
        replies = asyncio.create_task(answer(hub))
        seq = 0
        try:
            # The mic blocks for a second per chunk, so it is read off the event loop.
            while (chunk := await asyncio.to_thread(next, chunks, None)) is not None:
                if seq % HEARTBEAT_EVERY_FRAMES == 0:
                    heartbeat = {
                        "type": "heartbeat",
                        "ts_ms": now_ms(),
                        "battery_pct": 100,
                        "charging": True,
                        "paused": False,
                    }
                    await hub.send(json.dumps(heartbeat))
                await hub.send(encode_frame(now_ms() - 1000, seq, chunk))
                seq += 1
        finally:
            replies.cancel()
    print(f"Sent {seq} s of audio")


async def answer(hub: ClientConnection) -> None:
    """Print what the hub says, and answer an ask as the app would, minus the actual sound."""
    with contextlib.suppress(ConnectionClosed):  # stream() reports why the connection ended
        async for message in hub:
            print(f"hub: {message[:200]}")
            request = json.loads(message)
            if request.get("type") == "ask":
                started_ms = now_ms()
                await asyncio.sleep(PRETEND_PLAYBACK_S)
                played = {
                    "type": "ask_played",
                    "ask_id": request["ask_id"],
                    "ok": True,
                    "started_ms": started_ms,
                    "ended_ms": now_ms(),
                }
                await hub.send(json.dumps(played))
