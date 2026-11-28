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


def test_after_a_reassuring_answer_the_next_help_word_alerts_again():
    rules = RoomRules()
    rules.on_speech(said("aiuto", end_ms=0))
    rules.reassured("help_word")

    assert [alert.at_ms for alert in rules.on_speech(said("aiuto", end_ms=30_000))] == [30_000]


def test_a_scream_that_goes_on_stays_once_a_minute_even_after_a_reassuring_answer():
    rules = RoomRules()
    alerts = run_windows(rules, [heard("scream")] * 4)
    rules.reassured("scream")
    alerts += run_windows(rules, [heard("scream")] * 4, start_ms=2_000)

    assert alerts == [Alert("scream", 0)]


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


def water_for(rules, minutes, start_ms=0, every_ms=HOP_MS):
    """Water heard every `every_ms` for `minutes`; returns the alerts."""
    alerts = []
    for at_ms in range(start_ms, start_ms + minutes * 60_000 + 1, every_ms):
        alerts += rules.on_window(at_ms, heard("water"))
    return alerts


def test_water_running_for_twenty_minutes_gets_one_notice():
    alerts = water_for(RoomRules(), minutes=30, start_ms=1_000)

    assert alerts == [Alert("water_running", 1_000)]


def test_water_heard_only_now_and_then_still_counts_as_running():
    assert len(water_for(RoomRules(), minutes=21, every_ms=20_000)) == 1


def test_a_pause_in_the_water_starts_the_twenty_minutes_again():
    rules = RoomRules()
    alerts = water_for(rules, minutes=15) + water_for(rules, minutes=15, start_ms=16 * 60_000)

    assert alerts == []


def test_the_message_names_the_room_and_the_word():
    message = Alert("help_word", 0, "aiuto").message("living_room")

    assert message.startswith("Nonna Watch: Help word \"aiuto\" heard in the living room at ")
