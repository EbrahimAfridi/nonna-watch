import time
import uuid
from contextlib import contextmanager

import numpy as np
import pytest
from fakes import FakeWhisper, ScriptedWhisper, ThudInWindows, loud_parts
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nonna_hub import server
from nonna_hub.help_words import DEFAULT_HELP_WORDS
from nonna_hub.protocol import encode_frame, now_ms
from nonna_hub.server import Hub, create_app
from nonna_hub.sound import SoundClassifier
from nonna_hub.speech import SpeechListener

TOKEN = "test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def classifier():
    return SoundClassifier()


@pytest.fixture
def sent_alerts():
    return []


@pytest.fixture
def client(classifier, sent_alerts):
    def speech_listener():
        # Anything loud counts as speech, and Whisper always hears "Aiuto!".
        return SpeechListener(FakeWhisper({"it": "Aiuto!"}), ["it"], DEFAULT_HELP_WORDS, find_speech=loud_parts)

    hub = Hub(TOKEN, "test-hub", classifier, speech_listener, send_alert=sent_alerts.append)
    with TestClient(create_app(hub)) as client:
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
    """The hub handles a phone's messages in order, so its reply to a broken one means earlier ones are done.

    Returns whatever else the hub sent meanwhile, such as an ask.
    """
    websocket.send_text("not json")
    others = []
    while (reply := websocket.receive_json())["type"] != "error":
        others.append(reply)
    assert reply["code"] == "bad_message" and reply["message"].startswith("Expecting value"), reply
    return others


def devices(client):
    return client.get("/devices", headers=AUTH).json()


def eventually(condition, timeout_s=2):
    """Wait for something the hub does in the background, such as sending an alert."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


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


def test_phone_audio_becomes_events_under_its_room(client, capsys):
    beep = 0.5 * np.sin(2 * np.pi * 1_000 * np.arange(16_000) / 16_000)
    with phone(client, room="bedroom") as websocket:
        websocket.send_bytes(frame(0, beep))
        wait_until_handled(websocket)

    lines = [line for line in capsys.readouterr().out.splitlines() if "Beep, bleep" in line]
    assert lines and lines[0].startswith("bedroom") and " alarm " in lines[0]


def test_a_help_word_is_reported_and_sent_to_the_family(client, sent_alerts, capsys):
    speech = np.full(16_000, 0.5, dtype=np.float32)
    with phone(client, room="kitchen") as websocket:
        websocket.send_bytes(frame(0, speech))
        websocket.send_bytes(frame(1))
        wait_until_handled(websocket)
        eventually(lambda: sent_alerts)

    output = capsys.readouterr().out.splitlines()
    help_lines = [line for line in output if " HELP " in line]
    alert_lines = [line for line in output if " ALERT " in line]
    assert len(help_lines) == 1 and help_lines[0].startswith("kitchen") and "aiuto" in help_lines[0]
    assert len(alert_lines) == 1 and "help_word aiuto" in alert_lines[0]
    assert len(sent_alerts) == 1 and 'Help word "aiuto" heard in the kitchen' in sent_alerts[0]


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


def test_a_room_runs_one_voice_check_at_a_time(client, monkeypatch):
    monkeypatch.setattr(server, "ANSWER_WAIT_S", 0.2)

    def ask_kitchen():
        return client.post("/ask", params={"room": "kitchen"}, headers=AUTH)

    assert ask_kitchen().status_code == 404
    with phone(client) as websocket:
        ask_id = ask_kitchen().json()["ask_id"]
        ask = websocket.receive_json()
        while_running = ask_kitchen().status_code
        websocket.send_json({"type": "ask_played", "ask_id": ask_id, "ok": True, "started_ms": 1, "ended_ms": 2})
        wait_until_handled(websocket)
        eventually(lambda: ask_kitchen().status_code == 200)  # once the answer window has passed

    assert (ask["type"], ask["ask_id"], ask["reason"], ask["text"]) == ("ask", ask_id, "manual", "Are you okay?")
    assert while_running == 409


# The voice check, end to end. Capture times start now, as with a real phone, so that the hub can tell
# speech heard after it asked from speech before.


@contextmanager
def hub_hearing(classifier, whisper, sent, categorizer=None):
    hub = Hub(
        TOKEN,
        "test-hub",
        classifier,
        lambda: SpeechListener(whisper, ["it"], DEFAULT_HELP_WORDS, find_speech=loud_parts),
        send_alert=sent.append,
        checkin_language="it",
    )
    if categorizer:
        hub.categorizer = categorizer
    with TestClient(create_app(hub)) as client:
        yield client


def stream(websocket, start_ms, levels, first_seq=0):
    """Send one second of audio per level, 0.5 for speech and 0 for silence, captured from start_ms."""
    for index, level in enumerate(levels):
        seq = first_seq + index
        samples = np.full(16_000, level, dtype=np.float32)
        websocket.send_bytes(encode_frame(start_ms + 1000 * seq, seq, samples))
    return wait_until_handled(websocket)


def played(websocket, ask, start_ms, ended_after_s):
    ended_ms = start_ms + int(1000 * ended_after_s)
    websocket.send_json({"type": "ask_played", "ask_id": ask["ask_id"], "ok": True, "started_ms": 0, "ended_ms": ended_ms})


def test_a_reassuring_answer_after_a_help_word_sends_a_follow_up(classifier):
    sent = []
    # Whisper hears the shout, then the phone's own question, then the answer.
    whisper = ScriptedWhisper("Aiuto!", "Stai bene?", "Sì, sto bene.")
    start = now_ms()
    with hub_hearing(classifier, whisper, sent) as client, phone(client) as websocket:
        [ask] = stream(websocket, start, [0.5, 0])
        stream(websocket, start, [0.5, 0], first_seq=2)  # the question, heard by the phone's own mic
        played(websocket, ask, start, ended_after_s=3)
        stream(websocket, start, [0.5, 0], first_seq=4)
        eventually(lambda: len(sent) == 2)

    assert ask["text"] == "Stai bene?" and ask["reason"] == "help_word"
    assert 'Help word "aiuto"' in sent[0]
    assert 'the answer to the check-in question was "sto bene"' in sent[1]


def thud_then_ask(websocket, start):
    """A thud, then ten seconds without movement: the hub asks before it alerts."""
    asks = stream(websocket, start, [0] * 11)
    assert [ask["reason"] for ask in asks] == ["thud"]
    return asks[0]


def test_a_thud_without_an_answer_alerts(classifier, monkeypatch):
    monkeypatch.setattr(server, "ANSWER_WAIT_S", 0.2)
    sent = []
    start = now_ms()
    with hub_hearing(classifier, ScriptedWhisper(), sent, ThudInWindows(1)) as client, phone(client) as websocket:
        ask = thud_then_ask(websocket, start)
        assert sent == []
        played(websocket, ask, start, ended_after_s=10.5)
        eventually(lambda: sent)

    assert "possible fall" in sent[0] and "No answer to the check-in question." in sent[0]


def test_a_thud_answered_sto_bene_does_not_alert(classifier, monkeypatch, capsys):
    monkeypatch.setattr(server, "ANSWER_WAIT_S", 0.5)
    sent = []
    start = now_ms()
    with hub_hearing(classifier, ScriptedWhisper("Sto bene"), sent, ThudInWindows(1)) as client:
        with phone(client) as websocket:
            ask = thud_then_ask(websocket, start)
            played(websocket, ask, start, ended_after_s=10.5)
            stream(websocket, start, [0.5, 0], first_seq=11)
            eventually(lambda: "CHECK        thud: fine sto bene" in capsys.readouterr().out)
        time.sleep(0.6)  # past the answer window: nothing may be sent late

    assert sent == []


def test_after_a_reassuring_answer_the_next_thud_is_checked_again(classifier, monkeypatch):
    monkeypatch.setattr(server, "ANSWER_WAIT_S", 0.5)
    start = now_ms()
    # A thud in the first window, the answer "sto bene", then another thud 12.5 s in.
    thuds = ThudInWindows(1, 26)
    with hub_hearing(classifier, ScriptedWhisper("Sto bene"), [], thuds) as client, phone(client) as websocket:
        first = thud_then_ask(websocket, start)
        played(websocket, first, start, ended_after_s=10.5)
        stream(websocket, start, [0.5, 0], first_seq=11)
        asks = stream(websocket, start, [0] * 11, first_seq=13)

    assert [ask["reason"] for ask in asks] == ["thud"]


def test_a_thud_alerts_when_the_phone_cannot_ask(classifier, monkeypatch):
    monkeypatch.setattr(server, "ASK_PLAYED_TIMEOUT_S", 0.2)
    sent = []
    start = now_ms()
    with hub_hearing(classifier, ScriptedWhisper(), sent, ThudInWindows(1)) as client, phone(client) as websocket:
        thud_then_ask(websocket, start)
        eventually(lambda: sent)

    assert "possible fall" in sent[0] and "could not ask the check-in question" in sent[0]


def test_a_phone_that_goes_quiet_is_reported_offline_and_back(classifier, monkeypatch):
    monkeypatch.setattr(server, "OFFLINE_AFTER_MS", 300)
    monkeypatch.setattr(server, "WATCH_EVERY_S", 0.05)
    sent = []
    with hub_hearing(classifier, ScriptedWhisper(), sent) as client:
        with phone(client):
            pass
        eventually(lambda: sent)
        with phone(client):
            eventually(lambda: len(sent) == 2)

    assert "The kitchen listener has sent nothing since" in sent[0]
    assert "The kitchen listener is working again" in sent[1]
