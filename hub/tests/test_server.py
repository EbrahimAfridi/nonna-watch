import uuid
from contextlib import contextmanager

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nonna_hub.protocol import encode_frame
from nonna_hub.server import Hub, create_app
from nonna_hub.sound import SoundClassifier

TOKEN = "test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def classifier():
    return SoundClassifier()


@pytest.fixture
def client(classifier):
    with TestClient(create_app(Hub(TOKEN, "test-hub", classifier))) as client:
        yield client


def hello(room="kitchen", device_id=None):
    device_id = device_id or str(uuid.uuid4())
    return {"type": "hello", "protocol": 1, "device_id": device_id, "room": room, "sample_rate": 16_000}


@contextmanager
def phone(client, room="kitchen", device_id=None):
    with client.websocket_connect("/ws/listener", headers=AUTH) as websocket:
        websocket.send_json(hello(room, device_id))
        assert websocket.receive_json()["type"] == "welcome"
        yield websocket


def frame(seq, samples=None):
    if samples is None:
        samples = np.zeros(16_000, dtype=np.float32)
    return encode_frame(1_795_698_192_000 + 1000 * seq, seq, samples)


def wait_until_handled(websocket):
    """The hub handles a phone's messages in order, so its reply to a broken one means earlier ones are done."""
    websocket.send_text("not json")
    reply = websocket.receive_json()
    assert reply["code"] == "bad_message" and reply["message"].startswith("Expecting value"), reply


def devices(client):
    return client.get("/devices", headers=AUTH).json()


def test_wrong_token_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/listener", headers={"Authorization": "Bearer wrong"}):
            pass


def test_hello_is_welcomed(client):
    with client.websocket_connect("/ws/listener", headers=AUTH) as websocket:
        websocket.send_json(hello())
        welcome = websocket.receive_json()

    assert (welcome["type"], welcome["protocol"], welcome["hub_id"], welcome["paused"]) == ("welcome", 1, "test-hub", False)


def test_unknown_room_is_refused_with_4400(client):
    with client.websocket_connect("/ws/listener", headers=AUTH) as websocket:
        websocket.send_json(hello(room="garage"))
        error = websocket.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert error["code"] == "bad_hello" and error["message"].startswith("room:")
    assert closed.value.code == 4400


def test_audio_before_hello_is_refused_with_4400(client):
    with client.websocket_connect("/ws/listener", headers=AUTH) as websocket:
        websocket.send_bytes(frame(0))
        error = websocket.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert error["message"] == "audio before hello"
    assert closed.value.code == 4400


def test_bad_frame_gets_an_error_and_the_connection_stays_open(client):
    with phone(client) as websocket:
        websocket.send_bytes(bytes(100))
        error = websocket.receive_json()
        websocket.send_bytes(frame(0))
        wait_until_handled(websocket)
        [device] = devices(client)

    assert error == {"type": "error", "code": "bad_frame", "message": "frame must be 32012 bytes, got 100"}
    assert device["frames_received"] == 1


def test_unknown_message_types_are_ignored(client):
    with phone(client) as websocket:
        websocket.send_json({"type": "added_in_protocol_2", "anything": 1})
        wait_until_handled(websocket)  # fails if the unknown type got an error reply first


def test_phone_audio_is_labelled_under_its_room(client, capsys):
    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(16_000) / 16_000)
    with phone(client, room="bedroom") as websocket:
        websocket.send_bytes(frame(0, tone))
        wait_until_handled(websocket)

    lines = [line for line in capsys.readouterr().out.splitlines() if "Sine wave" in line]
    assert lines and lines[0].startswith("bedroom")


def test_skipped_frames_are_counted(client):
    with phone(client) as websocket:
        for seq in (0, 1, 4):
            websocket.send_bytes(frame(seq))
        wait_until_handled(websocket)
        [device] = devices(client)

    assert (device["frames_received"], device["frames_missing"]) == (3, 2)


def test_heartbeat_updates_battery_and_pause(client):
    with phone(client) as websocket:
        websocket.send_json({"type": "heartbeat", "ts_ms": 1, "battery_pct": 87, "charging": False, "paused": True})
        wait_until_handled(websocket)
        [device] = devices(client)

    assert (device["battery_pct"], device["paused"]) == (87, True)


def test_newer_connection_for_the_same_room_replaces_the_older(client):
    newer_id = str(uuid.uuid4())
    with phone(client) as older:
        with phone(client, device_id=newer_id):
            with pytest.raises(WebSocketDisconnect) as closed:
                older.receive_json()
            connected = [device["device_id"] for device in devices(client)]

    assert closed.value.code == 4409
    assert connected == [newer_id]


def test_rest_needs_the_token_except_health(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/devices").status_code == 401
    assert client.get("/devices", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/devices", headers=AUTH).json() == []


def test_ask_reaches_the_phone_and_waits_for_ask_played(client):
    def ask_kitchen():
        return client.post("/ask", params={"room": "kitchen"}, headers=AUTH)

    assert ask_kitchen().status_code == 404
    with phone(client) as websocket:
        ask_id = ask_kitchen().json()["ask_id"]
        ask = websocket.receive_json()
        while_waiting = ask_kitchen().status_code
        websocket.send_json({"type": "ask_played", "ask_id": ask_id, "ok": True, "started_ms": 1, "ended_ms": 2})
        wait_until_handled(websocket)
        after_played = ask_kitchen().status_code

    assert (ask["type"], ask["ask_id"], ask["reason"]) == ("ask", ask_id, "manual")
    assert (while_waiting, after_played) == (409, 200)
