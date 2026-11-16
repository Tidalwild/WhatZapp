"""Send approval that does not send.

A matching approval means the exact digest, scope, and event are still
inside the expiry and are not paused. The package send arm stays off, so
the decision is ``SEND_DISARMED``. An ambiguous attempt stays held and is
not replaced by another approval. The reply text is never stored.
"""

import json
import os
import re
from pathlib import Path

NAME = "approval.json"
FORMAT = "wake-approval-1"
DEFAULT_TTL = 15 * 60
_SCOPE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
_EVENT = re.compile(r"^evt-[0-9a-f]{32}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PHASES = frozenset({"none", "approved", "ambiguous", "failed"})


def approve(directory: Path, digest: str, scope: str, event: str, now, ttl: int = DEFAULT_TTL) -> str:
    if not _digest(digest) or not _scope(scope) or not _event(event):
        return "UNPARSEABLE"
    stamp = _seconds(now)
    if stamp is None or isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 60 or ttl > 60 * 60:
        return "UNPARSEABLE"
    current = load(directory)
    if current is not None and current["phase"] == "ambiguous":
        return "AMBIGUOUS_HOLD"
    payload = {
        "format": FORMAT,
        "phase": "approved",
        "digest": digest,
        "scope": scope,
        "event": event,
        "approvedAt": stamp,
        "expiresAt": stamp + ttl,
        "paused": False,
    }
    return "APPROVED_NOT_SENT" if _save(directory, payload) else "UNREADABLE"


def pause(directory: Path) -> str:
    current = load(directory)
    if current is None:
        return "ABSENT"
    if current["phase"] == "none":
        return "NONE"
    payload = dict(current)
    payload["paused"] = True
    return "PAUSED" if _save(directory, payload) else "UNREADABLE"


def revoke(directory: Path) -> str:
    path = Path(directory) / NAME
    if os.path.lexists(path) and os.path.islink(path):
        return "UNREADABLE"
    if not os.path.lexists(path):
        return "ABSENT"
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        return "UNREADABLE"
    return "REVOKED"


def mark_ambiguous(directory: Path) -> str:
    current = load(directory)
    if current is None or current["phase"] == "none":
        return "NONE"
    payload = dict(current)
    payload["phase"] = "ambiguous"
    payload["paused"] = True
    return "AMBIGUOUS" if _save(directory, payload) else "UNREADABLE"


def decide(directory: Path, digest: str, scope: str, event: str, now) -> str:
    """Return a refusal or ``SEND_DISARMED``. Never an instruction to send."""

    current = load(directory)
    if current is None:
        path = Path(directory) / NAME
        if os.path.lexists(path):
            return "UNREADABLE"
        return "AWAITING"
    if current["phase"] == "ambiguous":
        return "AMBIGUOUS_HOLD"
    if current["phase"] != "approved":
        return "AWAITING"
    if current["paused"]:
        return "PAUSED"
    stamp = _seconds(now)
    if stamp is None or stamp >= current["expiresAt"]:
        return "EXPIRED"
    if digest != current["digest"]:
        return "DIGEST_MISMATCH"
    if scope != current["scope"]:
        return "SCOPE_MISMATCH"
    if event != current["event"]:
        return "EVENT_MISMATCH"
    return "SEND_DISARMED"


def line(directory: Path, now) -> str:
    current = load(directory)
    path = Path(directory) / NAME
    if current is None:
        return "unreadable" if os.path.lexists(path) else "none"
    if current["phase"] == "ambiguous":
        return "ambiguous"
    if current["phase"] != "approved":
        return "none"
    if current["paused"]:
        return "paused"
    stamp = _seconds(now)
    if stamp is None or stamp >= current["expiresAt"]:
        return "expired"
    return "approved-not-sent"


def load(directory: Path) -> dict | None:
    path = Path(directory) / NAME
    if not os.path.lexists(path) or os.path.islink(path) or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    expected = {"format", "phase", "digest", "scope", "event", "approvedAt", "expiresAt", "paused"}
    if set(data) != expected or data.get("format") != FORMAT:
        return None
    if data.get("phase") not in _PHASES or data.get("paused") not in (True, False):
        return None
    if data.get("phase") == "observed":
        return None
    if not _digest(data.get("digest")) or not _scope(data.get("scope")) or not _event(data.get("event")):
        return None
    if _seconds(data.get("approvedAt")) is None or _seconds(data.get("expiresAt")) is None:
        return None
    return {
        "format": FORMAT,
        "phase": data["phase"],
        "digest": data["digest"],
        "scope": data["scope"],
        "event": data["event"],
        "approvedAt": int(data["approvedAt"]),
        "expiresAt": int(data["expiresAt"]),
        "paused": data["paused"],
    }


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


def _scope(value) -> bool:
    return isinstance(value, str) and _SCOPE.fullmatch(value) is not None


def _event(value) -> bool:
    return isinstance(value, str) and _EVENT.fullmatch(value) is not None


def _digest(value) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _seconds(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and value != value:
        return None
    whole = int(value)
    if whole < 0:
        return None
    return whole
