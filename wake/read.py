"""One bound chat, read only after a real notification wake.

The snapshot is the probe contract: visible header, sender, text, and clock.
The header match checks that the open chat is the one that was bound. It does
not authenticate a remote recipient. Notification titles are not accepted as
that binding. A connectivity probe does not open a read.

The first valid snapshot is a baseline and produces no draft. A later snapshot
drafts only when exactly one new inbound row is unambiguous and a wake has
been acknowledged. A desktop notification, the Android listener, or a
``web-page-change`` event can supply that acknowledgement. A connectivity
probe cannot. Duplicate clocks, a weekday or locale clock, a repeated row,
or two new inbound rows produce a gap and no draft. Message text is not
written to the state or the draft.
"""

import hashlib
import json
import re
import uuid
from pathlib import Path

from wake.outbox import Outbox
from wake.policy import valid_label

CLOCK = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?[AP]M)?$", re.IGNORECASE)
NOTIFY_SOURCES = frozenset({"linux-session-notify", "android-listener", "web-page-change"})
BINDING_NAME = "binding.json"
WINDOW_NAME = "read-window.json"
DRAFTS_NAME = "read-drafts.json"
UNTRUSTED_FIELDS = frozenset({"title", "notificationTitle", "app_name", "appName", "body"})


def bind_local(directory: Path, header: str, self_label: str | None = None, *, mode: str = "messages") -> tuple:
    visible = _label(header)
    if visible is None:
        return None, "HEADER_UNUSABLE"
    if mode == "metadata":
        if self_label not in (None, ""):
            return None, "SELF_LABEL_UNUSABLE"
        if not valid_label(visible):
            return None, "HEADER_UNUSABLE"
        binding = _binding_record(visible, "", "metadata")
        return _store_binding(directory, binding)
    if mode != "messages":
        return None, "MODE_UNUSABLE"
    own = _label(self_label if self_label is not None else "")
    if own is None:
        return None, "SELF_LABEL_UNUSABLE"
    if visible == own:
        return None, "DIRECTION_UNUSABLE"
    binding = _binding_record(visible, own, "messages")
    return _store_binding(directory, binding)


def bind_metadata(directory: Path, header: str) -> tuple:
    return bind_local(directory, header, None, mode="metadata")


def _binding_record(visible: str, own: str, mode: str) -> dict:
    return {
        "localScopeId": "scope-" + uuid.uuid4().hex,
        "visibleHeader": visible,
        "selfLabel": own,
        "mode": mode,
        "verifiedRemoteRecipient": False,
        "confidence": "local-pilot-display-label",
    }


def _store_binding(directory: Path, binding: dict) -> tuple:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory / BINDING_NAME, binding)
    window = directory / WINDOW_NAME
    if window.exists():
        window.unlink()
    return binding, "BOUND"


def load_binding(directory: Path):
    path = Path(directory) / BINDING_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("verifiedRemoteRecipient") is not False:
        return None
    if data.get("confidence") != "local-pilot-display-label":
        return None
    mode = data.get("mode", "messages")
    visible = _label(data.get("visibleHeader"))
    if visible is None:
        return None
    if mode == "metadata":
        if data.get("selfLabel") not in ("", None):
            return None
        if not valid_label(visible):
            return None
        data["selfLabel"] = ""
        data["mode"] = "metadata"
    elif mode == "messages":
        if _label(data.get("selfLabel")) is None or visible == _label(data.get("selfLabel")):
            return None
        data["mode"] = "messages"
    else:
        return None
    scope = data.get("localScopeId")
    if not isinstance(scope, str) or not scope.startswith("scope-") or len(scope) > 80:
        return None
    return data


def preview_tail(directory: Path, snapshot) -> dict:
    """Classify the open chat. One new inbound row does not advance or draft."""

    directory = Path(directory)
    binding = load_binding(directory)
    if binding is None:
        return _gap("NOT_BOUND")
    window = _load_window(directory, binding["localScopeId"])
    if _untrusted(snapshot):
        return _gap("UNTRUSTED_FIELD")
    parsed = _parse(snapshot, binding)
    if not parsed["ok"]:
        return _gap(parsed["reason"])
    if not window["baseline"]:
        window["baseline"] = True
        window["fingerprints"] = parsed["fingerprints"]
        window["clocks"] = parsed["clocks"]
        _write(directory / WINDOW_NAME, window)
        return _result("BASELINE", None)
    if _reused_clock(parsed, window):
        return _gap("AMBIGUOUS_CLOCK")
    fresh, _overlap, gap = _align(window["fingerprints"], parsed["fingerprints"])
    if gap:
        return _gap("NO_OVERLAP")
    inbound = [row for row in parsed["rows"][-len(fresh) :] if row["direction"] == "in"] if fresh else []
    if len(inbound) > 1:
        return _gap("AMBIGUOUS_NEW")
    if len(inbound) == 0:
        if fresh:
            _advance(directory, window, parsed)
            return _result("CONTEXT_ONLY", None)
        return _result("NO_NEW", None)
    result = _result("ONE_INBOUND", None)
    result["candidate"] = True
    result["replaces"] = _replaces(inbound[0]["fingerprint"])
    return result


def read_snapshot(directory: Path, snapshot, outbox: Outbox, event_id: str | None = None) -> dict:
    preview = preview_tail(directory, snapshot)
    if not preview.get("candidate"):
        return preview
    binding = load_binding(directory)
    if binding is None:
        return _gap("NOT_BOUND")
    permit = notification_permit(outbox, event_id)
    if permit is None:
        return _gap("NO_WAKE")
    if _already_drafted(directory, permit.event_id):
        return _gap("ALREADY_DRAFTED")
    parsed = _parse(snapshot, binding)
    if not parsed["ok"]:
        return _gap(parsed["reason"])
    record = _record(permit.event_id, binding["localScopeId"], permit.reason or "")
    _advance(directory, _load_window(directory, binding["localScopeId"]), parsed)
    _append_draft(directory, record)
    mock = record.get("handler") == "local-mock-handler"
    return _result("ONE_INBOUND", record if mock else None, "" if mock else str(record.get("kind") or ""))


def notification_permit(outbox: Outbox, event_id: str | None = None):
    if outbox.blocked:
        return None
    chosen = None
    for item in outbox.items.values():
        if item.state != "acked" or item.source not in NOTIFY_SOURCES:
            continue
        if event_id is not None and item.event_id != event_id:
            continue
        if chosen is None or (item.acked_at or 0) >= (chosen.acked_at or 0):
            chosen = item
    return chosen


def _parse(snapshot, binding) -> dict:
    if not isinstance(snapshot, dict):
        return {"ok": False, "reason": "UNRECOGNIZED"}
    if snapshot.get("layout") != "probe-contract":
        return {"ok": False, "reason": "UNRECOGNIZED"}
    if binding.get("mode") == "metadata" or not binding.get("selfLabel"):
        return {"ok": False, "reason": "DIRECTION_UNPROVEN"}
    header = snapshot.get("header")
    if not isinstance(header, str) or header != binding["visibleHeader"]:
        return {"ok": False, "reason": "CHAT_SWITCH"}
    phase = snapshot.get("phase")
    if phase in ("loading", "empty"):
        return {"ok": False, "reason": "LOAD_EMPTY"}
    if phase != "ready":
        return {"ok": False, "reason": "UNRECOGNIZED"}
    slots = snapshot.get("slots")
    if not isinstance(slots, list):
        return {"ok": False, "reason": "UNPARSEABLE"}
    rows = []
    seen = set()
    clocks = set()
    for slot in slots:
        if not isinstance(slot, dict):
            return {"ok": False, "reason": "UNPARSEABLE"}
        kind = slot.get("kind")
        if kind in ("separator", "header-echo"):
            continue
        if kind == "bad-time":
            return {"ok": False, "reason": "TIME_AMBIGUOUS"}
        if kind == "empty-body":
            return {"ok": False, "reason": "EMPTY_BODY"}
        if kind != "message":
            return {"ok": False, "reason": "UNPARSEABLE"}
        sender = slot.get("sender")
        text = slot.get("text")
        clock = slot.get("timeText")
        if not isinstance(sender, str) or not isinstance(text, str) or not isinstance(clock, str):
            return {"ok": False, "reason": "UNPARSEABLE"}
        if sender == "" or text == "":
            return {"ok": False, "reason": "EMPTY_BODY"}
        if CLOCK.fullmatch(clock.strip()) is None:
            return {"ok": False, "reason": "TIME_AMBIGUOUS"}
        clock = clock.strip()
        if sender == binding["selfLabel"]:
            direction = "out"
        elif sender == binding["visibleHeader"]:
            direction = "in"
        else:
            return {"ok": False, "reason": "AMBIGUOUS_DIRECTION"}
        fingerprint = _hash("\n".join((sender, clock, text)))
        clock_key = _hash(sender + "\n" + clock)
        if fingerprint in seen:
            return {"ok": False, "reason": "AMBIGUOUS_REPEAT"}
        if clock_key in clocks:
            return {"ok": False, "reason": "AMBIGUOUS_CLOCK"}
        seen.add(fingerprint)
        clocks.add(clock_key)
        rows.append({"direction": direction, "fingerprint": fingerprint, "clock": clock_key})
    if not rows:
        return {"ok": False, "reason": "UNPARSEABLE"}
    return {
        "ok": True,
        "rows": rows,
        "fingerprints": [row["fingerprint"] for row in rows],
        "clocks": [row["clock"] for row in rows],
    }


def _reused_clock(parsed, window) -> bool:
    previous = set(window.get("fingerprints") or [])
    known = set(window.get("clocks") or [])
    for row in parsed["rows"]:
        if row["clock"] in known and row["fingerprint"] not in previous:
            return True
    return False


def _align(previous: list, snapshot: list):
    if not snapshot:
        return [], 0, False
    if not previous:
        return list(snapshot), 0, False
    overlap = min(len(previous), len(snapshot))
    while overlap > 0 and previous[-overlap:] != snapshot[:overlap]:
        overlap -= 1
    if overlap > 0:
        return snapshot[overlap:], overlap, False
    if _contains(previous, snapshot):
        return [], len(snapshot), False
    return list(snapshot), 0, True


def _contains(haystack: list, needle: list) -> bool:
    if not needle:
        return True
    if len(needle) > len(haystack):
        return False
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start : start + len(needle)] == needle:
            return True
    return False


def _advance(directory, window, parsed) -> None:
    window["fingerprints"] = _tail(window["fingerprints"] + parsed["fingerprints"][-_fresh_count(window, parsed) :], 40)
    known = list(window.get("clocks") or [])
    for clock in parsed["clocks"]:
        if clock not in known:
            known.append(clock)
    window["clocks"] = known[-40:]
    _write(Path(directory) / WINDOW_NAME, window)


def _fresh_count(window, parsed) -> int:
    fresh, _overlap, gap = _align(window["fingerprints"], parsed["fingerprints"])
    if gap:
        return 0
    return len(fresh)


def _tail(values: list, limit: int) -> list:
    if len(values) <= limit:
        return values
    return values[-limit:]


def _load_window(directory: Path, scope_id: str) -> dict:
    path = Path(directory) / WINDOW_NAME
    empty = {"scopeId": scope_id, "baseline": False, "fingerprints": [], "clocks": []}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict) or data.get("scopeId") != scope_id:
        return empty
    if data.get("baseline") is not True:
        return empty
    fingerprints = data.get("fingerprints")
    clocks = data.get("clocks")
    if not isinstance(fingerprints, list) or not isinstance(clocks, list):
        return empty
    if any(not isinstance(item, str) for item in fingerprints + clocks):
        return empty
    return {
        "scopeId": scope_id,
        "baseline": True,
        "fingerprints": fingerprints,
        "clocks": clocks,
    }


def _already_drafted(directory: Path, event_id: str) -> bool:
    path = Path(directory) / DRAFTS_NAME
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    drafts = data.get("drafts") if isinstance(data, dict) else None
    if not isinstance(drafts, list):
        return True
    return any(isinstance(item, dict) and item.get("eventId") == event_id for item in drafts)


def _append_draft(directory: Path, draft: dict) -> None:
    path = Path(directory) / DRAFTS_NAME
    current = {"drafts": []}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("drafts"), list):
                current = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            current = {"drafts": []}
    current["drafts"].append(draft)
    _write(path, current)


def _record(event_id: str, scope_id: str, reason: str) -> dict:
    """Remember that this wake was consumed.

    The labelled mock is only for the local test-receipt reason ``acked``.
    An official transport acknowledgement is not a reply.
    """

    if reason == "acked":
        return _draft(event_id, scope_id)
    kind = reason if reason in ("transport-accepted", "legacy-409") else "noted"
    return {
        "eventId": event_id,
        "scopeId": scope_id,
        "kind": kind,
        "sent": False,
        "sendingEnabled": False,
        "verifiedRemoteRecipient": False,
        "liveWhatsApp": False,
        "source": "supplied-snapshot",
        "readsChat": False,
        "sendsWhatsApp": False,
    }


def _draft(event_id: str, scope_id: str) -> dict:
    return {
        "eventId": event_id,
        "scopeId": scope_id,
        "handler": "local-mock-handler",
        "placeholder": "LOCAL MOCK",
        "sendingEnabled": False,
        "sent": False,
        "verifiedRemoteRecipient": False,
        "liveWhatsApp": False,
        "source": "supplied-snapshot",
        "sendsWhatsApp": False,
    }


def _result(disposition: str, draft, ack: str = "") -> dict:
    return {
        "disposition": disposition,
        "draft": draft is not None,
        "ack": ack,
        "verifiedRemoteRecipient": False,
        "liveWhatsApp": False,
        "sendsWhatsApp": False,
    }


def _gap(reason: str) -> dict:
    row = _result(reason, None)
    row["draft"] = False
    return row


def _untrusted(snapshot) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return any(field in snapshot for field in UNTRUSTED_FIELDS)


def _label(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 80:
        return None
    if any(ord(char) < 32 for char in text):
        return None
    if "://" in text or "http:" in text.lower():
        return None
    return text


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _replaces(fingerprint: str) -> int:
    return int.from_bytes(hashlib.sha256(fingerprint.encode("utf-8")).digest()[:4], "big") or 1


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
