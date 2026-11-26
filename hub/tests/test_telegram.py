import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nonna_hub.telegram import Telegram, TelegramError


class FakeTelegramApi(BaseHTTPRequestHandler):
    """Answers like api.telegram.org, one prepared reply per request."""

    received: list = []
    replies: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        FakeTelegramApi.received.append((self.path, json.loads(body)))
        status, reply = FakeTelegramApi.replies.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def api_url():
    FakeTelegramApi.received, FakeTelegramApi.replies = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegramApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def telegram(api_url):
    return Telegram("123:secret", "-100777", api_url=api_url, retry_delays_s=(0, 0, 0))


def test_send_posts_the_text_to_the_family_chat(api_url):
    FakeTelegramApi.replies = [(200, {"ok": True, "result": {}})]

    telegram(api_url).send("Nonna Watch: test")

    assert FakeTelegramApi.received == [("/bot123:secret/sendMessage", {"chat_id": "-100777", "text": "Nonna Watch: test"})]


def test_send_retries_when_telegram_has_a_problem(api_url):
    FakeTelegramApi.replies = [(502, {"ok": False}), (200, {"ok": True, "result": {}})]

    telegram(api_url).send("Nonna Watch: test")

    assert len(FakeTelegramApi.received) == 2


def test_a_wrong_chat_is_reported_at_once_without_retrying(api_url):
    FakeTelegramApi.replies = [(400, {"ok": False, "description": "Bad Request: chat not found"})]

    with pytest.raises(TelegramError, match="chat not found"):
        telegram(api_url).send("Nonna Watch: test")
    assert len(FakeTelegramApi.received) == 1


def test_recent_chats_lists_the_groups_the_bot_was_added_to(api_url):
    added = {"my_chat_member": {"chat": {"id": -100777, "title": "Nonna family"}}}
    FakeTelegramApi.replies = [(200, {"ok": True, "result": [added]})]

    assert telegram(api_url).recent_chats() == [(-100777, "Nonna family")]
