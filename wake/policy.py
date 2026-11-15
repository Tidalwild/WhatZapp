import re
from dataclasses import dataclass

# One token, safe to place in a D-Bus match rule. Not an app name and not a recipient id.
LABEL_TOKEN = re.compile(r"[A-Za-z0-9._-]{1,40}")


def valid_label(value: object) -> bool:
    return isinstance(value, str) and LABEL_TOKEN.fullmatch(value) is not None


def hostile(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if len(value) > 80:
        return True
    if any(ord(char) < 32 for char in value):
        return True
    lowered = value.lower()
    if "://" in value or "http:" in lowered or "https:" in lowered:
        return True
    return False


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str
    scope: str | None = None


def classify(summary: object, allowlist_label: object) -> Decision:
    """Match one configured label. The summary is never a verified recipient."""

    if not valid_label(allowlist_label):
        return Decision(False, "ALLOWLIST_UNSET")
    if not isinstance(summary, str) or summary == "":
        return Decision(False, "MISSING_IDENTITY")
    if hostile(summary):
        return Decision(False, "UNTRUSTED_TEXT")
    if summary != allowlist_label:
        return Decision(False, "WRONG_OR_AMBIGUOUS")
    return Decision(True, "MATCH", str(allowlist_label))
