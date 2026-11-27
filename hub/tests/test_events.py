from nonna_hub.categories import Detection
from nonna_hub.events import Event, EventMerger

WINDOW_MS = 975
HOP_MS = 500


def water(score=0.5, label="Water tap, faucet"):
    return Detection("water", score, label)


def speech():
    return Detection("speech", 0.9, "Speech")


def merge(windows):
    """Feed one list of detections per window, 0.5 s apart, and collect every event."""
    merger = EventMerger(WINDOW_MS)
    events = []
    for index, detections in enumerate(windows):
        events += merger.push(index * HOP_MS, detections)
    return events + merger.close_all()


def test_consecutive_windows_become_one_event_with_the_label_at_its_peak():
    events = merge([[water(0.4)], [water(0.75, "Sink (filling or washing)")], [water(0.5)]])

    assert events == [Event("water", 0, 1_000 + WINDOW_MS, 0.75, "Sink (filling or washing)")]


def test_a_short_pause_does_not_split_an_event():
    events = merge([[water()], [], [], [water()]])  # 525 ms of nothing between the two windows

    assert [(event.start_ms, event.end_ms) for event in events] == [(0, 1_500 + WINDOW_MS)]


def test_a_long_pause_ends_an_event_as_soon_as_it_has_passed():
    merger = EventMerger(WINDOW_MS)
    merger.push(0, [water()])

    assert merger.push(1_500, []) == []
    assert [(event.start_ms, event.end_ms) for event in merger.push(2_000, [])] == [(0, WINDOW_MS)]


def test_sounds_at_the_same_time_become_separate_events():
    events = merge([[water(), speech()], [water()], [water()]])

    assert sorted((event.category, event.start_ms, event.end_ms) for event in events) == [
        ("speech", 0, WINDOW_MS),
        ("water", 0, 1_000 + WINDOW_MS),
    ]


def test_windows_with_nothing_detected_give_no_events():
    assert merge([[], [], []]) == []
