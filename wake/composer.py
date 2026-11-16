"""Visible composer sample. Not a bot response and not coverage.

The extension already measures the open textbox as empty, occupied, or
unmeasured. This file stores that state and an optional wake event id.
It does not store the text, does not decide who typed it, and does not
change the event ledger. No sample means the textbox was not observed.
That is not evidence the routine cannot draft.
"""

import json
import os
import re
from pathlib import Path

from wake.ledger import load as load_ledger

NAME = "composer-sample.json"
FORMAT = "wake-composer-1"
STATES = frozenset({"empty", "occupied", "unmeasured"})
_EVENT = re.compile(r"^evt-[0-9a-f]{32}$")


def note_sample(directory: Path, state: str, event: str, observed_at) -> str:
    if state not in STATES:
        return "UNPARSEABLE"
    if not isinstance(event, str) or (event != "" and _EVENT.fullmatch(event) is None):
        return "UNPARSEABLE"
    seconds = _seconds(observed_at)
    if seconds is None:
        return "UNPARSEABLE"
    if not save(directory, {"format": FORMAT, "state": state, "event": event, "observedAt": seconds}):
        return "UNREADABLE"
    return "NOTED"


def composer_state(directory: Path) -> str:
    sample = load(directory)
    if sample is None:
        path = Path(directory) / NAME
        if not os.path.lexists(path):
            return "not-observed"
        return "unreadable"
    return sample["state"]


def composer_event(directory: Path) -> str:
    sample = load(directory)
    if sample is None or sample["event"] == "":
        return "none"
    if _known(directory, sample["event"]):
        return "linked"
    return "unmatched"


def load(directory: Path) -> dict | None:
    path = Path(directory) / NAME
    if not os.path.lexists(path):
        return None
    if os.path.islink(path) or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or set(data) != {"format", "state", "event", "observedAt"}:
        return None
    if data.get("format") != FORMAT or data.get("state") not in STATES:
        return None
    event = data.get("event")
    stamp = data.get("observedAt")
    if not isinstance(event, str) or (event != "" and _EVENT.fullmatch(event) is None):
        return None
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 0:
        return None
    return {"format": FORMAT, "state": data["state"], "event": event, "observedAt": stamp}


def save(directory: Path, payload: dict) -> bool:
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


def _known(directory: Path, event: str) -> bool:
    ledger = load_ledger(directory)
    if ledger is not None and event in ledger.seen:
        return True
    path = Path(directory) / "outbox.json"
    if not path.is_file() or path.is_symlink():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get("eventId") == event for item in items)


def _seconds(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    whole = int(value)
    if whole < 0:
        return None
    return whole
