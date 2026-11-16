"""Opt-in context for one chat. Off until the operator enables it.

Facts from another chat are dropped. Fact text is untrusted data: it cannot
change scope, arm a send, or revoke a different chat. Nothing here is placed
on the wake webhook.
"""

import json
import os
import re
from pathlib import Path

NAME = "context-policy.json"
FORMAT = "wake-context-1"
TOKEN_BUDGET = 2000
MAX_TTL = 24 * 60 * 60
_SCOPE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


def enable(directory: Path, scope: str, now, ttl: int = 4 * 60 * 60) -> str:
    if not _scope(scope) or not _seconds(now) or not isinstance(ttl, int) or isinstance(ttl, bool):
        return "UNPARSEABLE"
    if ttl < 60 or ttl > MAX_TTL:
        return "UNPARSEABLE"
    stamp = int(now)
    payload = {
        "format": FORMAT,
        "enabled": True,
        "scope": scope,
        "source": "operator",
        "enabledAt": stamp,
        "expiresAt": stamp + ttl,
        "revoked": False,
    }
    return "ENABLED" if _save(directory, payload) else "UNREADABLE"


def revoke(directory: Path, scope: str, now) -> str:
    current = load(directory)
    if current is None:
        return "ABSENT"
    if not _scope(scope) or scope != current["scope"] or _seconds(now) is None:
        return "UNPARSEABLE"
    payload = dict(current)
    payload["enabled"] = False
    payload["revoked"] = True
    return "REVOKED" if _save(directory, payload) else "UNREADABLE"


def describe(directory: Path, now) -> str:
    path = Path(directory) / NAME
    if not os.path.lexists(path):
        return "off"
    current = load(directory)
    if current is None:
        return "unreadable"
    if current["revoked"] or not current["enabled"]:
        return "revoked"
    stamp = _seconds(now)
    if stamp is None or stamp >= current["expiresAt"]:
        return "stale"
    return "enabled"


def assemble(directory: Path, scope: str, facts, now) -> dict:
    """Return provenance and bounded text for this scope, or abstain.

    The result has no mode and no send flag. Fact text is copied only as data.
    """

    status = describe(directory, now)
    empty = {
        "status": "abstain" if status == "enabled" else status,
        "text": "",
        "scope": "",
        "source": "",
        "fresh": False,
        "budget": TOKEN_BUDGET,
        "dropped": 0,
    }
    if status != "enabled":
        return empty
    current = load(directory)
    if current is None or current["scope"] != scope or not _scope(scope):
        empty["status"] = "wrong-chat"
        return empty
    kept = []
    dropped = 0
    if not isinstance(facts, list):
        empty["status"] = "abstain"
        return empty
    for fact in facts:
        if not isinstance(fact, dict):
            dropped += 1
            continue
        if fact.get("scope") != scope or not isinstance(fact.get("text"), str):
            dropped += 1
            continue
        if set(fact) - {"scope", "text", "source"}:
            dropped += 1
            continue
        kept.append(fact["text"])
    text = _budget(kept)
    if text == "":
        empty["status"] = "abstain"
        empty["dropped"] = dropped
        empty["scope"] = scope
        empty["source"] = "operator"
        return empty
    return {
        "status": "ready",
        "text": text,
        "scope": scope,
        "source": "operator",
        "fresh": True,
        "budget": TOKEN_BUDGET,
        "dropped": dropped,
    }


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
    expected = {"format", "enabled", "scope", "source", "enabledAt", "expiresAt", "revoked"}
    if set(data) != expected or data.get("format") != FORMAT:
        return None
    if data.get("enabled") not in (True, False) or data.get("revoked") not in (True, False):
        return None
    if data.get("source") != "operator" or not _scope(data.get("scope")):
        return None
    if _seconds(data.get("enabledAt")) is None or _seconds(data.get("expiresAt")) is None:
        return None
    if int(data["expiresAt"]) < int(data["enabledAt"]):
        return None
    return {
        "format": FORMAT,
        "enabled": data["enabled"],
        "scope": data["scope"],
        "source": "operator",
        "enabledAt": int(data["enabledAt"]),
        "expiresAt": int(data["expiresAt"]),
        "revoked": data["revoked"],
    }


def _budget(parts: list[str]) -> str:
    used = []
    size = 0
    for part in parts:
        if part == "":
            continue
        extra = len(part) + (1 if used else 0)
        if size + extra > TOKEN_BUDGET:
            break
        used.append(part)
        size += extra
    return "\n".join(used)


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


def _seconds(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and value != value:
        return None
    whole = int(value)
    if whole < 0:
        return None
    return whole
