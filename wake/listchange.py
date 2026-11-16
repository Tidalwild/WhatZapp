"""Targetless list-change wake.

The payload is ``whatsapp-wake-test-v3``. It carries no chat, name, count,
or phone. A rise in the visible numbered-unread total asks the browser to
look at whatever unread rows are on screen now. The total stays in the local
file. The default wire does not post this schema.
"""

import hashlib
import json
from pathlib import Path

from wake.clock import iso
from wake.envelope import build_v3
from wake.ledger import note_held, note_posted, outbox_outstanding, worker_locked

STATE_NAME = "list-change.json"
COUNT_MAX = 9999


def apply_list_change(directory: Path, hint, *, pipeline, wire: str) -> dict:
    directory = Path(directory)
    parsed = _parse(hint)
    if parsed is None:
        return {"disposition": "UNPARSEABLE", "posted": False, "signal": "list-change"}
    mark, count = parsed
    if wire != "list":
        return {"disposition": "SCHEMA_HELD", "posted": False, "signal": "list-change"}
    if pipeline.outbox.stopped or not pipeline.enabled:
        return {"disposition": "STOPPED", "posted": False, "signal": "list-change"}
    state = _load(directory)
    at = iso(pipeline.outbox.clock.now())
    if mark == "absent" or count == 0:
        _save(directory, 0, 0 if state is None else state["generation"])
        return _sample("COUNT_CLEARED", count=0, prior=None if state is None else state["count"], at=at)
    if state is None:
        _save(directory, count, 0)
        return _sample("COUNT_BASELINE", count=count, stored=count, change="baseline", at=at)
    previous = state["count"]
    generation = state["generation"]
    if count == previous:
        return _sample("NO_NEW", count=count, prior=previous, stored=count, change="same", at=at)
    if count < previous:
        _save(directory, count, generation)
        return _sample("COUNT_DOWN", count=count, prior=previous, stored=count, change="down", at=at)
    if outbox_outstanding(pipeline):
        return _sample("COUNT_HELD", count=count, prior=previous, stored=previous, change="held", at=at, covered=False)
    locked = worker_locked(directory)
    if locked is None:
        return _sample("UNREADABLE", count=count, prior=previous, change="held", at=at, covered=False)
    key = f"list:{previous}:{count}:{generation}"
    observed = int(pipeline.outbox.clock.now())
    if locked:
        outcome, event = note_held(directory, key, observed)
        if outcome in {"HELD", "COALESCED", "DUPLICATE"}:
            _save(directory, count, generation)
        disposition = "NO_NEW" if outcome == "DUPLICATE" else "HELD"
        if outcome not in {"HELD", "COALESCED", "DUPLICATE"}:
            disposition = "UNREADABLE"
            event = ""
        return _sample(
            disposition,
            count=count,
            prior=previous,
            stored=count if disposition != "UNREADABLE" else previous,
            change="held",
            posted=False,
            event=event,
            covered=False,
            at=at,
        )
    result = pipeline.enqueue_list_change(_replaces(previous, count, generation))
    if result.disposition not in ("enqueued", "replaced") or not result.event_id:
        if result.reason == "DEBOUNCED":
            return _sample("COUNT_HELD", count=count, prior=previous, change="held", at=at, covered=False)
        return _sample("COUNT_UP", count=count, prior=previous, change="up", forward="error", at=at, covered=False)
    pipeline.flush()
    item = pipeline.outbox.items.get(result.event_id)
    posted = item is not None and item.state == "acked"
    if posted:
        note_posted(directory, result.event_id, key, observed)
        _save(directory, count, generation + 1)
    return _sample(
        "COUNT_UP",
        count=count,
        prior=previous,
        stored=count if posted else previous,
        change="up",
        posted=posted,
        forward="accepted" if posted else "attempted",
        event=result.event_id,
        covered=False,
        at=at,
    )


def _parse(hint):
    if not isinstance(hint, dict) or set(hint) - {"mark", "count"} or "mark" not in hint:
        return None
    mark = hint.get("mark")
    if mark == "absent":
        if "count" in hint and hint.get("count") != 0:
            return None
        return mark, 0
    if mark != "count":
        return None
    count = hint.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= COUNT_MAX:
        return None
    return mark, count


def _replaces(previous: int, current: int, generation: int) -> int:
    raw = f"list-change:v3:{previous}:{current}:{generation}".encode("ascii")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") or 1


def _load(directory: Path):
    path = Path(directory) / STATE_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    count = data.get("count")
    generation = data.get("generation")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > COUNT_MAX:
        return None
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        return None
    return {"count": count, "generation": generation}


def _save(directory: Path, count: int, generation: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / STATE_NAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"count": count, "generation": generation}, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sample(disposition: str, **extra) -> dict:
    sample = {"disposition": disposition, "posted": False, "signal": "list-change"}
    sample.update(extra)
    return sample
