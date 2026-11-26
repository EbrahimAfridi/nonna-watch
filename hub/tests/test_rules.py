from nonna_hub.categories import Detection
from nonna_hub.rules import Alert, RoomRules
from nonna_hub.speech import Utterance

HOP_MS = 500


def heard(*categories):
    return [Detection(category, 0.9, category) for category in categories]


def run_windows(rules, windows, start_ms=0):
    """Feed one list of detections per window, 0.5 s apart, and collect the alerts."""
    alerts = []
    for index, detections in enumerate(windows):
        alerts += rules.on_window(start_ms + index * HOP_MS, detections)
    return alerts


def said(*help_words, end_ms=5_000):
    return Utterance(start_ms=end_ms - 1_000, end_ms=end_ms, texts={"it": "..."}, help_words=list(help_words))


def test_a_help_word_alerts_at_once_with_the_word():
    assert RoomRules().on_speech(said("aiuto", end_ms=5_000)) == [Alert("help_word", 5_000, "aiuto")]


def test_speech_without_a_help_word_does_not_alert():
    assert RoomRules().on_speech(said()) == []


def test_the_same_kind_alerts_once_a_minute():
    rules = RoomRules()
    alerts = rules.on_speech(said("aiuto", end_ms=0))
    alerts += rules.on_speech(said("aiuto", end_ms=30_000))
    alerts += rules.on_speech(said("aiuto", end_ms=60_000))

    assert [alert.at_ms for alert in alerts] == [0, 60_000]


def test_a_long_scream_alerts_once():
    alerts = run_windows(RoomRules(), [heard("scream")] * 10)

    assert alerts == [Alert("scream", 0)]


def test_a_thud_then_ten_seconds_of_silence_alerts_at_the_time_of_the_thud():
    alerts = run_windows(RoomRules(), [heard("thud")] + [[]] * 20, start_ms=1_000)

    assert alerts == [Alert("thud", 1_000)]


def test_a_thud_does_not_alert_before_ten_seconds_have_passed():
    assert run_windows(RoomRules(), [heard("thud")] + [[]] * 19) == []


def test_footsteps_after_a_thud_cancel_it():
    alerts = run_windows(RoomRules(), [heard("thud")] + [[]] * 5 + [heard("footsteps")] + [[]] * 30)

    assert alerts == []


def test_a_tv_after_a_thud_does_not_count_as_movement():
    alerts = run_windows(RoomRules(), [heard("thud")] + [heard("tv_music")] * 20)

    assert [alert.kind for alert in alerts] == ["thud"]


def test_the_message_names_the_room_and_the_word():
    message = Alert("help_word", 0, "aiuto").message("living_room")

    assert message.startswith("Nonna Watch: Help word \"aiuto\" heard in the living room at ")
