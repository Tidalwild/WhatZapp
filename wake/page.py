"""Page-change wake. This is not a desktop notification.

Two rendered signals can post ``web-page-change``. Both require the existing
local binding and an allowlist token equal to that binding's visible header.
A display name by itself is not enough.

The open-chat signal is one new inbound row after a baseline. The boolean
chat-list signal is the bound row, uniquely identified, gaining a boolean
unread mark while no other row changed. A move to the top without that unread
change does not wake. That boolean path is not used for a numbered badge.

``mark`` ``count`` is one visible numbered unread badge. The integer stays in
the local list file. It is not a sender, a body, or a verified message. On a
metadata binding, a stored count rising to a larger positive count posts one
``unread-indicator-hint``. The first counted sample, including a badge that is
already visible and an older file that has no count, is ``COUNT_BASELINE`` and
does not post. An unchanged count, a decrease, and a clear do not post. An
unknown, ambiguous, or empty-dot sample does not post and does not replace the
stored count. Another row changing in the same sample does not hide a rise.
``mark`` ``dot`` is the empty manual indicator. It does not post.

``unread`` null, with no ``mark``, means the row was identified and the
indicator was not classified. That does not post and does not record a
baseline. Other rows' names, order, and previews are not stored or sent.

The webhook envelope is the same metadata shape as a notification wake. It
has no message body and no preview.
"""

import hashlib
import json
from pathlib import Path

from wake.clock import iso
from wake.model import Observation
from wake.policy import valid_label
from wake.read import (
    bind_local,
    load_binding,
    preview_tail,
    read_snapshot,
    _append_draft,
    _draft,
    _write,
)

LIST_NAME = "list-window.json"
LIST_KEYS = frozenset({"layout", "boundLabel", "matches", "position", "unread", "mark", "count", "otherChanges"})
MARKS = frozenset({"absent", "dot", "count", "unknown", "ambiguous"})
LIST_REPLACES = int.from_bytes(hashlib.sha256(b"web-page-change:chat-list").digest()[:4], "big") or 1
COUNT_MAX = 9999


def apply_page(directory: Path, snapshot, *, allowlist: str, pipeline) -> dict:
    directory = Path(directory)
    if pipeline.outbox.stopped or not pipeline.enabled:
        return _public("STOPPED")
    if not isinstance(snapshot, dict):
        return _public("UNRECOGNIZED")
    layout = snapshot.get("layout")
    if layout == "chat-list-contract":
        return _list(directory, snapshot, allowlist, pipeline)
    if layout == "probe-contract":
        return _tail(directory, snapshot, allowlist, pipeline)
    return _public("UNRECOGNIZED")


def _tail(directory: Path, snapshot, allowlist: str, pipeline) -> dict:
    if not _scope_ok(directory, allowlist):
        return _scope_block(directory)
    preview = preview_tail(directory, snapshot)
    if not preview.get("candidate"):
        return _public(preview["disposition"], signal="open-tail")
    posted, event_id = _post(pipeline, allowlist, int(preview["replaces"]))
    if not posted:
        return _public("WAKE_NOT_ACKED", signal="open-tail", posted=True)
    drafted = read_snapshot(directory, snapshot, pipeline.outbox, event_id)
    return _public(
        drafted["disposition"],
        signal="open-tail",
        posted=True,
        draft=bool(drafted["draft"]),
    )


def _list(directory: Path, snapshot, allowlist: str, pipeline) -> dict:
    if set(snapshot) - LIST_KEYS:
        return _public("UNTRUSTED_FIELD", signal="chat-list")
    if not _scope_ok(directory, allowlist):
        return _scope_block(directory, signal="chat-list")
    if snapshot.get("boundLabel") != allowlist:
        return _public("SCOPE_MISMATCH", signal="chat-list")
    parsed = _list_fields(snapshot)
    if parsed is None:
        return _public("UNPARSEABLE", signal="chat-list")
    matches, position, unread, other = parsed
    if matches != 1:
        return _public("NOT_UNIQUE", signal="chat-list")
    mark = snapshot.get("mark") if "mark" in snapshot else None
    if mark is not None and mark not in MARKS:
        return _public("UNPARSEABLE", signal="chat-list")
    binding = load_binding(directory)
    # A numbered badge is decided before other-row churn. An empty dot, an
    # unknown row, and an ambiguous row do not replace a stored count.
    if mark == "count":
        if unread is not None or not _good_count(snapshot.get("count"), positive=True):
            return _public("UNPARSEABLE", signal="chat-list")
        return _apply_count(directory, binding, pipeline, position, int(snapshot["count"]))
    if mark == "absent":
        if unread is not False:
            return _public("UNPARSEABLE", signal="chat-list")
        if "count" in snapshot and (not _good_count(snapshot.get("count")) or snapshot.get("count") != 0):
            return _public("UNPARSEABLE", signal="chat-list")
        return _apply_count(directory, binding, pipeline, position, 0)
    if mark == "dot":
        if unread is not None or "count" in snapshot:
            return _public("UNPARSEABLE", signal="chat-list")
        return _hold(directory, binding, pipeline, "UNREAD_DOT")
    if other != 0:
        return _public("SEVERAL_CHANGES", signal="chat-list")
    if mark == "unknown" or (mark is None and unread is None):
        return _hold(directory, binding, pipeline, "UNREAD_UNKNOWN")
    if mark == "ambiguous":
        return _hold(directory, binding, pipeline, "UNREAD_AMBIGUOUS")
    if unread is None:
        return _hold(directory, binding, pipeline, "UNREAD_UNKNOWN")
    state = _load_list(directory, binding["localScopeId"])
    if state["counted"] or state["mark"] in {"absent", "dot", "count"}:
        return _public("NOT_A_WAKE", signal="chat-list")
    if not state["baseline"]:
        _save_list(directory, binding["localScopeId"], position, unread)
        return _public("BASELINE", signal="chat-list")
    if unread and not state["unread"]:
        posted, event_id = _post(pipeline, allowlist, LIST_REPLACES)
        if not posted:
            return _public("WAKE_NOT_ACKED", signal="chat-list", posted=True)
        _save_list(directory, binding["localScopeId"], position, True)
        draft = _draft(event_id, binding["localScopeId"])
        draft["source"] = "web-page-change"
        draft["signal"] = "chat-list"
        draft["readsChat"] = False
        _append_draft(directory, draft)
        return _public("ONE_UNREAD", signal="chat-list", posted=True, draft=True)
    if position != state["position"] or unread != state["unread"]:
        _save_list(directory, binding["localScopeId"], position, unread)
        if not unread and state["unread"]:
            return _public("READ_CLEARED", signal="chat-list")
        if unread and state["unread"]:
            return _public("ALREADY_UNREAD", signal="chat-list")
        return _public("REORDER_ONLY", signal="chat-list")
    return _public("NO_NEW", signal="chat-list")


def _list_fields(snapshot):
    matches = snapshot.get("matches")
    other = snapshot.get("otherChanges")
    position = snapshot.get("position")
    unread = snapshot.get("unread")
    if "unread" not in snapshot:
        return None
    if _bad_count(matches) or _bad_count(other):
        return None
    if matches != 1:
        return matches, 0, False, other
    if _bad_count(position):
        return None
    if unread is None:
        return matches, position, None, other
    if not isinstance(unread, bool):
        return None
    return matches, position, unread, other


def _bad_count(value) -> bool:
    return isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10000


def _scope_ok(directory: Path, allowlist: str) -> bool:
    binding = load_binding(directory)
    if binding is None or not valid_label(allowlist):
        return False
    return binding["visibleHeader"] == allowlist


def _scope_block(directory: Path, signal: str = "open-tail") -> dict:
    if load_binding(directory) is None:
        return _public("NOT_BOUND", signal=signal)
    return _public("SCOPE_MISMATCH", signal=signal)


def _good_count(value, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    if positive:
        return 1 <= value <= COUNT_MAX
    return 0 <= value <= COUNT_MAX


def _apply_count(directory: Path, binding: dict, pipeline, position: int, count: int) -> dict:
    state = _load_list(directory, binding["localScopeId"])
    at = iso(pipeline.outbox.clock.now())
    scope_id = binding["localScopeId"]
    if not state["counted"]:
        _save_count(directory, scope_id, position, count, 0)
        return _attach_last(
            pipeline,
            _sample("COUNT_BASELINE", count=count, stored=count, change="baseline", at=at),
        )
    previous = state["count"]
    generation = state["generation"]
    if count == previous:
        if position != state["position"]:
            _save_count(directory, scope_id, position, count, generation)
        return _attach_last(
            pipeline,
            _sample("NO_NEW", count=count, prior=previous, stored=count, change="same", at=at),
        )
    if count < previous:
        if _pending_hint(pipeline) is not None:
            return _attach_last(
                pipeline,
                _sample("COUNT_HELD", count=count, prior=previous, stored=previous, change="held", at=at),
            )
        _save_count(directory, scope_id, position, count, generation)
        if count == 0:
            return _attach_last(
                pipeline,
                _sample("COUNT_CLEARED", count=0, prior=previous, stored=0, change="clear", at=at),
            )
        return _attach_last(
            pipeline,
            _sample("COUNT_DOWN", count=count, prior=previous, stored=count, change="down", at=at),
        )
    if binding.get("mode") != "metadata":
        _save_count(directory, scope_id, position, count, generation)
        return _attach_last(
            pipeline,
            _sample("COUNT_UP", count=count, prior=previous, stored=count, change="up", at=at),
        )
    forwarded = _forward_count(pipeline, binding, previous, count, generation, at)
    if forwarded["forward"] == "accepted":
        _save_count(directory, scope_id, position, count, generation + 1)
        forwarded["stored"] = count
    else:
        forwarded["stored"] = previous
    return _attach_last(pipeline, forwarded)


def _forward_count(pipeline, binding: dict, previous: int, current: int, generation: int, at: str) -> dict:
    observation = Observation(
        app_name="",
        replaces_id=_count_replaces(previous, current, generation),
        summary=binding.get("visibleHeader") or "",
        origin="unread-hint",
    )
    result = pipeline.handle(observation)
    event = result.event_id or ""
    if result.disposition == "ignored" and result.reason == "DEBOUNCED":
        return _sample("COUNT_HELD", count=current, prior=previous, change="held", at=at)
    if result.disposition not in ("enqueued", "replaced") or not event:
        return _sample("COUNT_UP", count=current, prior=previous, change="up", forward="error", event=event, at=at)
    pipeline.flush()
    item = pipeline.outbox.items.get(event)
    view = _forward_view(item)
    return _sample(
        "COUNT_UP",
        count=current,
        prior=previous,
        change="up",
        posted=view["posted"],
        forward=view["forward"],
        event=view["event"],
        at=at,
    )


def _count_replaces(previous: int, current: int, generation: int) -> int:
    raw = f"unread-indicator-hint:count:{previous}:{current}:{generation}".encode("ascii")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") or 1


def _hold(directory: Path, binding: dict, pipeline, disposition: str) -> dict:
    state = _load_list(directory, binding["localScopeId"])
    at = iso(pipeline.outbox.clock.now())
    stored = state["count"] if state["counted"] else None
    return _attach_last(pipeline, _sample(disposition, stored=stored, change="held", at=at))


def _sample(
    disposition: str,
    *,
    count=None,
    prior=None,
    stored=None,
    change: str = "",
    posted: bool = False,
    forward: str = "none",
    event: str = "",
    at: str = "",
) -> dict:
    public = _public(disposition, signal="chat-list", posted=posted, forward=forward, event=event)
    if change:
        public["change"] = change
    if count is not None:
        public["count"] = count
    if prior is not None:
        public["prior"] = prior
    if stored is not None:
        public["stored"] = stored
    if at:
        public["at"] = at
    return public


def _attach_last(pipeline, public: dict) -> dict:
    item = _latest_hint(pipeline)
    if item is None:
        return public
    view = _forward_view(item)
    event = view["event"]
    if not event or event == public.get("event"):
        return public
    public["lastForward"] = view["forward"]
    public["lastEvent"] = event
    stamp = item.acked_at if item.acked_at is not None else item.updated_at
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        public["lastAt"] = iso(stamp)
    return public


def _pending_hint(pipeline):
    rows = [
        item
        for item in pipeline.outbox.items.values()
        if item.source == "unread-indicator-hint" and item.state in ("pending", "retryable", "in_flight")
    ]
    return rows[0] if rows else None


def _latest_hint(pipeline):
    rows = [item for item in pipeline.outbox.items.values() if item.source == "unread-indicator-hint"]
    if not rows:
        return None
    return max(rows, key=lambda item: item.updated_at or 0)


def _forward_view(item) -> dict:
    if item is None:
        return {"forward": "error", "event": "", "posted": False}
    event = item.event_id if isinstance(item.event_id, str) else ""
    if item.state == "acked":
        return {"forward": "accepted", "event": event, "posted": True}
    if item.state in ("pending", "retryable", "in_flight"):
        return {"forward": "attempted", "event": event, "posted": False}
    return {"forward": "error", "event": event, "posted": False}


def _post(pipeline, allowlist: str, replaces: int) -> tuple:
    observation = Observation(
        app_name="",
        replaces_id=replaces,
        summary=allowlist,
        origin="web-page",
    )
    result = pipeline.handle(observation)
    if result.event_id is None or result.disposition not in ("enqueued", "replaced"):
        return False, None
    pipeline.flush()
    item = pipeline.outbox.items.get(result.event_id)
    if item is None or item.state != "acked":
        return False, result.event_id
    return True, result.event_id


def _load_list(directory: Path, scope_id: str) -> dict:
    path = Path(directory) / LIST_NAME
    empty = {
        "scopeId": scope_id,
        "baseline": False,
        "position": 0,
        "unread": False,
        "mark": "",
        "count": None,
        "counted": False,
        "generation": 0,
    }
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict) or data.get("scopeId") != scope_id or data.get("baseline") is not True:
        return empty
    position = data.get("position")
    unread = data.get("unread")
    mark = data.get("mark", "")
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        return empty
    if not isinstance(unread, bool):
        return empty
    if mark not in {"", "absent", "dot", "count"}:
        return empty
    counted = data.get("counted") is True
    generation = data.get("generation", 0)
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0 or generation > 1_000_000:
        return empty
    count = data.get("count")
    if counted:
        if not _good_count(count):
            return empty
    else:
        count = None
    return {
        "scopeId": scope_id,
        "baseline": True,
        "position": position,
        "unread": unread,
        "mark": mark,
        "count": count,
        "counted": counted,
        "generation": generation,
    }


def _save_count(directory: Path, scope_id: str, position: int, count: int, generation: int) -> None:
    _write(
        Path(directory) / LIST_NAME,
        {
            "scopeId": scope_id,
            "baseline": True,
            "position": position,
            "unread": False,
            "mark": "absent" if count == 0 else "count",
            "count": count,
            "counted": True,
            "generation": generation,
        },
    )


def _save_list(directory: Path, scope_id: str, position: int, unread: bool, mark: str = "") -> None:
    payload = {"scopeId": scope_id, "baseline": True, "position": position, "unread": unread}
    if mark in {"absent", "dot"}:
        payload["mark"] = mark
    _write(Path(directory) / LIST_NAME, payload)


def _public(
    disposition: str,
    *,
    signal: str = "",
    posted: bool = False,
    draft: bool = False,
    forward: str = "none",
    event: str = "",
) -> dict:
    if forward not in {"none", "attempted", "accepted", "error"}:
        forward = "none"
    if not isinstance(event, str):
        event = ""
    return {
        "disposition": disposition,
        "signal": signal,
        "posted": posted,
        "draft": draft,
        "forward": forward,
        "event": event,
        "verifiedRemoteRecipient": False,
        "liveWhatsApp": False,
        "sendsWhatsApp": False,
    }


# Re-exported so a caller can bind before the first snapshot without importing read.
prepare_binding = bind_local
