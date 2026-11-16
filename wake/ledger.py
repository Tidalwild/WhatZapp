"""Durable event ledger for this package. Not a bot, and not coverage.

The example receiver stays in ``examples/routine`` and is not imported here.
This file is the host boundary: one worker, event ids separate from message
keys, and no path that marks an id covered because HTTP accepted the post.

``complete`` and ``fail`` exist for an explicit caller and for tests. The
page, list, and pane paths do not call them. A finished observation is still
not recorded by this package, so a posted id stays in flight and a later id
stays pending. # ponytail: one store-wide lock until that observation exists.
"""

import json
import os
import re
from pathlib import Path

from wake.envelope import new_event_id

NAME = "event-ledger.json"
FORMAT = "wake-ledger-1"
FOLLOWUP_LOCK = "followup"
MAX_FOLLOWUP_ROUNDS = 2
_EVENT = re.compile(r"^evt-[0-9a-f]{32}$")
_KEY = re.compile(r"^[A-Za-z0-9:._-]{1,80}$")
_OPEN = frozenset({"pending", "in_flight", "retryable"})
_GROUPS = ("pending", "scheduled", "inflight", "covered", "unresolved")


class Ledger:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.observed: dict[str, int] = {}
        self.pending: set[str] = set()
        self.scheduled: set[str] = set()
        self.inflight: set[str] = set()
        self.covered: set[str] = set()
        self.unresolved: set[str] = set()
        self.message_keys: set[str] = set()
        self.lock: str | None = None
        self.rounds = 0

    def state(self, event_id: str) -> str:
        if event_id in self.covered:
            return "covered"
        if event_id in self.inflight:
            return "inflight"
        if event_id in self.scheduled:
            return "scheduled"
        if event_id in self.unresolved:
            return "unresolved"
        if event_id in self.pending:
            return "pending"
        return "absent"

    def accept(self, event_id: str, observed_at: int) -> str:
        if not isinstance(event_id, str) or event_id == "" or event_id == FOLLOWUP_LOCK:
            return "UNUSABLE"
        if isinstance(observed_at, bool) or not isinstance(observed_at, int):
            return "UNUSABLE"
        if event_id in self.message_keys:
            return "UNUSABLE"
        if event_id in self.seen:
            return "DUPLICATE_EVENT"
        self.seen.add(event_id)
        self.observed[event_id] = observed_at
        if self.lock is not None:
            self.pending.add(event_id)
            return "HELD"
        if self.scheduled:
            self.scheduled.add(event_id)
            return "COALESCED"
        self.lock = event_id
        self.inflight.add(event_id)
        return "INSPECT"

    def note_message(self, key: str) -> str:
        if not _usable_key(key) or key in self.seen or _EVENT.fullmatch(key):
            return "UNUSABLE"
        if key in self.message_keys:
            return "DUPLICATE"
        self.message_keys.add(key)
        return "ADDED"

    def message_known(self, key: str) -> bool:
        return isinstance(key, str) and key in self.message_keys

    def complete(
        self,
        sampled_at: int,
        *,
        new_turn: bool = False,
        covered_event_ids: tuple[str, ...] | list[str] = (),
        handled_message_keys: tuple[str, ...] | list[str] = (),
    ) -> str:
        if self.lock is None:
            return "NO_LOCK"
        if isinstance(sampled_at, bool) or not isinstance(sampled_at, int):
            return "UNUSABLE"
        for key in handled_message_keys:
            if isinstance(key, str):
                self.note_message(key)
        self.lock = None
        listed = {event_id for event_id in covered_event_ids if isinstance(event_id, str)}
        for event_id in listed:
            if event_id in self.seen:
                self._cover(event_id)
        self._release_inflight()
        # new_turn is the caller's claim. It does not cover an id, and a
        # sample clock does not either. Only listed ids move to covered.
        del new_turn
        return self._schedule_pending()

    def begin_followup(self) -> str:
        if self.lock is not None:
            return "BUSY"
        if not self.scheduled:
            return "NO_FOLLOWUP"
        self.inflight.update(self.scheduled)
        self.scheduled.clear()
        self.lock = FOLLOWUP_LOCK
        return "INSPECT"

    def fail(self, reason: str) -> str:
        if reason not in {"failed", "timeout"}:
            return "UNUSABLE"
        if self.lock is None:
            return "NO_LOCK"
        self.lock = None
        self._release_inflight()
        return "PENDING"

    def schedule_pending(self) -> str:
        if self.lock is not None:
            return "BUSY"
        return self._schedule_pending()

    def _cover(self, event_id: str) -> None:
        self.pending.discard(event_id)
        self.scheduled.discard(event_id)
        self.inflight.discard(event_id)
        self.unresolved.discard(event_id)
        self.covered.add(event_id)

    def _release_inflight(self) -> None:
        for event_id in list(self.inflight):
            self.inflight.discard(event_id)
            if event_id not in self.covered:
                self.pending.add(event_id)

    def _schedule_pending(self) -> str:
        if not self.pending:
            if self.scheduled:
                return "ALREADY_SCHEDULED"
            return "SETTLED"
        if self.rounds >= MAX_FOLLOWUP_ROUNDS:
            self.unresolved.update(self.pending)
            self.pending.clear()
            return "FOLLOWUP_CAP"
        if not self.scheduled:
            self.rounds += 1
        self.scheduled.update(self.pending)
        self.pending.clear()
        return "FOLLOWUP"

    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "seen": sorted(self.seen),
            "observed": {key: self.observed[key] for key in sorted(self.observed)},
            "pending": sorted(self.pending),
            "scheduled": sorted(self.scheduled),
            "inflight": sorted(self.inflight),
            "covered": sorted(self.covered),
            "unresolved": sorted(self.unresolved),
            "messageKeys": sorted(self.message_keys),
            "lock": self.lock,
            "rounds": self.rounds,
        }


def outbox_outstanding(pipeline) -> bool:
    outbox = getattr(pipeline, "outbox", None)
    items = getattr(outbox, "items", None)
    if not isinstance(items, dict):
        return False
    return any(getattr(item, "state", "") in _OPEN for item in items.values())


def worker_locked(directory: Path) -> bool | None:
    path = Path(directory) / NAME
    if not os.path.lexists(path):
        return False
    ledger = load(directory)
    if ledger is None:
        return None
    return ledger.lock is not None or bool(ledger.inflight)


def note_posted(directory: Path, event_id: str, message_key: str, observed_at) -> str:
    ledger = load(directory)
    if ledger is None:
        return "UNREADABLE"
    seconds = _seconds(observed_at)
    if seconds is None or not isinstance(event_id, str):
        return "UNUSABLE"
    outcome = ledger.accept(event_id, seconds)
    if outcome == "UNUSABLE":
        return outcome
    status = ledger.note_message(message_key)
    if status == "UNUSABLE":
        return status
    if not save(directory, ledger):
        return "UNREADABLE"
    return outcome


def note_held(directory: Path, message_key: str, observed_at) -> tuple[str, str]:
    ledger = load(directory)
    if ledger is None:
        return "UNREADABLE", ""
    seconds = _seconds(observed_at)
    if seconds is None:
        return "UNUSABLE", ""
    if ledger.message_known(message_key):
        return "DUPLICATE", ""
    if ledger.lock is None and not ledger.scheduled and not ledger.inflight:
        return "NO_LOCK", ""
    event_id = new_event_id()
    outcome = ledger.accept(event_id, seconds)
    if outcome not in {"HELD", "COALESCED"}:
        return outcome, ""
    if ledger.note_message(message_key) != "ADDED":
        return "UNUSABLE", ""
    if not save(directory, ledger):
        return "UNREADABLE", ""
    return outcome, event_id


def remember_message(directory: Path, message_key: str) -> str:
    ledger = load(directory)
    if ledger is None:
        return "UNREADABLE"
    status = ledger.note_message(message_key)
    if status != "ADDED":
        return status
    if not save(directory, ledger):
        return "UNREADABLE"
    return "ADDED"


def summary(directory: Path) -> str:
    path = Path(directory) / NAME
    if not os.path.lexists(path):
        return "none"
    ledger = load(directory)
    if ledger is None:
        return "unreadable"
    return (
        f"pending={len(ledger.pending)} inflight={len(ledger.inflight)} "
        f"covered={len(ledger.covered)} unresolved={len(ledger.unresolved)}"
    )


def load(directory: Path) -> Ledger | None:
    path = Path(directory) / NAME
    if not os.path.lexists(path):
        return Ledger()
    if os.path.islink(path) or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return _from_dict(data)


def save(directory: Path, ledger: Ledger) -> bool:
    directory = Path(directory)
    path = directory / NAME
    if os.path.lexists(path) and (os.path.islink(path) or not path.is_file()):
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    temporary = path.with_suffix(".json.tmp")
    if os.path.lexists(temporary) and os.path.islink(temporary):
        return False
    try:
        temporary.write_text(json.dumps(ledger.to_dict(), sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def _from_dict(data) -> Ledger | None:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None
    ledger = Ledger()
    seen = _strings(data.get("seen"))
    if seen is None:
        return None
    ledger.seen = seen
    observed = data.get("observed")
    if not isinstance(observed, dict) or set(observed) != ledger.seen:
        return None
    for event_id, stamp in observed.items():
        if isinstance(stamp, bool) or not isinstance(stamp, int):
            return None
        ledger.observed[event_id] = stamp
    groups = {}
    for name in _GROUPS:
        values = _strings(data.get(name))
        if values is None or not values <= ledger.seen:
            return None
        groups[name] = values
    if len(set().union(*groups.values())) != sum(len(values) for values in groups.values()):
        return None
    ledger.pending = groups["pending"]
    ledger.scheduled = groups["scheduled"]
    ledger.inflight = groups["inflight"]
    ledger.covered = groups["covered"]
    ledger.unresolved = groups["unresolved"]
    keys = _strings(data.get("messageKeys"))
    if keys is None or keys & ledger.seen:
        return None
    if any(not _usable_key(key) or _EVENT.fullmatch(key) for key in keys):
        return None
    ledger.message_keys = keys
    lock = data.get("lock")
    if lock is not None and (not isinstance(lock, str) or (lock != FOLLOWUP_LOCK and lock not in ledger.seen)):
        return None
    rounds = data.get("rounds")
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 0 <= rounds <= MAX_FOLLOWUP_ROUNDS:
        return None
    ledger.lock = lock
    ledger.rounds = rounds
    return ledger


def _strings(value) -> set[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) or item == "" for item in value):
        return None
    if len(set(value)) != len(value):
        return None
    return set(value)


def _usable_key(key: str) -> bool:
    return isinstance(key, str) and _KEY.fullmatch(key) is not None and _EVENT.fullmatch(key) is None


def _seconds(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    whole = int(value)
    if whole < 0:
        return None
    return whole
