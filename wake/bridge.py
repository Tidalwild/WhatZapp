"""Continuous page-change receiver for the extension's native-messaging host.

Chrome starts this process and speaks length-prefixed JSON on stdin and
stdout. The only accepted page message is the sanitized chat-list contract.
Message text, previews, and other chats' names are not stored or logged.
"""

import json
import os
import re
import time
from pathlib import Path

from wake.composer import note_sample
from wake.approval import approve, decide, mark_ambiguous, pause, revoke
from wake.config import load_config, transmission_ready
from wake.context import enable as enable_context
from wake.context import revoke as revoke_context
from wake.trace import note_read
from wake.lifecycle import outbox_stopped, stop_requested
from wake.listchange import apply_list_change
from wake.pane import apply_pane_hint
from wake.page import apply_page
from wake.persons import apply_person_hint
from wake.policy import valid_label
from wake.resolve import take_permit, touch_session
from wake.read import bind_metadata, load_binding
from wake.routine import DEFAULT_STORE

HOST_NAME = "com.draft_bridge.wake"
HANDSHAKE_NAME = "handshake.json"
HOST_STATE_NAME = "host.json"
MAX_FRAME = 1024
_RECENT_LIMIT = 8
_CODE = re.compile(r"[A-Z_]{1,40}")
_WORD = re.compile(r"pending|none|[A-Z_]{1,40}")
_DETAIL = re.compile(r"[A-Za-z0-9-]{1,40}")
_HOST_PHASE = frozenset({"listening", "exited"})
_HOST_CAUSE = frozenset({"none", "HOST_EXITED", "HOST_CRASH", "STORE_IGNORED"})
_HELLO = frozenset({"v", "kind"})
_OFFER = frozenset({"v", "kind", "label"})
_LIST = frozenset({"v", "kind", "layout", "boundLabel", "matches", "position", "unread", "mark", "count", "otherChanges"})
_PERSON = frozenset({"v", "kind", "chatRef", "mark", "count"})
_LIST_CHANGE = frozenset({"v", "kind", "mark", "count"})
_PANE = frozenset({"v", "kind", "generation"})
_COMPOSER = frozenset({"v", "kind", "state", "event"})
_CONTEXT = frozenset({"v", "kind", "action", "scope"})
_APPROVAL = frozenset({"v", "kind", "action", "scope", "event", "digest"})
_APPROVAL_BARE = frozenset({"v", "kind", "action"})
_READ_NOTE = frozenset({"v", "kind", "event"})
_APPROVAL_ACTIONS = frozenset({"approve", "pause", "revoke", "ambiguous", "decide"})
_CHANGES = frozenset({"baseline", "up", "down", "clear", "same", "held"})
_WHEN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class Outcome:
    def __init__(
        self,
        disposition: str,
        posted: bool = False,
        rescope: bool = False,
        forward: str = "none",
        event: str = "",
        count=None,
        prior=None,
        stored=None,
        change: str = "",
        at: str = "",
        last_forward: str = "none",
        last_event: str = "",
        last_at: str = "",
        reply: dict | None = None,
    ) -> None:
        self.disposition = disposition if _CODE.fullmatch(disposition or "") else "UNREADABLE"
        self.posted = bool(posted)
        self.rescope = bool(rescope)
        self.forward = forward if forward in {"none", "attempted", "accepted", "error"} else "none"
        self.event = event if isinstance(event, str) else ""
        self.count = count if _small_count(count) else None
        self.prior = prior if _small_count(prior) else None
        self.stored = stored if _small_count(stored) else None
        self.change = change if change in _CHANGES else ""
        self.at = at if isinstance(at, str) and _WHEN.fullmatch(at) else ""
        self.last_forward = last_forward if last_forward in {"attempted", "accepted", "error"} else "none"
        self.last_event = last_event if isinstance(last_event, str) else ""
        self.last_at = last_at if isinstance(last_at, str) and _WHEN.fullmatch(last_at) else ""
        self.reply = reply if isinstance(reply, dict) else None


def open_store(env: dict) -> tuple:
    raw = env.get("WHATSAPP_WAKE_STORE") or ""
    if not raw:
        return DEFAULT_STORE, "none"
    path = Path(raw)
    if not path.is_absolute():
        return DEFAULT_STORE, "STORE_IGNORED"
    return path, "none"


def store_path(env: dict) -> Path:
    path, _cause = open_store(env)
    return path


def run_stdio(env: dict, stdin, stdout, pipeline) -> int:
    config = load_config(env)
    store, store_cause = open_store(env)
    Path(store).mkdir(parents=True, exist_ok=True)
    note_host(store, "listening", store_cause, "relative" if store_cause == "STORE_IGNORED" else "none")
    mark_pending(store)
    seen_hello = False
    try:
        write_frame(stdout, scope_message(store, config))
        while True:
            incoming = read_frame(stdin)
            if incoming is None:
                if seen_hello:
                    note_host(store, "exited", store_cause, "stdin-closed")
                else:
                    note_host(store, "exited", "HOST_EXITED", "closed-before-hello")
                return 0
            if incoming.get("error"):
                code = incoming["error"] if incoming["error"] in {"OVERSIZE", "SHORT", "UNPARSEABLE"} else "UNPARSEABLE"
                _trace(env, code)
                write_frame(stdout, ack(code, False))
                if code == "SHORT":
                    note_host(store, "exited", "HOST_EXITED", "short-frame")
                    return 1
                continue
            value = incoming["value"]
            if isinstance(value, dict) and value.get("kind") == "hello":
                seen_hello = True
            outcome = accept(store, config, pipeline, value)
            note_handshake(store, value, outcome)
            if outcome.rescope:
                write_frame(stdout, scope_message(store, config))
            _trace(env, outcome.disposition)
            write_frame(stdout, ack_for(outcome))
    except BrokenPipeError:
        note_host(store, "exited", "HOST_EXITED" if not seen_hello else store_cause, "broken-pipe")
        return 0
    except Exception as exc:
        name = type(exc).__name__
        note_host(store, "exited", "HOST_CRASH", name if _DETAIL.fullmatch(name or "") else "Error")
        raise


def accept(store: Path, config, pipeline, value) -> Outcome:
    if not isinstance(value, dict):
        return Outcome("UNPARSEABLE")
    kind = value.get("kind")
    if kind == "hello":
        if value.get("v") != 1 or set(value) - _HELLO:
            return Outcome("UNTRUSTED_FIELD")
        return Outcome("READY", rescope=True)
    if kind == "scope-offer":
        return offer_scope(store, config, value)
    if kind == "take-permit":
        return take_open_permit(store, value)
    if kind == "person-hint":
        return accept_person(store, config, pipeline, value)
    if kind == "list-change":
        return accept_list_change(store, config, pipeline, value)
    if kind == "pane-hint":
        return accept_pane(store, config, pipeline, value)
    if kind == "composer-sample":
        return accept_composer(store, pipeline, value)
    if kind == "context-policy":
        return accept_context(store, pipeline, value)
    if kind == "approval-note":
        return accept_approval(store, pipeline, value)
    if kind == "read-note":
        return accept_read_note(store, pipeline, value)
    if config.wire == "list" and kind == "list-signal":
        return Outcome("SCHEMA_HELD")
    if kind != "list-signal" or value.get("v") != 1 or set(value) - _LIST:
        return Outcome("UNTRUSTED_FIELD")
    if not config.enabled:
        return Outcome("DISABLED")
    if not transmission_ready(config):
        return Outcome("BLOCKED")
    if stop_requested(store) or outbox_stopped(store):
        return Outcome("STOPPED")
    if pipeline.outbox.stopped:
        pipeline.resume()
    snapshot = {
        "layout": value.get("layout"),
        "boundLabel": value.get("boundLabel"),
        "matches": value.get("matches"),
        "position": value.get("position"),
        "unread": value.get("unread"),
        "otherChanges": value.get("otherChanges"),
    }
    if "mark" in value:
        snapshot["mark"] = value.get("mark")
    if "count" in value:
        snapshot["count"] = value.get("count")
    result = apply_page(store, snapshot, allowlist=config.label, pipeline=pipeline)
    return Outcome(
        str(result["disposition"]),
        bool(result["posted"]),
        forward=str(result.get("forward") or "none"),
        event=str(result.get("event") or ""),
        count=result.get("count"),
        prior=result.get("prior"),
        stored=result.get("stored"),
        change=str(result.get("change") or ""),
        at=str(result.get("at") or ""),
        last_forward=str(result.get("lastForward") or "none"),
        last_event=str(result.get("lastEvent") or ""),
        last_at=str(result.get("lastAt") or ""),
    )


def accept_person(store: Path, config, pipeline, value) -> Outcome:
    if value.get("v") != 2 or set(value) - _PERSON:
        return Outcome("UNTRUSTED_FIELD")
    hint = {"chatRef": value.get("chatRef"), "mark": value.get("mark")}
    if "count" in value:
        hint["count"] = value.get("count")
    if config.wire == "v2":
        if not config.enabled:
            return Outcome("DISABLED")
        if not transmission_ready(config):
            return Outcome("BLOCKED")
        if stop_requested(store) or outbox_stopped(store):
            return Outcome("STOPPED")
    result = apply_person_hint(store, hint, pipeline=pipeline, wire=config.wire)
    if result.get("disposition") != "UNPARSEABLE" and isinstance(result.get("chatRef"), str):
        touch_session(store, result["chatRef"], time.time())
    return Outcome(str(result["disposition"]), bool(result.get("posted")), event=str(result.get("event") or ""))


def accept_list_change(store: Path, config, pipeline, value) -> Outcome:
    if value.get("v") != 3 or set(value) - _LIST_CHANGE:
        return Outcome("UNTRUSTED_FIELD")
    hint = {"mark": value.get("mark")}
    if "count" in value:
        hint["count"] = value.get("count")
    if config.wire == "list":
        if not config.enabled:
            return Outcome("DISABLED")
        if not transmission_ready(config):
            return Outcome("BLOCKED")
        if stop_requested(store) or outbox_stopped(store):
            return Outcome("STOPPED")
    result = apply_list_change(store, hint, pipeline=pipeline, wire=config.wire)
    return Outcome(str(result["disposition"]), bool(result.get("posted")), event=str(result.get("event") or ""))


def accept_pane(store: Path, config, pipeline, value) -> Outcome:
    if value.get("v") != 3 or set(value) - _PANE:
        return Outcome("UNTRUSTED_FIELD")
    hint = {"generation": value.get("generation")}
    if config.wire == "list":
        if not config.enabled:
            return Outcome("DISABLED")
        if not transmission_ready(config):
            return Outcome("BLOCKED")
        if stop_requested(store) or outbox_stopped(store):
            return Outcome("STOPPED")
    result = apply_pane_hint(store, hint, pipeline=pipeline, wire=config.wire)
    return Outcome(str(result["disposition"]), bool(result.get("posted")), event=str(result.get("event") or ""))


def accept_composer(store: Path, pipeline, value) -> Outcome:
    """Record a textbox state. Extra fields, including any body, are refused."""

    if value.get("v") != 1 or set(value) - _COMPOSER or "state" not in value:
        return Outcome("UNTRUSTED_FIELD")
    event = value.get("event", "")
    if not isinstance(event, str):
        return Outcome("UNPARSEABLE")
    noted = note_sample(store, value.get("state"), event, pipeline.outbox.clock.now())
    if noted == "NOTED":
        return Outcome("COMPOSER_NOTED")
    if noted == "UNREADABLE":
        return Outcome("UNREADABLE")
    return Outcome("UNPARSEABLE")


def accept_context(store: Path, pipeline, value) -> Outcome:
    """Operator opt-in only. Fact text and message text are refused."""

    if value.get("v") != 1 or set(value) - _CONTEXT:
        return Outcome("UNTRUSTED_FIELD")
    action = value.get("action")
    scope = value.get("scope")
    if not isinstance(action, str) or not isinstance(scope, str):
        return Outcome("UNPARSEABLE")
    now = pipeline.outbox.clock.now()
    if action == "enable":
        result = enable_context(store, scope, now)
    elif action == "revoke":
        result = revoke_context(store, scope, now)
    else:
        return Outcome("UNPARSEABLE")
    if result in {"ENABLED", "REVOKED"}:
        return Outcome("CONTEXT_NOTED")
    if result == "UNREADABLE":
        return Outcome("UNREADABLE")
    if result == "ABSENT":
        return Outcome("CONTEXT_ABSENT")
    return Outcome("UNPARSEABLE")


def accept_approval(store: Path, pipeline, value) -> Outcome:
    """Store a digest. The reply text is not accepted on this frame."""

    action = value.get("action")
    if action not in _APPROVAL_ACTIONS or value.get("v") != 1:
        return Outcome("UNPARSEABLE")
    bare = action in {"pause", "revoke", "ambiguous"}
    if set(value) - (_APPROVAL_BARE if bare else _APPROVAL):
        return Outcome("UNTRUSTED_FIELD")
    if not bare and ("digest" not in value or "scope" not in value or "event" not in value):
        return Outcome("UNPARSEABLE")
    now = pipeline.outbox.clock.now()
    if action == "pause":
        result = pause(store)
    elif action == "revoke":
        result = revoke(store)
    elif action == "ambiguous":
        result = mark_ambiguous(store)
    elif action == "decide":
        result = decide(store, value.get("digest"), value.get("scope"), value.get("event"), now)
    else:
        result = approve(store, value.get("digest"), value.get("scope"), value.get("event"), now)
    if result == "UNREADABLE":
        return Outcome("UNREADABLE")
    if result in {"UNPARSEABLE", "ABSENT", "NONE"}:
        return Outcome("UNPARSEABLE")
    return Outcome(result if _CODE.fullmatch(result or "") else "UNPARSEABLE")


def accept_read_note(store: Path, pipeline, value) -> Outcome:
    """A read happened. The frame has no message text and does not cover a wake."""

    if value.get("v") != 1 or set(value) - _READ_NOTE:
        return Outcome("UNTRUSTED_FIELD")
    event = value.get("event", "")
    if not isinstance(event, str):
        return Outcome("UNPARSEABLE")
    noted = note_read(store, event, pipeline.outbox.clock.now())
    if noted == "NOTED":
        return Outcome("READ_NOTED")
    if noted == "UNREADABLE":
        return Outcome("UNREADABLE")
    return Outcome("UNPARSEABLE")


def take_open_permit(store: Path, value) -> Outcome:
    if value.get("v") != 2 or set(value) - {"v", "kind"}:
        return Outcome("UNTRUSTED_FIELD")
    permit = take_permit(store, time.time())
    if permit is None:
        reply = {"v": 2, "kind": "permit", "disposition": "NONE"}
    else:
        reply = {
            "v": 2,
            "kind": "permit",
            "disposition": "READY",
            "chatRef": permit["chatRef"],
            "event": permit["eventId"],
        }
    return Outcome("PERMIT", reply=reply)


def offer_scope(store: Path, config, value) -> Outcome:
    if value.get("v") != 1 or set(value) - _OFFER:
        return Outcome("UNTRUSTED_FIELD")
    label = value.get("label")
    if not valid_label(config.label) or label != config.label:
        return Outcome("SCOPE_MISMATCH")
    existing = load_binding(store)
    if existing is not None and existing.get("mode") == "messages":
        if existing.get("visibleHeader") == label:
            return Outcome("SCOPE", rescope=True)
        return Outcome("MODE_MISMATCH")
    _binding, reason = bind_metadata(store, str(label))
    if reason != "BOUND":
        return Outcome("HEADER_UNUSABLE")
    return Outcome("SCOPE", posted=False, rescope=True)


def mark_pending(store: Path) -> None:
    _write_json(Path(store) / HANDSHAKE_NAME, {"hello": "pending", "list": "none", "posted": False, "scope": "pending"})


def note_host(store: Path, phase: str, cause: str, detail: str) -> None:
    _write_json(
        Path(store) / HOST_STATE_NAME,
        _host_payload(phase, cause, detail),
    )


def _host_payload(phase: str, cause: str, detail: str) -> dict:
    payload = {
        "cause": cause if cause in _HOST_CAUSE else "HOST_CRASH",
        "detail": detail if _DETAIL.fullmatch(detail or "") else "none",
        "phase": phase if phase in _HOST_PHASE else "exited",
    }
    if payload["phase"] == "listening":
        payload["pid"] = os.getpid()
    return payload


def _bridge_pid_alive(pid: int) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    text = raw.replace(b"\x00", b" ")
    return b"wake" in text and b"bridge" in text


def read_host(store: Path) -> dict:
    empty = {"phase": "none", "cause": "none", "detail": "none", "live": "unverified"}
    data = _read_json(Path(store) / HOST_STATE_NAME)
    if not isinstance(data, dict):
        return empty
    phase = data.get("phase")
    cause = data.get("cause")
    detail = data.get("detail")
    phase = phase if phase in _HOST_PHASE else "none"
    cause = cause if cause in _HOST_CAUSE else "none"
    detail = detail if isinstance(detail, str) and _DETAIL.fullmatch(detail) else "none"
    live = "unverified"
    if phase == "listening":
        pid = data.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool):
            if _bridge_pid_alive(pid):
                live = "yes"
            else:
                phase = "stale"
                cause = "HOST_STALE"
                live = "no"
    return {"phase": phase, "cause": cause, "detail": detail, "live": live}


def note_handshake(store: Path, value, outcome: Outcome) -> None:
    if not isinstance(value, dict):
        return
    kind = value.get("kind")
    current = read_handshake(store)
    if kind == "hello" and outcome.disposition == "READY":
        current["hello"] = "READY"
    elif kind == "scope-offer":
        current["scope"] = outcome.disposition if _CODE.fullmatch(outcome.disposition or "") else "UNREADABLE"
    elif kind == "list-signal":
        code = outcome.disposition if _CODE.fullmatch(outcome.disposition or "") else "UNREADABLE"
        current["list"] = code
        recent = [item for item in current.get("listRecent", []) if isinstance(item, str) and _CODE.fullmatch(item)]
        if not recent or recent[-1] != code:
            recent.append(code)
        current["listRecent"] = recent[-_RECENT_LIMIT:]
        current["posted"] = bool(outcome.posted)
        current["forward"] = outcome.forward
        current["event"] = outcome.event if re.fullmatch(r"evt-[0-9a-f]{32}", outcome.event or "") else "none"
        if outcome.change:
            current["change"] = outcome.change
        if outcome.count is not None or outcome.change == "held":
            current["count"] = outcome.count
        if outcome.prior is not None:
            current["prior"] = outcome.prior
        if outcome.stored is not None:
            current["stored"] = outcome.stored
        if outcome.at:
            current["at"] = outcome.at
        if outcome.forward in {"attempted", "accepted", "error"} and re.fullmatch(r"evt-[0-9a-f]{32}", outcome.event or ""):
            current["lastForward"] = outcome.forward
            current["lastEvent"] = outcome.event
            current["lastAt"] = outcome.at or current.get("lastAt") or "none"
        elif re.fullmatch(r"evt-[0-9a-f]{32}", outcome.last_event or ""):
            current["lastForward"] = outcome.last_forward
            current["lastEvent"] = outcome.last_event
            current["lastAt"] = outcome.last_at or "none"
    else:
        return
    _write_json(Path(store) / HANDSHAKE_NAME, current)


def read_handshake(store: Path) -> dict:
    empty = {"hello": "none", "scope": "none", "list": "none", "posted": False}
    path = Path(store) / HANDSHAKE_NAME
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    found = dict(empty)
    for key in ("hello", "scope", "list"):
        value = data.get(key)
        found[key] = value if isinstance(value, str) and _WORD.fullmatch(value or "") else "none"
    found["posted"] = data.get("posted") is True
    forward = data.get("forward")
    found["forward"] = forward if forward in {"none", "attempted", "accepted", "error"} else "none"
    event = data.get("event")
    found["event"] = event if isinstance(event, str) and re.fullmatch(r"evt-[0-9a-f]{32}", event) else "none"
    change = data.get("change")
    found["change"] = change if change in _CHANGES else "none"
    found["count"] = data.get("count") if _small_count(data.get("count")) else None
    found["prior"] = data.get("prior") if _small_count(data.get("prior")) else None
    found["stored"] = data.get("stored") if _small_count(data.get("stored")) else None
    at = data.get("at")
    found["at"] = at if isinstance(at, str) and _WHEN.fullmatch(at) else "none"
    last_forward = data.get("lastForward")
    found["lastForward"] = last_forward if last_forward in {"attempted", "accepted", "error"} else "none"
    last_event = data.get("lastEvent")
    found["lastEvent"] = last_event if isinstance(last_event, str) and re.fullmatch(r"evt-[0-9a-f]{32}", last_event) else "none"
    last_at = data.get("lastAt")
    found["lastAt"] = last_at if isinstance(last_at, str) and _WHEN.fullmatch(last_at) else "none"
    raw_recent = data.get("listRecent")
    recent = []
    if isinstance(raw_recent, list):
        recent = [item for item in raw_recent if isinstance(item, str) and _CODE.fullmatch(item)][-_RECENT_LIMIT:]
    found["listRecent"] = recent
    return found


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def scope_message(store: Path, config) -> dict:
    label = ""
    binding = load_binding(store)
    if valid_label(config.label) and binding is not None and binding.get("visibleHeader") == config.label:
        label = config.label
    return {"v": 1, "kind": "scope", "label": label}


def read_frame(stream):
    header = _read_exact(stream, 4)
    if header is None:
        return None
    if len(header) < 4:
        return {"error": "SHORT"}
    length = int.from_bytes(header, "little")
    if length < 2 or length > 1_000_000:
        return {"error": "OVERSIZE"}
    body = _read_exact(stream, length)
    if body is None or len(body) != length:
        return {"error": "SHORT"}
    if length > MAX_FRAME:
        return {"error": "OVERSIZE"}
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {"error": "UNPARSEABLE"}
    if not isinstance(value, dict):
        return {"error": "UNPARSEABLE"}
    return {"value": value}


def write_frame(stream, payload: dict) -> None:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    stream.write(len(raw).to_bytes(4, "little") + raw)
    stream.flush()


def ack(disposition: str, posted: bool, forward: str = "none", event: str = "") -> dict:
    return ack_for(Outcome(disposition, posted, forward=forward, event=event))


def ack_for(outcome: Outcome) -> dict:
    if outcome.reply is not None:
        return outcome.reply
    payload = {"v": 1, "kind": "ack", "disposition": outcome.disposition, "posted": bool(outcome.posted)}
    if outcome.forward in {"attempted", "accepted", "error"}:
        payload["forward"] = outcome.forward
    if re.fullmatch(r"evt-[0-9a-f]{32}", outcome.event or ""):
        payload["event"] = outcome.event
    if outcome.count is not None:
        payload["count"] = outcome.count
    if outcome.prior is not None:
        payload["prior"] = outcome.prior
    if outcome.stored is not None:
        payload["stored"] = outcome.stored
    if outcome.change:
        payload["change"] = outcome.change
    if outcome.at:
        payload["at"] = outcome.at
    if re.fullmatch(r"evt-[0-9a-f]{32}", outcome.last_event or ""):
        payload["lastForward"] = outcome.last_forward
        payload["lastEvent"] = outcome.last_event
        if outcome.last_at:
            payload["lastAt"] = outcome.last_at
    return payload


def _small_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 9999


def _read_exact(stream, length: int):
    chunks = []
    remaining = length
    while remaining:
        chunk = stream.read(min(remaining, 65536))
        if not chunk:
            return b"".join(chunks) if chunks else None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _trace(env: dict, code: str) -> None:
    raw = env.get("WHATSAPP_WAKE_BRIDGE_TRACE") or ""
    if not raw:
        return
    path = Path(raw)
    if not path.is_absolute():
        return
    safe = code if _CODE.fullmatch(code or "") else "UNREADABLE"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(safe + "\n")
