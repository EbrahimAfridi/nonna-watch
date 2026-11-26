"""Merges one room's per-window detections into events with a start and an end."""

from dataclasses import dataclass

from nonna_hub.categories import Detection

# Detections of one category with at most this much nothing between them belong to one event.
MAX_PAUSE_MS = 1_000


@dataclass
class Event:
    category: str
    start_ms: int
    end_ms: int
    peak: float
    label: str  # the YAMNet label at the peak

    def summary(self) -> str:
        """Category, peak score and label, such as "water        0.59  Water tap, faucet"."""
        return f"{self.category:<12} {self.peak:.2f}  {self.label}"


class EventMerger:
    def __init__(self, window_ms: int):
        self.window_ms = window_ms
        # Events still going on, by category. Readable so the alert rules (E5) need not wait for the end.
        self.open: dict[str, Event] = {}

    def push(self, window_start_ms: int, detections: list[Detection]) -> list[Event]:
        """Add one window's detections; return the events that a long enough pause has ended."""
        ended = [event for event in self.open.values() if window_start_ms - event.end_ms > MAX_PAUSE_MS]
        for event in ended:
            del self.open[event.category]

        window_end_ms = window_start_ms + self.window_ms
        for detection in detections:
            event = self.open.get(detection.category)
            if event is None:
                self.open[detection.category] = Event(
                    detection.category, window_start_ms, window_end_ms, detection.score, detection.label
                )
                continue
            event.end_ms = window_end_ms
            if detection.score > event.peak:
                event.peak = detection.score
                event.label = detection.label
        return ended

    def close_all(self) -> list[Event]:
        """End every open event, for when the stream stops."""
        ended = list(self.open.values())
        self.open.clear()
        return ended
