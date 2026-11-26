"""Alerts to the family's Telegram group through the Bot API."""

import json
import time
import urllib.error
import urllib.request

API_URL = "https://api.telegram.org"


class TelegramError(Exception):
    """Telegram answered with an error, such as a wrong token or an unknown chat."""

    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class Telegram:
    def __init__(self, bot_token: str, chat_id: str, api_url: str = API_URL, retry_delays_s=(1, 2, 4)):
        self._base_url = f"{api_url}/bot{bot_token}"  # contains the token: never print or log it
        self._chat_id = chat_id
        self._retry_delays_s = retry_delays_s

    def send(self, text: str) -> None:
        """Post a message to the chat, retrying a few times if the network or Telegram is down."""
        message = {"chat_id": self._chat_id, "text": text}
        for delay_s in self._retry_delays_s:
            try:
                self._call("sendMessage", message)
                return
            except TelegramError as error:
                if not error.retryable:
                    raise
            except OSError:  # no network, DNS failure or timeout
                pass
            time.sleep(delay_s)
        self._call("sendMessage", message)

    def recent_chats(self) -> list[tuple[int, str]]:
        """Chats the bot has seen lately, to find TELEGRAM_CHAT_ID."""
        chats = {}
        for update in self._call("getUpdates", {}):
            for kind in ("message", "my_chat_member"):
                chat = update.get(kind, {}).get("chat")
                if chat:
                    chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name", "")
        return list(chats.items())

    def _call(self, method: str, payload: dict):
        request = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read())["result"]
        except urllib.error.HTTPError as error:
            # 429 means too many messages; 5xx is Telegram's side. Anything else will not fix itself.
            retryable = error.code == 429 or error.code >= 500
            raise TelegramError(f"Telegram said HTTP {error.code}: {describe(error)}", retryable) from None


def describe(error: urllib.error.HTTPError) -> str:
    try:
        return json.loads(error.read()).get("description", str(error.reason))
    except ValueError:
        return str(error.reason)
