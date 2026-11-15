"""Local resolution of an opaque chatRef.

The webhook never carries a display name. The receiver asks this module, on
the same machine, to queue one open permit. The extension popup is the only
component that turns that permit into a click, and only after it re-reads the
visible list. A permit is not a chat receipt.
"""

import json
import re
from pathlib import Path

from wake.envelope import CHAT_REF, SCHEMA_FIELD, SCHEMA_V2, SCHEMA_V3

EVENT_ID = re.compile(r"^evt-[0-9a-f]{32}$")
SESSION_SECONDS = 600
PERMIT_SECONDS = 60
SESSIONS_NAME = "person-sessions.json"
PERMIT_NAME = "open-permit.json"
OPENED_NAME = "opened-events.json"


def touch_session(directory: Path, chat_ref: str, now: float) -> bool:
    if CHAT_REF.fullmatch(chat_ref or "") is None:
        return False
    sessions = _sessions(directory)
    sessions[chat_ref] = {"expires": float(now) + SESSION_SECONDS}
    _write(Path(directory) / SESSIONS_NAME, {"sessions": sessions})
    return True


def permit_open(directory: Path, event_id: str, chat_ref: str, now: float) -> str:
    if EVENT_ID.fullmatch(event_id or "") is None or CHAT_REF.fullmatch(chat_ref or "") is None:
        return "MALFORMED"
    item = _item(directory, event_id)
    if item is None:
        return "UNKNOWN_EVENT"
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return "MALFORMED"
    if payload.get("field") == SCHEMA_FIELD:
        return "V1_SCOPE"
    if payload.get("field") == SCHEMA_V3:
        return "UNTARGETED"
    if payload.get("field") != SCHEMA_V2:
        return "MALFORMED"
    if item.get("reason") == "transport-accepted":
        return "TRANSPORT_ONLY"
    if item.get("reason") == "legacy-409":
        return "LEGACY_409"
    if payload.get("chatRef") != chat_ref:
        return "REF_MISMATCH"
    if item.get("reason") == "duplicate":
        return "DUPLICATE_EVENT"
    if item.get("state") != "acked" or item.get("reason") != "acked":
        return "NOT_ACKED"
    if _latest_unique(directory, chat_ref) != event_id:
        return "STALE_EVENT"
    if event_id in _opened(directory):
        return "DUPLICATE_OPEN"
    expires = _session_expires(directory, chat_ref)
    if expires is None or expires <= float(now):
        return "SESSION_EXPIRED"
    current = _permit(directory)
    if (
        current is not None
        and current.get("state") == "queued"
        and float(current.get("expires") or 0) > float(now)
        and current.get("eventId") != event_id
    ):
        return "PERMIT_PENDING"
    _write(
        Path(directory) / PERMIT_NAME,
        {
            "eventId": event_id,
            "chatRef": chat_ref,
            "expires": float(now) + PERMIT_SECONDS,
            "state": "queued",
        },
    )
    return "OPEN_QUEUED"


def take_permit(directory: Path, now: float) -> dict | None:
    current = _permit(directory)
    path = Path(directory) / PERMIT_NAME
    if current is None or current.get("state") != "queued" or float(current.get("expires") or 0) <= float(now):
        if path.exists():
            path.unlink()
        return None
    event_id = current.get("eventId")
    chat_ref = current.get("chatRef")
    if not isinstance(event_id, str) or not isinstance(chat_ref, str):
        path.unlink()
        return None
    if permit_open(directory, event_id, chat_ref, now) not in {"OPEN_QUEUED", "PERMIT_PENDING"}:
        if path.exists():
            path.unlink()
        return None
    opened = _opened(directory)
    if event_id not in opened:
        opened.append(event_id)
    _write(Path(directory) / OPENED_NAME, {"ids": opened[-100:]})
    if path.exists():
        path.unlink()
    return {"eventId": event_id, "chatRef": chat_ref}


def _item(directory: Path, event_id: str) -> dict | None:
    for item in _items(directory):
        if item.get("eventId") == event_id:
            return item
    return None


def _latest_unique(directory: Path, chat_ref: str) -> str | None:
    chosen = None
    stamp = -1.0
    for item in _items(directory):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if payload.get("field") != SCHEMA_V2 or payload.get("chatRef") != chat_ref:
            continue
        if item.get("state") != "acked" or item.get("reason") != "acked":
            continue
        acked = item.get("ackedAt")
        if isinstance(acked, bool) or not isinstance(acked, (int, float)):
            continue
        if float(acked) >= stamp:
            stamp = float(acked)
            chosen = item.get("eventId")
    return chosen if isinstance(chosen, str) else None


def _items(directory: Path) -> list:
    data = _read(Path(directory) / "outbox.json")
    rows = data.get("items") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _sessions(directory: Path) -> dict:
    data = _read(Path(directory) / SESSIONS_NAME)
    rows = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    clean = {}
    for ref, row in rows.items():
        if CHAT_REF.fullmatch(str(ref)) is None or not isinstance(row, dict):
            continue
        expires = row.get("expires")
        if isinstance(expires, bool) or not isinstance(expires, (int, float)):
            continue
        clean[str(ref)] = {"expires": float(expires)}
    return clean


def _session_expires(directory: Path, chat_ref: str):
    row = _sessions(directory).get(chat_ref)
    if row is None:
        return None
    return row["expires"]


def _permit(directory: Path):
    data = _read(Path(directory) / PERMIT_NAME)
    if not isinstance(data, dict):
        return None
    if set(data) - {"eventId", "chatRef", "expires", "state"}:
        return None
    return data


def _opened(directory: Path) -> list:
    data = _read(Path(directory) / OPENED_NAME)
    rows = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, str) and EVENT_ID.fullmatch(item)]


def _read(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
