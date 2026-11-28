"""C2 helper: find the family group's chat id, and check the bot can post there.

The bot token is a secret. Put it in cloud/secrets/telegram.env as one line:

    TELEGRAM_BOT_TOKEN=123456:ABC...

or set the environment variable TELEGRAM_BOT_TOKEN. Then, from cloud/:

    uv run python -m nonna_cloud.telegram_setup chat-id          # lists chats the bot has seen
    uv run python -m nonna_cloud.telegram_setup test <chat_id>   # posts a test message

Uses only the Python standard library (urllib), so it needs no extra install.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path(__file__).resolve().parents[2] / "secrets" / "telegram.env"


class TelegramError(RuntimeError):
    """No token, or Telegram refused the request. A normal error, so a loop can catch it and go on."""


def token() -> str:
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not t and SECRETS.exists():
        for line in SECRETS.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("TELEGRAM_BOT_TOKEN="):
                t = line.split("=", 1)[1].strip()
    if not t:
        raise TelegramError(f"No bot token. Put TELEGRAM_BOT_TOKEN=... in {SECRETS} (see cloud/README.md, C2).")
    return t


def call(method: str, _timeout: float = 15, **params) -> dict:
    url = f"https://api.telegram.org/bot{token()}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(url, data=data, timeout=_timeout) as r:
        body = json.load(r)
    if not body.get("ok"):
        raise TelegramError(f"Telegram said: {body}")
    return body["result"]


def list_chats() -> None:
    me = call("getMe")
    print(f"Bot: @{me['username']}")
    chats = {}
    for u in call("getUpdates"):
        msg = u.get("message") or u.get("my_chat_member") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if not chats:
        print("No chats yet. Add the bot to the family group, then send /start@" + me["username"]
              + " in the group and run this again.")
    for cid, name in chats.items():
        kind = "group" if cid < 0 else "private chat"
        print(f"  {cid}   {name}   ({kind})")
    print("Group ids are negative numbers. Use the family group's id as telegramChatId.")


def send_message(chat_id: str, text: str) -> None:
    """Post one message to a chat. Used by checks.py --telegram."""
    call("sendMessage", chat_id=chat_id, text=text)


def send_test(chat_id: str) -> None:
    call("sendMessage", chat_id=chat_id,
         text="✅ Nonna Watch test: the bot can post to this group. Real alerts will look like:\n"
              "🚨 Maria may need help. Heard 'aiuto' in the bathroom at 14:03.")
    print("Sent. Check the group on your phone.")


def main(argv: list[str]) -> None:
    try:
        if len(argv) >= 1 and argv[0] == "chat-id":
            list_chats()
        elif len(argv) == 2 and argv[0] == "test":
            send_test(argv[1])
        else:
            print(__doc__)
    except TelegramError as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main(sys.argv[1:])
