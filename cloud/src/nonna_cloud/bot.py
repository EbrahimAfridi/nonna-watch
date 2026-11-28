"""The family's Telegram commands: /status, /ask, /help (extra, not in C1-C10).

Runs next to the hub, on the same laptop, as a third window:

    cd cloud
    uv run --env-file ../hub/.env python -m nonna_cloud.bot

It reads everything from hub/.env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HUB_TOKEN (and HUB_URL if the
hub is not on this laptop, default http://localhost:8000). At start it also sets the "/" menu in Telegram,
so nothing has to be typed into BotFather.

    /status   is the hub on, which phones are connected, the last sound (from Firestore)
    /ask      buttons with the rooms; tapping one makes that phone ask "Stai bene?" (the hub's POST /ask)
    /ask kitchen   the same, straight away
    /help     what the bot can do

Only the family group (TELEGRAM_CHAT_ID) is answered: anyone can find a bot and write to it, and /ask
makes a phone speak in Maria's home.

It uses Telegram "long polling" (getUpdates): the bot asks Telegram "anything new?" and waits up to 30 s
for an answer. Only ONE program may do that per bot, so stop this before running telegram_setup chat-id.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nonna_cloud.defaults import ROOMS
from nonna_cloud.telegram_setup import TelegramError, call

ROME = ZoneInfo("Europe/Rome")
HUB_ENV = Path(__file__).resolve().parents[3] / "hub" / ".env"

COMMANDS = [
    {"command": "status", "description": "Is everything working? Phones, hub, last sound"},
    {"command": "ask", "description": 'Ask Maria "Are you okay?" in a room, e.g. /ask kitchen'},
    {"command": "help", "description": "What this bot can do"},
]
HELP = (
    "I watch over Maria's home.\n"
    "/status — is the hub on, which phones listen, the last sound\n"
    "/ask — pick a room, and its phone asks Maria \"Stai bene?\"\n"
    "Alerts arrive here by themselves; you don't need to ask."
)


def room_name(room: str) -> str:
    return room.replace("_", " ")


# -------------------------------------------------------------------- talking to the hub

class HubError(Exception):
    """The hub said no, or could not be reached. The message is meant for the family."""


class Hub:
    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    def _request(self, method: str, path: str, auth: bool = True):
        req = urllib.request.Request(self.url + path, method=method,
                                     headers={"Authorization": f"Bearer {self.token}"} if auth else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.load(e).get("detail", "")
            except (ValueError, AttributeError):
                pass
            raise HubError({401: "The bot has the wrong HUB_TOKEN.",
                            404: f"No phone is listening there ({detail}).",
                            409: "A question is already being asked in that room. Wait a moment.",
                            503: "That phone just disconnected."}.get(e.code, f"The hub said {e.code}: {detail}"))
        except (urllib.error.URLError, TimeoutError, OSError):
            raise HubError(f"The hub is not answering at {self.url}. Is it running?")

    def health(self) -> dict:
        return self._request("GET", "/health", auth=False)

    def devices(self) -> list[dict]:
        return self._request("GET", "/devices")

    def ask(self, room: str) -> dict:
        return self._request("POST", "/ask?" + urllib.parse.urlencode({"room": room}))


# -------------------------------------------------------------------- what the bot says

def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min ago"


def status_text(health: dict | None, devices: list[dict] | None, last_event: dict | None,
                now_ms: int, hub_problem: str = "") -> str:
    lines = []
    if health is None:
        lines.append(f"❌ {hub_problem or 'The hub is not answering.'}")
    else:
        up = int(health.get("uptime_s", 0))
        lines.append(f"✅ The hub is on (running for {up // 3600} h {up % 3600 // 60} min).")
    if devices is not None:
        by_room = {d["room"]: d for d in devices}
        for room in ROOMS:
            d = by_room.get(room)
            if d is None:
                continue
            quiet_s = (now_ms - d["last_frame_ms"]) / 1000 if d.get("last_frame_ms") else None
            mark = "🟢" if quiet_s is not None and quiet_s < 60 else "🟡"
            bits = [f"{mark} {room_name(room).capitalize()}: listening"]
            if d.get("paused"):
                bits = [f"⏸ {room_name(room).capitalize()}: paused"]
            if quiet_s is not None and quiet_s >= 60:
                bits.append(f"no audio for {ago(quiet_s).removesuffix(' ago')}")
            if d.get("battery_pct") is not None:
                bits.append(f"battery {d['battery_pct']}%")
            lines.append(", ".join(bits))
        missing = [room_name(r) for r in ROOMS if r not in by_room]
        if not by_room:
            lines.append("⚪ No phone is connected.")
        elif missing:
            lines.append("⚪ No phone in: " + ", ".join(missing))
    if last_event:
        start = last_event["start"].astimezone(ROME)
        sound = last_event.get("category") or last_event.get("sound", "a sound")
        lines.append(f"🔊 Last sound: {room_name(last_event['room'])}, {sound.replace('_', ' ')}, "
                     f"at {start:%H:%M} ({ago(now_ms / 1000 - start.timestamp())})")
    return "\n".join(lines)


def room_buttons() -> dict:
    rows = [[{"text": room_name(r).capitalize(), "callback_data": f"ask:{r}"} for r in ROOMS[i:i + 2]]
            for i in range(0, len(ROOMS), 2)]
    return {"inline_keyboard": rows}


def parse_command(text: str, bot_username: str) -> tuple[str, str] | None:
    """'/ask@nonna_watch_team_bot kitchen' -> ('ask', 'kitchen'). None if it's not a command for us."""
    if not text.startswith("/"):
        return None
    word, _, rest = text[1:].partition(" ")
    name, _, to = word.partition("@")
    if to and to.lower() != bot_username.lower():
        return None                                   # meant for another bot in the group
    return name.lower(), rest.strip().lower().replace(" ", "_")


# -------------------------------------------------------------------- the bot

class Bot:
    def __init__(self, chat_id: str, hub: Hub, db=None, home_id: str = "maria", username: str = ""):
        self.chat_id, self.hub, self.db, self.home_id, self.username = str(chat_id), hub, db, home_id, username

    def last_event(self) -> dict | None:
        if self.db is None:
            return None
        try:
            from google.cloud import firestore
            q = (self.db.collection("homes").document(self.home_id).collection("events")
                 .order_by("start", direction=firestore.Query.DESCENDING).limit(1))
            docs = list(q.stream())
            return docs[0].to_dict() if docs else None
        except Exception:                             # Firestore is a nice-to-have here
            return None

    def status(self) -> str:
        health = devices = None
        problem = ""
        try:
            health = self.hub.health()
            devices = self.hub.devices()
        except HubError as e:
            problem = str(e)
        return status_text(health, devices, self.last_event(), int(time.time() * 1000), problem)

    def ask(self, room: str) -> str:
        if room not in ROOMS:
            return "Which room? " + ", ".join(room_name(r) for r in ROOMS)
        try:
            self.hub.ask(room)
        except HubError as e:
            return f"❌ {e}"
        return f"🔔 The {room_name(room)} phone is asking Maria \"Stai bene?\" now."

    def reply_to(self, text: str) -> tuple[str, dict | None] | None:
        """(text, buttons) for a message from the family group, or None to stay quiet."""
        cmd = parse_command(text, self.username)
        if cmd is None:
            return None
        name, arg = cmd
        if name == "status":
            return self.status(), None
        if name == "ask":
            return (self.ask(arg), None) if arg else ("Which room should I ask in?", room_buttons())
        if name in ("help", "start"):
            return HELP, None
        return None

    def handle(self, update: dict) -> None:
        if q := update.get("callback_query"):         # a room button was tapped
            msg = q.get("message", {})
            if str(msg.get("chat", {}).get("id")) != self.chat_id or not q.get("data", "").startswith("ask:"):
                call("answerCallbackQuery", callback_query_id=q["id"])
                return
            answer = self.ask(q["data"].split(":", 1)[1])
            call("answerCallbackQuery", callback_query_id=q["id"])
            call("editMessageText", chat_id=self.chat_id, message_id=msg["message_id"], text=answer)
            return
        msg = update.get("message")
        if not msg or "text" not in msg:
            return
        if str(msg["chat"]["id"]) != self.chat_id:    # only the family group may use the bot
            return
        reply = self.reply_to(msg["text"])
        if reply:
            text, buttons = reply
            params = {"chat_id": self.chat_id, "text": text}
            if buttons:
                params["reply_markup"] = json.dumps(buttons)
            call("sendMessage", **params)

    def run(self) -> None:
        offset = None
        print(f"Answering /status, /ask, /help in chat {self.chat_id}. Ctrl+C stops.")
        while True:
            try:
                params = {"timeout": 30, "allowed_updates": json.dumps(["message", "callback_query"])}
                if offset is not None:
                    params["offset"] = offset
                for update in call("getUpdates", _timeout=40, **params):
                    offset = update["update_id"] + 1
                    try:
                        self.handle(update)
                    except Exception as e:            # one bad message must not stop the bot
                        print(f"Could not answer update {update['update_id']}: {e}")
            except (TelegramError, OSError) as e:
                print(f"Telegram problem, trying again in 5 s: {e}")
                time.sleep(5)


def read_env_file(path: Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values[key.strip()] = value.strip()
    return values


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Answer /status and /ask in the family's Telegram group.")
    ap.add_argument("--home", default=os.environ.get("HOME_ID", "maria"))
    ap.add_argument("--hub-url", default=os.environ.get("HUB_URL", "http://localhost:8000"))
    ap.add_argument("--no-firestore", action="store_true", help="skip the 'last sound' line")
    args = ap.parse_args(argv)

    file_env = read_env_file(HUB_ENV)                 # works even without --env-file
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "HUB_TOKEN"):
        if not os.environ.get(key) and file_env.get(key):
            os.environ[key] = file_env[key]
    chat_id, hub_token = os.environ.get("TELEGRAM_CHAT_ID", ""), os.environ.get("HUB_TOKEN", "")
    if not chat_id or not hub_token:
        raise SystemExit(f"Need TELEGRAM_CHAT_ID and HUB_TOKEN, e.g. in {HUB_ENV}.")

    db = None
    if not args.no_firestore:
        try:
            from nonna_cloud.db import connect
            db = connect()
        except (Exception, SystemExit) as e:
            print(f"No Firestore ({e}); /status will leave out the last sound.")

    try:
        me = call("getMe")
        call("setMyCommands", commands=json.dumps(COMMANDS))
    except TelegramError as e:
        raise SystemExit(str(e))
    print(f"Bot @{me['username']}: the / menu is set.")
    try:
        Bot(chat_id, Hub(args.hub_url, hub_token), db, args.home, me["username"]).run()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
