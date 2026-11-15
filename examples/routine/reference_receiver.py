"""Reference wake receiver. Not installed into a bot.

Copy this rule into a routine you run. The extension, the native host, and a
Grok Bot install do not import this module. It does not read a chat, does not
call a webhook, and does not send.

A wake is an event id plus the time it was observed. That pair is not a
message. One worker may inspect at a time. A second unique event accepted
during that lock stays pending. When the sample finishes, an event is covered
only if the sample names its id. A followup already queued for that id is
also proof. The sample clock is not proof, including when the event was
observed earlier than the sample was read. Pending ids that lack that proof
share one followup. After that followup finishes, those same ids are not
queued again.
"""

from datetime import datetime, timezone

from wake.envelope import SCHEMA_V3, EnvelopeError, validate

FOLLOWUP_LOCK = "followup"
MAX_FOLLOWUP_ROUNDS = 2


class ReferenceReceiver:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.observed: dict[str, int] = {}
        self.covered: set[str] = set()
        self.inspected: set[str] = set()
        self.handled_messages: set[str] = set()
        self.queued: set[str] = set()
        self.followup_done: set[str] = set()
        self.capped: set[str] = set()
        self.pending: list[str] = []
        self.lock: str | None = None
        self.rounds = 0
        self.sends = 0
        self.incoming = False
        self.last_sampled_at: int | None = None

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
            self.pending.append(event_id)
            return "HELD"
        if self.queued:
            self.queued.add(event_id)
            return "COALESCED"
        self.lock = event_id
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
        holder = self.lock
        self.last_sampled_at = sampled_at
        self.incoming = bool(new_turn)
        for key in handled_message_keys:
            if isinstance(key, str) and key:
                self.handled_messages.add(key)
        named = {item for item in covered_event_ids if isinstance(item, str) and item}
        self.covered |= named
        self.lock = None
        if holder == FOLLOWUP_LOCK:
            self.followup_done |= set(self.queued)
            self.queued.clear()
        else:
            self.inspected.add(holder)
        need = [
            event_id
            for event_id in self.pending
            if event_id not in self.covered
            and event_id not in self.followup_done
            and event_id not in self.queued
            and event_id not in self.capped
        ]
        self.pending.clear()
        if not need:
            return "SETTLED"
        if self.rounds >= MAX_FOLLOWUP_ROUNDS:
            self.capped.update(need)
            return "FOLLOWUP_CAP"
        self.rounds += 1
        self.queued.update(need)
        return "FOLLOWUP"

    def begin_followup(self) -> str:
        if self.lock is not None:
            return "BUSY"
        if not self.queued:
            return "NO_FOLLOWUP"
        self.lock = FOLLOWUP_LOCK
        return "INSPECT"

    def request_send(self) -> str:
        return "NOT_SENT"

    def message_handled(self, key: str) -> bool:
        return key in self.handled_messages


def _iso_to_unix(value: str) -> int:
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())
