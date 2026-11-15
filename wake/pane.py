"""Open-pane attention on the same targetless v3 wake.

The message carries a generation and nothing else. The webhook payload is
still ``whatsapp-wake-test-v3`` with no chat, name, count, or body. One
unacked v3 item blocks the next, so two workers are not posted together.
A repeated generation does not post again.
"""

import hashlib
import json
from pathlib import Path

from wake.envelope import SCHEMA_V3

STATE_NAME = "pane-hint.json"
GENERATION_MAX = 9999
_BUSY = frozenset({"pending", "in_flight", "retryable"})


def apply_pane_hint(directory: Path, hint, *, pipeline, wire: str) -> dict:
    directory = Path(directory)
    generation = _generation(hint)
    if generation is None:
        return {"disposition": "UNPARSEABLE", "posted": False, "signal": "pane-hint"}
    if wire != "list":
        return {"disposition": "SCHEMA_HELD", "posted": False, "signal": "pane-hint"}
    if pipeline.outbox.stopped or not pipeline.enabled:
        return {"disposition": "STOPPED", "posted": False, "signal": "pane-hint"}
    state = _load(directory)
    if generation > state["pending"]:
        state["pending"] = generation
        _save(directory, state)
    if state["pending"] <= state["posted"]:
        return {"disposition": "NO_NEW", "posted": False, "signal": "pane-hint", "generation": state["posted"]}
    if _busy(pipeline):
        return {"disposition": "BUSY", "posted": False, "signal": "pane-hint", "generation": state["pending"]}
    result = pipeline.enqueue_list_change(_replaces(state["posted"], state["pending"]))
    if result.disposition not in ("enqueued", "replaced") or not result.event_id:
        if result.reason == "DEBOUNCED":
            return {"disposition": "NO_NEW", "posted": False, "signal": "pane-hint", "generation": state["posted"]}
        return {"disposition": "PANE_HINT", "posted": False, "signal": "pane-hint", "forward": "error"}
    pipeline.flush()
    item = pipeline.outbox.items.get(result.event_id)
    posted = item is not None and item.state == "acked"
    if posted:
        state["posted"] = state["pending"]
        _save(directory, state)
    return {
        "disposition": "PANE_HINT",
        "posted": posted,
        "signal": "pane-hint",
        "generation": state["posted"] if posted else state["pending"],
        "event": result.event_id,
        "forward": "accepted" if posted else "attempted",
    }


def _generation(hint):
    if not isinstance(hint, dict) or set(hint) != {"generation"}:
        return None
    generation = hint.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int):
        return None
    if not 1 <= generation <= GENERATION_MAX:
        return None
    return generation


def _busy(pipeline) -> bool:
    for item in pipeline.outbox.items.values():
        payload = item.payload if isinstance(item.payload, dict) else {}
        if payload.get("field") == SCHEMA_V3 and item.state in _BUSY:
            return True
    return False


def _replaces(posted: int, pending: int) -> int:
    raw = f"list-change:v3:pane:{posted}:{pending}".encode("ascii")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") or 1


def _load(directory: Path) -> dict:
    path = Path(directory) / STATE_NAME
    if not path.exists():
        return {"posted": 0, "pending": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"posted": 0, "pending": 0}
    posted = data.get("posted") if isinstance(data, dict) else None
    pending = data.get("pending") if isinstance(data, dict) else None
    if isinstance(posted, bool) or not isinstance(posted, int) or posted < 0:
        return {"posted": 0, "pending": 0}
    if isinstance(pending, bool) or not isinstance(pending, int) or pending < posted:
        return {"posted": 0, "pending": 0}
    return {"posted": posted, "pending": pending}


def _save(directory: Path, state: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / STATE_NAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"pending": state["pending"], "posted": state["posted"]}, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
