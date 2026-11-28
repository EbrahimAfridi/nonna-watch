from datetime import UTC, datetime

from fakes import FakeFirestore

from nonna_hub import cloud_sync
from nonna_hub.cloud_sync import CloudSync
from nonna_hub.events import Event
from nonna_hub.rules import Alert

START_MS = 1_795_698_192_000


def written(db):
    return {path: data for path, data, _ in db.writes}


def test_an_event_is_one_document_as_the_schema_says():
    db = FakeFirestore()
    sync = CloudSync(db, "maria")

    sync.event("kitchen", Event("water", START_MS, START_MS + 8_500, 0.5873, "Water tap, faucet"))
    sync.flush(10)

    assert written(db) == {
        f"homes/maria/events/listener-kitchen_{START_MS}_water": {
            "room": "kitchen",
            "deviceId": "listener-kitchen",
            "sound": "Water tap, faucet",
            "category": "water",
            "confidence": 0.59,
            "start": datetime.fromtimestamp(START_MS / 1000, tz=UTC),
            "end": datetime.fromtimestamp((START_MS + 8_500) / 1000, tz=UTC),
            "source": "hub",
        }
    }


def test_an_alert_carries_its_message_voice_check_and_timings():
    db = FakeFirestore()
    sync = CloudSync(db, "maria")
    timings = {"capturedMs": START_MS, "hubReceivedMs": START_MS + 600, "aiDoneMs": START_MS + 2_800}

    sync.alert("kitchen", Alert("help_word", START_MS, "aiuto"), "pending", timings)
    sync.alert("bathroom", Alert("water_running", START_MS), None, None)
    sync.flush(10)
    help_alert = written(db)[f"homes/maria/alerts/help_word_kitchen_{START_MS}"]
    water = written(db)[f"homes/maria/alerts/water_running_bathroom_{START_MS}"]

    assert help_alert["message"].startswith('Nonna Watch: Help word "aiuto" heard in the kitchen')
    assert (help_alert["type"], help_alert["severity"], help_alert["status"], help_alert["source"]) == (
        "help_word",
        "alert",
        "sent",
        "hub",
    )
    assert help_alert["detail"] == {"word": "aiuto"}
    assert help_alert["voiceCheck"] == {"asked": True, "result": "pending"}
    assert help_alert["timings"] == timings
    assert (water["severity"], water["voiceCheck"], "timings" in water) == ("notice", None, False)


def test_writes_made_while_offline_go_through_later_in_order(monkeypatch):
    monkeypatch.setattr(cloud_sync, "RETRY_DELAYS_S", (0,))
    db = FakeFirestore(offline_writes=3)
    sync = CloudSync(db, "maria")

    sync.device("hub", {"kind": "hub"})
    sync.device("listener-kitchen", {"kind": "listener"})
    sync.flush(10)

    assert [path for path, _, _ in db.writes] == ["homes/maria/devices/hub", "homes/maria/devices/listener-kitchen"]
