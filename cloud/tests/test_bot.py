"""The Telegram commands (bot.py): what the family sees, and how the bot talks to the hub."""

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nonna_cloud import bot

NOW_MS = int(datetime(2026, 12, 1, 11, 0, tzinfo=timezone.utc).timestamp() * 1000)


def test_commands_are_read_with_or_without_the_bot_name():
    assert bot.parse_command("/status", "nonna_watch_team_bot") == ("status", "")
    assert bot.parse_command("/ask@Nonna_Watch_Team_Bot Living Room", "nonna_watch_team_bot") == ("ask", "living_room")
    assert bot.parse_command("/status@some_other_bot", "nonna_watch_team_bot") is None
    assert bot.parse_command("ciao nonna", "nonna_watch_team_bot") is None


def test_status_lists_phones_quiet_ones_and_the_last_sound():
    devices = [{"room": "kitchen", "last_frame_ms": NOW_MS - 2_000, "battery_pct": 80, "paused": False},
               {"room": "bathroom", "last_frame_ms": NOW_MS - 300_000, "battery_pct": None, "paused": False}]
    last = {"room": "kitchen", "category": "cooking", "start": datetime(2026, 12, 1, 10, 50, tzinfo=timezone.utc)}
    text = bot.status_text({"uptime_s": 7_500}, devices, last, NOW_MS)
    assert "hub is on (running for 2 h 5 min)" in text
    assert "🟢 Kitchen: listening, battery 80%" in text
    assert "🟡 Bathroom: listening, no audio for 5 min" in text
    assert "No phone in: bedroom, living room, hallway" in text
    assert "Last sound: kitchen, cooking, at 11:50 (10 min ago)" in text       # Rome time


def test_status_when_the_hub_is_off():
    text = bot.status_text(None, None, None, NOW_MS, "The hub is not answering at http://localhost:8000.")
    assert text.startswith("❌ The hub is not answering")


class FakeHub:
    def __init__(self, fail=None):
        self.asked, self.fail = [], fail

    def health(self):
        return {"uptime_s": 60}

    def devices(self):
        return []

    def ask(self, room):
        if self.fail:
            raise bot.HubError(self.fail)
        self.asked.append(room)
        return {"ask_id": 1}


def test_ask_without_a_room_offers_buttons_and_with_a_room_asks():
    b = bot.Bot("-100", FakeHub(), username="nonna_watch_team_bot")
    text, buttons = b.reply_to("/ask")
    assert "Which room" in text
    assert [k["callback_data"] for row in buttons["inline_keyboard"] for k in row] == \
        ["ask:kitchen", "ask:bathroom", "ask:bedroom", "ask:living_room", "ask:hallway"]
    text, _ = b.reply_to("/ask kitchen")
    assert b.hub.asked == ["kitchen"] and "kitchen phone is asking" in text


def test_ask_explains_a_problem_in_plain_words():
    b = bot.Bot("-100", FakeHub(fail="No phone is listening there."), username="x")
    assert b.reply_to("/ask bedroom")[0] == "❌ No phone is listening there."
    assert "Which room?" in b.reply_to("/ask garage")[0]


def test_strangers_are_ignored(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "call", lambda method, **p: sent.append((method, p)))
    b = bot.Bot("-100", FakeHub(), username="x")
    b.handle({"message": {"chat": {"id": 12345}, "text": "/ask kitchen"}})        # a private chat, not the group
    assert sent == [] and b.hub.asked == []
    b.handle({"message": {"chat": {"id": -100}, "text": "/ask kitchen"}})
    assert b.hub.asked == ["kitchen"] and sent[0][0] == "sendMessage"


def test_a_room_button_asks_and_replaces_the_buttons(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "call", lambda method, **p: sent.append((method, p)))
    b = bot.Bot("-100", FakeHub(), username="x")
    b.handle({"callback_query": {"id": "q1", "data": "ask:bathroom",
                                 "message": {"message_id": 7, "chat": {"id": -100}}}})
    assert b.hub.asked == ["bathroom"]
    assert [m for m, _ in sent] == ["answerCallbackQuery", "editMessageText"]


# ------------------------------------------------------------------ the real HTTP calls, against a tiny fake hub

@pytest.fixture
def http_hub():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization")))
            self._send(200, {"uptime_s": 5} if self.path == "/health" else [])

        def do_POST(self):
            seen.append(("POST", self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") != "Bearer secret":
                return self._send(401, {"detail": "missing or wrong token"})
            if "bedroom" in self.path:
                return self._send(404, {"detail": "no listener is connected in bedroom"})
            self._send(200, {"ask_id": 3})

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_the_bot_calls_the_hub_with_its_token(http_hub):
    url, seen = http_hub
    hub = bot.Hub(url, "secret")
    assert hub.ask("kitchen") == {"ask_id": 3}
    assert seen[-1] == ("POST", "/ask?room=kitchen", "Bearer secret")
    with pytest.raises(bot.HubError, match="No phone is listening there"):
        hub.ask("bedroom")
    with pytest.raises(bot.HubError, match="wrong HUB_TOKEN"):
        bot.Hub(url, "wrong").ask("kitchen")


def test_a_hub_that_is_off_gives_a_plain_message():
    with pytest.raises(bot.HubError, match="not answering"):
        bot.Hub("http://127.0.0.1:9", "x").health()
