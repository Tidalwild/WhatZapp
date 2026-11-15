"""Reference wake receiver. Not installed into a bot.

Copy this rule into a routine you run. The extension, the native host, and a
Grok Bot install do not import this module. It does not read a chat, does not
call a webhook, and does not send.

A wake is an event id plus the time it was observed. That pair is not a
message. One worker may inspect at a time. Another unique id accepted during
that lock stays pending. A scheduled followup blocks a second schedule for
those ids. Scheduled and in-flight ids are not covered and are not inspected.
An id becomes covered only when a finished observation lists it. A failed or
timed-out observation puts the in-flight ids back to pending. When the
followup round cap is reached, leftover ids stay unresolved. They are kept,
and they are not covered.
"""

from datetime import datetime, timezone

from wake.envelope import SCHEMA_V3, EnvelopeError, validate

FOLLOWUP_LOCK = "followup"
MAX_FOLLOWUP_ROUNDS = 2


class ReferenceReceiver:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.observed: dict[str, int] = {}
        self.pending: set[str] = set()
        self.scheduled: set[str] = set()
        self.inflight: set[str] = set()
        self.covered: set[str] = set()
        self.unresolved: set[str] = set()
        self.handled_messages: set[str] = set()
        self.lock: str | None = None
        self.rounds = 0
        self.sends = 0
        self.incoming = False
        self.last_sampled_at: int | None = None

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

    def accept_v3(self, payload: dict) -> str:
        try:
            checked = validate(payload)
        except EnvelopeError:
            return "UNUSABLE"
        if checked.get("field") != SCHEMA_V3:
            return "IGNORED_SCHEMA"
        return self.accept(checked["eventId"], _iso_to_unix(checked["observedAt"]))

    def complete(
        self,
        sampled_at: int,
        *,
        new_turn: bool,
        covered_event_ids: tuple[str, ...] | list[str] = (),
        handled_message_keys: tuple[str, ...] | list[str] = (),
    ) -> str:
        if self.lock is None:
            return "NO_LOCK"
        if isinstance(sampled_at, bool) or not isinstance(sampled_at, int):
            return "UNUSABLE"
        self.last_sampled_at = sampled_at
        self.incoming = bool(new_turn)
        for key in handled_message_keys:
            if isinstance(key, str) and key:
                self.handled_messages.add(key)
        self.lock = None
        for event_id in covered_event_ids:
            if isinstance(event_id, str) and event_id in self.seen:
                self._cover(event_id)
        self._release_inflight_to_pending()
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
        self._release_inflight_to_pending()
        return "PENDING"

    def schedule_pending(self) -> str:
        if self.lock is not None:
            return "BUSY"
        return self._schedule_pending()

    def request_send(self) -> str:
        return "NOT_SENT"

    def message_handled(self, key: str) -> bool:
        return key in self.handled_messages

    def _cover(self, event_id: str) -> None:
        self.pending.discard(event_id)
        self.scheduled.discard(event_id)
        self.inflight.discard(event_id)
        self.unresolved.discard(event_id)
        self.covered.add(event_id)

    def _release_inflight_to_pending(self) -> None:
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


def _iso_to_unix(value: str) -> int:
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())
