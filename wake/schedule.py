"""Wait for the outbox retry time, then flush.

``next_attempt_at`` used to be stored and only consulted when a later
notification called ``flush``. A failed delivery now waits out its own delay
and tries again without a new notification.
"""


def seconds_until_due(outbox) -> float | None:
    if outbox.blocked or outbox.stopped:
        return None
    now = outbox.clock.now()
    due = False
    soon = None
    for item in outbox.items.values():
        if item.state not in ("pending", "retryable"):
            continue
        delay = item.next_attempt_at - now
        if delay <= 0:
            due = True
        elif soon is None or delay < soon:
            soon = delay
    if due:
        return 0.0
    return soon


def outstanding(outbox) -> bool:
    if outbox.blocked:
        return False
    return any(item.state in ("pending", "retryable") for item in outbox.items.values())


def flush_until(pipeline, *, seconds: float, sleep, now) -> str:
    """Flush, then sleep until the next attempt is due.

    ``sleep`` advances whatever clock ``now`` and the outbox share. In the
    runtime process those are wall time and ``time.sleep``. A test passes a
    fake clock for both. The URL is not passed to ``sleep``.
    """

    if seconds < 0:
        raise ValueError("seconds")
    deadline = now() + float(seconds)
    spins = 0
    while True:
        pipeline.flush()
        if pipeline.outbox.blocked:
            return "blocked"
        if not outstanding(pipeline.outbox):
            return "settled"
        delay = seconds_until_due(pipeline.outbox)
        if delay is None:
            return "idle"
        if delay <= 0:
            spins += 1
            if spins > 5:
                return "time"
            continue
        spins = 0
        remaining = deadline - now()
        if remaining <= 0:
            return "time"
        sleep(min(delay, remaining))
