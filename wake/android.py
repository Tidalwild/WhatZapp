"""Metadata adapter for the existing public Android listener.

The listener already sees package, key, post time, and title. This function
does not accept message text. ``post_time_ms`` is ignored: a rendered clock
is not proof that a row just arrived.
"""

import hashlib

from wake.model import Observation

PACKAGES = frozenset({"com.whatsapp", "com.whatsapp.w4b"})


def from_listener(
    *,
    package: str,
    notification_key: str,
    title: str | None,
    post_time_ms: int | None = None,
) -> tuple:
    _ = post_time_ms
    if package not in PACKAGES:
        return None, "WRONG_PACKAGE"
    if not isinstance(notification_key, str) or not notification_key:
        return None, "MISSING_IDENTITY"
    digest = hashlib.sha256(notification_key.encode("utf-8")).digest()
    replaces = int.from_bytes(digest[:4], "big") or 1
    return (
        Observation(
            app_name="",
            replaces_id=replaces,
            summary=title or "",
            origin="android-listener",
        ),
        "OK",
    )
