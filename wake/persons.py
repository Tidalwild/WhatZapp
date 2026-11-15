"""Versioned person-list wake.

Schema ``whatsapp-wake-test-v1`` stays the single-label wire. Its receiver
checks ``conversationScope`` against the configured label. This module does
not put a person token on that wire.

Schema ``whatsapp-wake-test-v2`` carries ``chatRef`` only. The default wire
is v1, so a v2 hint is held and not posted until ``WHATSAPP_WAKE_WIRE=v2``.
That flag is the host/receiver migration gate. The installed receiver rejects
a v2 field. Do not set the flag until that receiver accepts ``chatRef`` and
resolves it only from the local table on the machine that observed the row.
"""

import hashlib
import json
from pathlib import Path

from wake.clock import iso
from wake.envelope import CHAT_REF

COUNTS_NAME = "person-counts.json"
MARKS = frozenset({"absent", "count"})
COUNT_MAX = 9999


def apply_person_hint(directory: Path, hint, *, pipeline, wire: str) -> dict:
    directory = Path(directory)
    parsed = _parse(hint)
    if parsed is None:
        return {"disposition": "UNPARSEABLE", "posted": False, "signal": "person-list"}
    chat_ref, mark, count = parsed
    if wire != "v2":
        return {"disposition": "SCHEMA_HELD", "posted": False, "signal": "person-list", "chatRef": chat_ref}
    if pipeline.outbox.stopped or not pipeline.enabled:
        return {"disposition": "STOPPED", "posted": False, "signal": "person-list"}
    state = _load(directory).get(chat_ref)
    at = iso(pipeline.outbox.clock.now())
    if mark == "absent" or count == 0:
        _save(directory, chat_ref, 0, 0 if state is None else state["generation"])
        return _sample("COUNT_CLEARED", chat_ref, count=0, prior=None if state is None else state["count"], at=at)
    if state is None:
        _save(directory, chat_ref, count, 0)
        return _sample("COUNT_BASELINE", chat_ref, count=count, stored=count, change="baseline", at=at)
    previous = state["count"]
    generation = state["generation"]
    if count == previous:
        return _sample("NO_NEW", chat_ref, count=count, prior=previous, stored=count, change="same", at=at)
    if count < previous:
        _save(directory, chat_ref, count, generation)
        return _sample("COUNT_DOWN", chat_ref, count=count, prior=previous, stored=count, change="down", at=at)
    result = pipeline.enqueue_chat_ref(chat_ref, _replaces(chat_ref, previous, count, generation))
    if result.disposition not in ("enqueued", "replaced") or not result.event_id:
        if result.reason == "DEBOUNCED":
            return _sample("COUNT_HELD", chat_ref, count=count, prior=previous, change="held", at=at)
        return _sample("COUNT_UP", chat_ref, count=count, prior=previous, change="up", forward="error", at=at)
    pipeline.flush()
    item = pipeline.outbox.items.get(result.event_id)
    posted = item is not None and item.state == "acked"
    if posted:
        _save(directory, chat_ref, count, generation + 1)
    return _sample(
        "COUNT_UP",
        chat_ref,
        count=count,
        prior=previous,
        stored=count if posted else previous,
        change="up",
        posted=posted,
        forward="accepted" if posted else "attempted",
        event=result.event_id,
        at=at,
    )


def _parse(hint):
    if not isinstance(hint, dict):
        return None
    allowed = {"chatRef", "mark", "count"}
    if set(hint) - allowed or "chatRef" not in hint or "mark" not in hint:
        return None
    chat_ref = hint.get("chatRef")
    mark = hint.get("mark")
    if not isinstance(chat_ref, str) or CHAT_REF.fullmatch(chat_ref) is None:
        return None
    if mark not in MARKS:
        return None
    if mark == "absent":
        if "count" in hint and hint.get("count") != 0:
            return None
        return chat_ref, mark, 0
    count = hint.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= COUNT_MAX:
        return None
    return chat_ref, mark, count


def _replaces(chat_ref: str, previous: int, current: int, generation: int) -> int:
    raw = f"unread-indicator-hint:v2:{chat_ref}:{previous}:{current}:{generation}".encode("ascii")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") or 1


def _load(directory: Path) -> dict:
    path = Path(directory) / COUNTS_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    chats = data.get("chats") if isinstance(data, dict) else None
    if not isinstance(chats, dict):
        return {}
    clean = {}
    for ref, row in chats.items():
        if CHAT_REF.fullmatch(str(ref)) is None or not isinstance(row, dict):
            continue
        count = row.get("count")
        generation = row.get("generation")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > COUNT_MAX:
            continue
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            continue
        clean[str(ref)] = {"count": count, "generation": generation}
    return clean


def _save(directory: Path, chat_ref: str, count: int, generation: int) -> None:
    chats = _load(directory)
    chats[chat_ref] = {"count": count, "generation": generation}
    path = Path(directory) / COUNTS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"chats": chats}, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _sample(disposition: str, chat_ref: str, **extra) -> dict:
    public = {"disposition": disposition, "posted": bool(extra.get("posted")), "signal": "person-list", "chatRef": chat_ref}
    for key in ("count", "prior", "stored", "change", "forward", "event", "at"):
        if key in extra and extra[key] is not None:
            public[key] = extra[key]
    return public
