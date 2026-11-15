import time
from datetime import datetime, timezone


def iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
    def now(self) -> float:
        return time.time()


class FakeClock:
    def __init__(self, timestamp: float = 1_700_000_000.0) -> None:
        self.timestamp = float(timestamp)

    def now(self) -> float:
        return self.timestamp

    def advance(self, seconds: float) -> None:
        self.timestamp += float(seconds)
