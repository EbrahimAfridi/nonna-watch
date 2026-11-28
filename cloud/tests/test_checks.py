"""checks.py and seed.py behaviour that needs no Firestore: a tiny stand-in plays the database."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nonna_cloud import checks, seed
from nonna_cloud.routine import Finding

ROME = ZoneInfo("Europe/Rome")


class AlreadyExists(Exception):
    """Same class name as google.api_core.exceptions.AlreadyExists, which is all report() looks at."""


class FakeDoc:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def get(self):
        data = self.store.get(self.path)
        return type("Snap", (), {"exists": data is not None, "to_dict": lambda _s: data})()

    def create(self, data):
        if self.path in self.store:
            raise AlreadyExists(self.path)
        self.store[self.path] = data

    def collection(self, name):
        return FakeCollection(self.store, f"{self.path}/{name}")


class FakeCollection:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def document(self, doc_id):
        return FakeDoc(self.store, f"{self.path}/{doc_id}")


class FakeDb(FakeCollection):
    def __init__(self, store):
        super().__init__(store, "")

    def collection(self, name):
        return FakeCollection(self.store, name)


def finding():
    return Finding(type="routine_missing", severity="notice", room="kitchen",
                   time=datetime(2026, 12, 1, 10, 30, tzinfo=ROME), message="No kitchen sounds yet today",
                   detail="", alert_id="routine_missing_kitchen_2026-12-01", voice_check=True)


def test_report_says_whether_it_wrote_the_alert():
    checker = checks.Checker(FakeDb({}), "maria")
    assert checker.report(finding())["type"] == "routine_missing"
    assert checker.report(finding()) is None              # someone already reported it


def test_a_missing_home_is_a_normal_error_not_an_exit():
    with pytest.raises(checks.MissingHome):
        checks.Checker(FakeDb({}), "nobody").run()
    assert not issubclass(checks.MissingHome, SystemExit)


def test_telegram_is_not_sent_twice_for_one_alert(monkeypatch):
    sent = []
    import nonna_cloud.telegram_setup as tg
    monkeypatch.setattr(tg, "send_message", lambda chat, text: sent.append(text))
    store = {"homes/maria": {"telegramChatId": "-100"}}
    checker = checks.Checker(FakeDb(store), "maria")
    monkeypatch.setattr(checker, "run", lambda now=None: [finding()])
    checks._once(checker, None, report=True, telegram=True)
    checks._once(checker, None, report=True, telegram=True)   # e.g. the hub reported it in between
    assert len(sent) == 1


def test_the_loop_survives_a_failed_run(monkeypatch):
    calls = []

    def flaky(checker, now, report, telegram):
        calls.append(1)
        if len(calls) == 1:
            from nonna_cloud.telegram_setup import TelegramError
            raise TelegramError("Telegram said: Bad Gateway")
        raise KeyboardInterrupt                            # the second run: stop the test here

    monkeypatch.setattr(checks, "_once", flaky)
    monkeypatch.setattr(checks.time, "sleep", lambda s: None)
    monkeypatch.setattr("nonna_cloud.db.connect", lambda **kw: FakeDb({}))
    with pytest.raises(KeyboardInterrupt):
        checks.main(["--loop"])
    assert len(calls) == 2


def test_telegram_errors_are_normal_errors():
    from nonna_cloud.telegram_setup import TelegramError
    assert issubclass(TelegramError, Exception) and not issubclass(TelegramError, SystemExit)


def test_seed_clear_only_counts_todays_alerts():
    midnight = datetime(2026, 12, 1, tzinfo=ROME)
    assert seed.is_today(midnight + timedelta(hours=10, minutes=30), midnight)
    assert not seed.is_today(midnight - timedelta(minutes=1), midnight)
    assert not seed.is_today(midnight + timedelta(days=1), midnight)
    assert not seed.is_today(None, midnight)


def test_madat_is_a_help_word_as_in_the_hub():
    from nonna_cloud.defaults import HELP_WORDS
    assert "madat" in HELP_WORDS["hi"] and "madat" in HELP_WORDS["ur"]
