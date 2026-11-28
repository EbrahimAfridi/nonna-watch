"""The listener <-> hub wire format, protocol 1. The spec is docs/api-contract.md."""

import json
import struct
import time
from typing import Annotated, Literal, get_args
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field, StringConstraints

from nonna_hub.audio import CHUNK_SAMPLES

PROTOCOL_VERSION = 1
FRAME_HEADER = struct.Struct("<qI")  # capture_ms (int64), seq (uint32), little-endian
FRAME_BYTES = FRAME_HEADER.size + 2 * CHUNK_SAMPLES  # 32,012

CLOSE_BAD_HELLO = 4400
CLOSE_REPLACED = 4409

Room = Literal["kitchen", "bathroom", "bedroom", "living_room", "hallway"]
ROOMS = get_args(Room)

# Text from a phone ends up in the hub's console, so only short printable ASCII is accepted.
PrintableText = Annotated[str, StringConstraints(max_length=80, pattern=r"^[ -~]*$")]


class Hello(BaseModel):
    type: Literal["hello"]
    protocol: Literal[1]
    device_id: UUID
    room: Room
    sample_rate: Literal[16_000]
    app_version: PrintableText = ""
    device_model: PrintableText = ""


class Heartbeat(BaseModel):
    type: Literal["heartbeat"]
    ts_ms: int
    battery_pct: int = Field(ge=0, le=100)
    charging: bool
    paused: bool


class Light(BaseModel):
    type: Literal["light"]
    ts_ms: int
    state: Literal["dark", "bright"]
    lux: float = Field(ge=0)


class AskPlayed(BaseModel):
    type: Literal["ask_played"]
    ask_id: PrintableText
    ok: bool
    started_ms: int | None = None
    ended_ms: int | None = None
    reason: PrintableText = ""


PHONE_MESSAGES = {"heartbeat": Heartbeat, "light": Light, "ask_played": AskPlayed}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def parse_message(text: str) -> Heartbeat | Light | AskPlayed | None:
    """Validate a text message from a phone. Unknown types give None: the contract says ignore them."""
    message = json.loads(text)
    kind = message.get("type") if isinstance(message, dict) else None
    if not isinstance(kind, str):
        raise ValueError("a message must be a JSON object with a string type")
    model = PHONE_MESSAGES.get(kind)
    return model.model_validate(message) if model else None


def parse_frame(frame: bytes) -> tuple[int, int, np.ndarray]:
    """Split one audio frame into capture_ms, seq and 1 s of samples as float32 in [-1, 1]."""
    capture_ms, seq = FRAME_HEADER.unpack_from(frame)
    pcm = np.frombuffer(frame, dtype="<i2", offset=FRAME_HEADER.size)
    return capture_ms, seq, pcm.astype(np.float32) / 32768


def encode_frame(capture_ms: int, seq: int, samples: np.ndarray) -> bytes:
    """What a phone sends: the inverse of parse_frame, from float samples in [-1, 1]."""
    pcm = np.clip(np.round(samples * 32768), -32768, 32767).astype("<i2")
    return FRAME_HEADER.pack(capture_ms, seq) + pcm.tobytes()
