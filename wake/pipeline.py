from wake.android import from_listener
from wake.clock import iso
from wake.evidence import stored_reason
from wake.envelope import CHAT_REF, build, build_v2, build_v3, new_event_id, validate
from wake.log import Log
from wake.model import Observation, ParseFailure
from wake.outbox import Item, Outbox, delay_seconds
from wake.policy import classify

SOURCE_BY_ORIGIN = {
    "session-bus": "linux-session-notify",
    "android-listener": "android-listener",
    "web-page": "web-page-change",
    "unread-hint": "unread-indicator-hint",
}


class HandleResult:
    def __init__(self, disposition: str, reason: str, event_id: str | None = None) -> None:
        self.disposition = disposition
        self.reason = reason
        self.event_id = event_id


class Pipeline:
    def __init__(self, *, outbox: Outbox, allowlist: str, enabled: bool, client, log: Log) -> None:
        self.outbox = outbox
        self.allowlist = allowlist
        self.enabled = bool(enabled)
        self.client = client
        self.log = log

    def handle(self, obs) -> HandleResult:
        if self.outbox.blocked:
            self.log.event("ignored", reason="CORRUPT", disposition="ignored")
            return HandleResult("ignored", "CORRUPT")
        if self.outbox.stopped:
            self.outbox.add_gap("STOPPED")
            self.log.event("ignored", reason="STOPPED", disposition="ignored")
            return HandleResult("ignored", "STOPPED")
        if not self.enabled:
            self.outbox.add_gap("DISABLED")
            self.log.event("ignored", reason="DISABLED", disposition="ignored")
            return HandleResult("ignored", "DISABLED")
        if isinstance(obs, ParseFailure):
            self.outbox.add_gap("MALFORMED_NOTIFY")
            self.log.event("ignored", reason="MALFORMED_NOTIFY", disposition="ignored")
            return HandleResult("ignored", "MALFORMED_NOTIFY")
        if not isinstance(obs, Observation) or obs.origin not in SOURCE_BY_ORIGIN:
            self.outbox.add_gap("UNTRUSTED_ORIGIN")
            self.log.event("ignored", reason="UNTRUSTED_ORIGIN", disposition="ignored")
            return HandleResult("ignored", "UNTRUSTED_ORIGIN")
        decision = classify(obs.summary, self.allowlist)
        if not decision.ok:
            self.outbox.add_gap(decision.reason)
            self.log.event("ignored", reason=decision.reason, disposition="ignored")
            return HandleResult("ignored", decision.reason)
        now = self.outbox.clock.now()
        source = SOURCE_BY_ORIGIN[obs.origin]
        action, existing = self.outbox.plan(source, obs.replaces_id, now)
        if action == "update" and existing is not None:
            existing.payload["observedAt"] = iso(now)
            validate(existing.payload)
            existing.updated_at = now
            self.outbox.save()
            self.log.event("replaced", eventId=existing.event_id, source=source, disposition="replaced")
            return HandleResult("replaced", "REPLACED", existing.event_id)
        if action == "drop":
            self.outbox.add_gap("DEBOUNCED")
            self.log.event("ignored", reason="DEBOUNCED", disposition="ignored")
            return HandleResult("ignored", "DEBOUNCED")
        if not self.outbox.rate_ok(now):
            self.outbox.add_gap("RATE_CAP")
            self.log.event("ignored", reason="RATE_CAP", disposition="ignored")
            return HandleResult("ignored", "RATE_CAP")
        event_id = new_event_id()
        payload = build(
            event_id=event_id,
            source=source,
            observed_at=iso(now),
            conversation_scope=decision.scope,
        )
        item = Item(
            event_id=event_id,
            payload=payload,
            state="pending",
            attempts=0,
            next_attempt_at=now,
            replaces_id=obs.replaces_id,
            source=source,
            created_at=now,
            updated_at=now,
            acked_at=None,
            reason="",
            draft=None,
        )
        self.outbox.mark_rate(now)
        self.outbox.add(item)
        self.log.event("enqueued", eventId=event_id, source=source, disposition="enqueued")
        return HandleResult("enqueued", "ENQUEUED", event_id)

    def handle_listener(self, *, package: str, notification_key: str, title: str | None, post_time_ms: int | None = None) -> HandleResult:
        observation, reason = from_listener(
            package=package,
            notification_key=notification_key,
            title=title,
            post_time_ms=post_time_ms,
        )
        if observation is None:
            if not self.outbox.blocked:
                self.outbox.add_gap(reason)
            self.log.event("ignored", reason=reason, disposition="ignored")
            return HandleResult("ignored", reason)
        return self.handle(observation)

    def enqueue_chat_ref(self, chat_ref: str, replaces_id: int) -> HandleResult:
        # A v2 person hint is not an allowlist match. The configured label is not
        # consulted, and the payload does not receive a display name.
        if not isinstance(chat_ref, str) or CHAT_REF.fullmatch(chat_ref) is None:
            return HandleResult("ignored", "UNTRUSTED_REF")
        if self.outbox.blocked:
            return HandleResult("ignored", "CORRUPT")
        if self.outbox.stopped or not self.enabled:
            return HandleResult("ignored", "STOPPED" if self.outbox.stopped else "DISABLED")
        now = self.outbox.clock.now()
        source = "unread-indicator-hint"
        action, existing = self.outbox.plan(source, replaces_id, now)
        if action == "update" and existing is not None:
            existing.payload["observedAt"] = iso(now)
            validate(existing.payload)
            existing.updated_at = now
            self.outbox.save()
            return HandleResult("replaced", "REPLACED", existing.event_id)
        if action == "drop":
            return HandleResult("ignored", "DEBOUNCED")
        if not self.outbox.rate_ok(now):
            return HandleResult("ignored", "RATE_CAP")
        event_id = new_event_id()
        payload = build_v2(event_id=event_id, observed_at=iso(now), chat_ref=chat_ref)
        item = Item(
            event_id=event_id,
            payload=payload,
            state="pending",
            attempts=0,
            next_attempt_at=now,
            replaces_id=replaces_id,
            source=source,
            created_at=now,
            updated_at=now,
            acked_at=None,
            reason="",
            draft=None,
        )
        self.outbox.mark_rate(now)
        self.outbox.add(item)
        self.log.event("enqueued", eventId=event_id, source=source, disposition="enqueued")
        return HandleResult("enqueued", "ENQUEUED", event_id)

    def enqueue_list_change(self, replaces_id: int) -> HandleResult:
        # The event says the visible unread total rose. It does not name a row.
        if self.outbox.blocked:
            return HandleResult("ignored", "CORRUPT")
        if self.outbox.stopped or not self.enabled:
            return HandleResult("ignored", "STOPPED" if self.outbox.stopped else "DISABLED")
        now = self.outbox.clock.now()
        source = "list-change"
        action, existing = self.outbox.plan(source, replaces_id, now)
        if action == "update" and existing is not None:
            existing.payload["observedAt"] = iso(now)
            validate(existing.payload)
            existing.updated_at = now
            self.outbox.save()
            return HandleResult("replaced", "REPLACED", existing.event_id)
        if action == "drop":
            return HandleResult("ignored", "DEBOUNCED")
        if not self.outbox.rate_ok(now):
            return HandleResult("ignored", "RATE_CAP")
        event_id = new_event_id()
        payload = build_v3(event_id=event_id, observed_at=iso(now))
        item = Item(
            event_id=event_id,
            payload=payload,
            state="pending",
            attempts=0,
            next_attempt_at=now,
            replaces_id=replaces_id,
            source=source,
            created_at=now,
            updated_at=now,
            acked_at=None,
            reason="",
            draft=None,
        )
        self.outbox.mark_rate(now)
        self.outbox.add(item)
        self.log.event("enqueued", eventId=event_id, source=source, disposition="enqueued")
        return HandleResult("enqueued", "ENQUEUED", event_id)

    def note_silence(self) -> None:
        self.outbox.add_gap("NO_NOTIFICATION")
        self.log.event("gap", reason="NO_NOTIFICATION")

    def note_disconnect(self) -> None:
        self.outbox.add_gap("RECONNECT_GAP")
        self.log.event("gap", reason="RECONNECT_GAP")

    def stop(self) -> None:
        self.outbox.set_stopped(True)
        self.log.event("stopped", reason="STOPPED")

    def resume(self) -> None:
        self.outbox.set_stopped(False)

    def flush(self) -> int:
        if self.outbox.blocked:
            return 0
        if self.outbox.stopped or self.client is None:
            if self.outbox.due() or self.outbox.stopped:
                self.outbox.add_gap("TRANSMISSION_OFF")
            self.log.event("flush", reason="TRANSMISSION_OFF")
            return 0
        sent = 0
        for item in list(self.outbox.due()):
            item.state = "in_flight"
            item.attempts += 1
            self.outbox.save()
            result = self.client.post(item.payload)
            if result.status == "acked":
                item.state = "acked"
                item.acked_at = self.outbox.clock.now()
                item.reason = _stored_reason(result)
                # A 2xx on the official transport is not a reply. The labelled
                # fixture is only the explicit local test-receipt contract.
                if result.classification in ("receipt", "receipt-duplicate"):
                    item.draft = _draft(item.event_id)
                else:
                    item.draft = None
                fields = {
                    "eventId": item.event_id,
                    "state": "acked",
                    "source": item.source,
                    "reason": item.reason,
                    "attempt": item.attempts,
                }
                if result.classification in ("receipt", "receipt-duplicate"):
                    fields["unique"] = not result.duplicate
                self.log.event("acked", **fields)
            elif result.status == "retryable":
                if item.attempts >= self.outbox.max_attempts:
                    item.state = "rejected"
                    item.reason = "GAVE_UP"
                    self.outbox.add_gap("GAVE_UP")
                    self.log.event(
                        "gave-up",
                        eventId=item.event_id,
                        state="rejected",
                        reason="GAVE_UP",
                        attempt=item.attempts,
                    )
                else:
                    item.state = "retryable"
                    item.next_attempt_at = self.outbox.clock.now() + delay_seconds(item.attempts)
                    item.reason = "RETRY"
                    self.log.event(
                        "retry",
                        eventId=item.event_id,
                        state="retryable",
                        reason="RETRY",
                        attempt=item.attempts,
                    )
            else:
                item.state = "rejected"
                item.reason = "REJECTED"
                self.outbox.add_gap("REJECTED")
                self.log.event(
                    "rejected",
                    eventId=item.event_id,
                    state="rejected",
                    reason="REJECTED",
                    attempt=item.attempts,
                )
            self.outbox.save()
            sent += 1
        return sent


def _stored_reason(result) -> str:
    return stored_reason(result.classification, result.duplicate)


def _draft(event_id: str) -> dict:
    """Local test-receipt fixture. Not stored for an official transport ack."""

    return {
        "eventId": event_id,
        "handler": "local-mock-handler",
        "placeholder": "LOCAL MOCK",
        "sendingEnabled": False,
        "sent": False,
        "verifiedRemoteRecipient": False,
        "readsChat": False,
        "sendsWhatsApp": False,
    }
