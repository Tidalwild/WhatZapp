"""Privacy-safe stage timings. Missing stages stay missing.

Receipt, queue, and handoff come from the outbox timestamps. A read note is
the only stage the extension may add, and it carries no message text. The
composer sample stays an observation, not authorship. The result stage stays
missing: this package does not record a finished routine draft, and that
absence is not an inability. Approval wait is reported separately from
processing time. No target latency is invented.
"""

import json
import os
import re
from pathlib import Path

from wake.approval import load as load_approval
from wake.composer import load as load_composer

NAME = "stage-note.json"
FORMAT = "wake-trace-1"


def note_read(directory: Path, event: str, observed_at) -> str:
    if not isinstance(event, str):
        return "UNPARSEABLE"
    if event != "" and re.fullmatch(r"evt-[0-9a-f]{32}", event) is None:
        return "UNPARSEABLE"
    stamp = _seconds(observed_at)
    if stamp is None:
        return "UNPARSEABLE"
    payload = {"format": FORMAT, "read": {"at": stamp, "event": event, "outcome": "noted"}}
    return "NOTED" if _save(directory, payload) else "UNREADABLE"


def report(directory: Path) -> dict:
    queue_at, handoff_at, receipt, queue, handoff = _outbox(directory)
    read = _read(directory)
    composer = load_composer(directory)
    approval = load_approval(directory)
    stages = {
        "receipt": "present" if receipt else "missing",
        "queue": "present" if queue else "missing",
        "read": "present" if read is not None else "missing",
        "handoff": handoff,
        "composer": "unproven" if composer is not None else "missing",
        "approval": "present" if approval is not None and approval["phase"] == "approved" else "missing",
        "result": "missing",
    }
    processing = None
    if queue_at is not None and handoff_at is not None and handoff == "present" and handoff_at >= queue_at:
        processing = int(handoff_at - queue_at)
    return {
        "stages": stages,
        "processing_ms": None if processing is None else processing * 1000,
        "approval_wait": "separate",
        "approval_wait_ms": None,
        "baseline": "partial" if any(value != "missing" for value in stages.values()) else "none",
        "authorship": "unproven",
        "draft_interface": "page-composer",
        "response_absence": "not-inability",
    }


def format_report(directory: Path) -> list[str]:
    found = report(directory)
    order = ("receipt", "queue", "read", "handoff", "composer", "approval", "result")
    stages = ",".join(f"{name}={found['stages'][name]}" for name in order)
    processing = "unavailable" if found["processing_ms"] is None else str(found["processing_ms"])
    return [
        f"stages: {stages}",
        f"processing-ms: {processing}",
        "approval-wait: separate",
        "approval-wait-ms: unavailable",
        f"baseline: {found['baseline']}",
        "authorship: unproven",
        "draft-interface: page-composer",
    ]


def _outbox(directory: Path) -> tuple:
    path = Path(directory) / "outbox.json"
    if not path.is_file() or path.is_symlink():
        return None, None, False, False, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None, False, False, "missing"
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None, None, False, False, "missing"
    receipt = False
    queue = False
    queue_at = None
    handoff_at = None
    handoff = "missing"
    for item in items:
        if not isinstance(item, dict):
            continue
        receipt = True
        state = item.get("state")
        created = _seconds(item.get("createdAt"))
        if state == "pending":
            queue = True
            if created is not None:
                queue_at = created if queue_at is None else min(queue_at, created)
        elif created is not None and queue_at is None:
            queue_at = created
        reason = item.get("reason")
        draft = item.get("draft")
        mock = isinstance(draft, dict) and draft.get("handler") == "local-mock-handler"
        acked = _seconds(item.get("ackedAt"))
        if state == "acked" and reason == "transport-accepted" and not mock:
            handoff = "present"
            if acked is not None:
                handoff_at = acked if handoff_at is None else min(handoff_at, acked)
        elif mock and handoff == "missing":
            handoff = "not-a-response"
    return queue_at, handoff_at, receipt, queue, handoff


def _read(directory: Path) -> dict | None:
    path = Path(directory) / NAME
    if not os.path.lexists(path) or os.path.islink(path) or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or set(data) != {"format", "read"} or data.get("format") != FORMAT:
        return None
    read = data.get("read")
    if not isinstance(read, dict) or set(read) != {"at", "event", "outcome"}:
        return None
    if read.get("outcome") != "noted" or _seconds(read.get("at")) is None:
        return None
    event = read.get("event")
    if not isinstance(event, str):
        return None
    if event != "" and re.fullmatch(r"evt-[0-9a-f]{32}", event) is None:
        return None
    return {"at": int(read["at"]), "event": event, "outcome": "noted"}


def _save(directory: Path, payload: dict) -> bool:
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
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def _seconds(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    whole = int(value)
    if whole < 0:
        return None
    return whole
