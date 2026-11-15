import json
import os
from dataclasses import dataclass
from pathlib import Path

from wake.clock import Clock, iso
from wake.envelope import validate

GAP_REASONS = frozenset(
    {
        "ALLOWLIST_UNSET",
        "MISSING_IDENTITY",
        "UNTRUSTED_TEXT",
        "WRONG_OR_AMBIGUOUS",
        "WRONG_PACKAGE",
        "UNTRUSTED_ORIGIN",
        "DISABLED",
        "STOPPED",
        "RATE_CAP",
        "DEBOUNCED",
        "NO_NOTIFICATION",
        "RECONNECT_GAP",
        "MALFORMED_NOTIFY",
        "GAVE_UP",
        "REJECTED",
        "TRANSMISSION_OFF",
        "CORRUPT",
    }
)


def delay_seconds(attempts: int) -> float:
    if attempts < 1:
        return 1.0
    return min(30.0, float(2 ** (attempts - 1)))


@dataclass
class Item:
    event_id: str
    payload: dict
    state: str
    attempts: int
    next_attempt_at: float
    replaces_id: int
    source: str
    created_at: float
    updated_at: float
    acked_at: float | None
    reason: str
    draft: dict | None

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "payload": self.payload,
            "state": self.state,
            "attempts": self.attempts,
            "nextAttemptAt": self.next_attempt_at,
            "replacesId": self.replaces_id,
            "source": self.source,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "ackedAt": self.acked_at,
            "reason": self.reason,
            "draft": self.draft,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Item":
        payload = validate(raw["payload"])
        return cls(
            event_id=payload["eventId"],
            payload=payload,
            state=raw["state"],
            attempts=int(raw["attempts"]),
            next_attempt_at=float(raw["nextAttemptAt"]),
            replaces_id=int(raw["replacesId"]),
            source=payload["source"],
            created_at=float(raw["createdAt"]),
            updated_at=float(raw["updatedAt"]),
            acked_at=None if raw.get("ackedAt") is None else float(raw["ackedAt"]),
            reason=str(raw.get("reason") or ""),
            draft=raw.get("draft"),
        )


class Outbox:
    def __init__(
        self,
        path: Path,
        clock: Clock,
        *,
        debounce: float = 1.5,
        rate_limit: int = 8,
        rate_window: float = 60.0,
        max_attempts: int = 5,
    ) -> None:
        self.path = Path(path)
        self.clock = clock
        self.debounce = float(debounce)
        self.rate_limit = int(rate_limit)
        self.rate_window = float(rate_window)
        self.max_attempts = int(max_attempts)
        self.items = {}
        self.gaps = []
        self.rate_times = []
        self.replacement_index = {}
        self.zero_index = {}
        self.stopped = False
        self.blocked = False
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = {}
            for raw in data["items"]:
                item = Item.from_dict(raw)
                if item.state == "in_flight":
                    item.state = "retryable"
                    item.next_attempt_at = self.clock.now()
                    item.reason = "RESTART"
                items[item.event_id] = item
            self.items = items
            self.gaps = list(data.get("gaps") or [])
            self.rate_times = [float(value) for value in data.get("rateTimes") or []]
            self.replacement_index = {str(k): str(v) for k, v in (data.get("replacementIndex") or {}).items()}
            self.zero_index = {str(k): str(v) for k, v in (data.get("zeroIndex") or {}).items()}
            self.stopped = bool(data.get("stopped"))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.blocked = True
            self.items = {}

    def save(self) -> None:
        if self.blocked:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stopped": self.stopped,
            "gaps": self.gaps,
            "rateTimes": self.rate_times,
            "replacementIndex": self.replacement_index,
            "zeroIndex": self.zero_index,
            "items": [item.to_dict() for item in self.items.values()],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    def add_gap(self, reason: str) -> None:
        if self.blocked:
            return
        if reason not in GAP_REASONS:
            reason = "CORRUPT"
        self.gaps.append({"reason": reason, "at": iso(self.clock.now())})
        if len(self.gaps) > 200:
            self.gaps = self.gaps[-200:]
        self.save()

    def set_stopped(self, stopped: bool) -> None:
        if self.blocked:
            return
        self.stopped = bool(stopped)
        self.save()

    def plan(self, source: str, replaces_id: int, now: float):
        item = self._match(source, replaces_id)
        if item is None or item.state == "rejected":
            return "create", None
        if item.state in ("pending", "retryable", "in_flight"):
            return "update", item
        if item.state == "acked" and item.acked_at is not None and (now - item.acked_at) <= self.debounce:
            return "drop", item
        return "create", None

    def rate_ok(self, now: float) -> bool:
        self.rate_times = [stamp for stamp in self.rate_times if now - stamp < self.rate_window]
        return len(self.rate_times) < self.rate_limit

    def mark_rate(self, now: float) -> None:
        self.rate_times.append(now)

    def add(self, item: Item) -> None:
        self.items[item.event_id] = item
        if item.replaces_id == 0:
            self.zero_index[item.source] = item.event_id
        else:
            self.replacement_index[str(item.replaces_id)] = item.event_id
        self.save()

    def due(self) -> list:
        if self.blocked or self.stopped:
            return []
        now = self.clock.now()
        rows = [
            item
            for item in self.items.values()
            if item.state in ("pending", "retryable") and item.next_attempt_at <= now
        ]
        rows.sort(key=lambda item: (item.created_at, item.event_id))
        return rows

    def _match(self, source: str, replaces_id: int):
        if replaces_id == 0:
            event_id = self.zero_index.get(source)
        else:
            event_id = self.replacement_index.get(str(replaces_id))
        if not event_id:
            return None
        return self.items.get(event_id)
