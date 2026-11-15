"""Contact scope for a reply policy. The default is nobody.

A label is not a verified recipient. Groups are out unless ``groups`` is
``include``. This module does not read a chat and does not send.
"""

import re

LABEL = re.compile(r"[A-Za-z0-9._-]{1,40}")
MODES = frozenset({"off", "allowlist", "direct"})


def default_scope() -> dict:
    return {"mode": "off", "allow": [], "deny": [], "groups": "exclude", "maxReplies": 0}


def normalize_scope(value) -> dict:
    if not isinstance(value, dict):
        return default_scope()
    mode = value.get("mode") if value.get("mode") in MODES else "off"
    groups = "include" if value.get("groups") == "include" else "exclude"
    raw = value.get("maxReplies")
    cap = raw if isinstance(raw, int) and not isinstance(raw, bool) and 0 < raw <= 10000 else 0
    return {
        "mode": mode,
        "allow": _labels(value.get("allow")),
        "deny": _labels(value.get("deny")),
        "groups": groups,
        "maxReplies": cap,
    }


def contact_in_scope(scope, *, label: str, kind: str) -> bool:
    policy = normalize_scope(scope)
    if policy["mode"] == "off":
        return False
    if not isinstance(label, str) or LABEL.fullmatch(label) is None or label in policy["deny"]:
        return False
    if kind == "group":
        return policy["groups"] == "include" and (policy["mode"] == "direct" or label in policy["allow"])
    if kind != "direct":
        return False
    if policy["mode"] == "direct":
        return True
    return label in policy["allow"]


def _labels(value) -> list:
    if not isinstance(value, list):
        return []
    seen = []
    for item in value:
        if isinstance(item, str) and LABEL.fullmatch(item) and item not in seen:
            seen.append(item)
        if len(seen) == 200:
            break
    return seen
