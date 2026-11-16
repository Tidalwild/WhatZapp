"""Connection recovery.

``connection_status`` is a unit model. It can describe a live page only when
the caller passes ``live_page=True``. Nothing in this package observes the
browser, so ``disk_status`` and ``note_restart`` never do that. A stored
outbox is not a send, and restart does not replay an acknowledged row.
"""

import json
import os
import stat
from pathlib import Path

from wake.bridge import read_host
from wake.clock import Clock
from wake.outbox import Outbox
from wake.read import BINDING_NAME, WINDOW_NAME, load_binding

LABELS_ZH_HANT = {
    "disconnected": "已中斷",
    "recovering": "復原中",
    "ready": "已重新確認",
    "relink": "需要重新連結",
}

UNRESOLVED_STATES = frozenset({"pending", "retryable", "in_flight"})


class PageFacts:
    def __init__(
        self,
        phase: str = "absent",
        fresh: bool = False,
        network: str = "unknown",
        identity: str = "unchecked",
    ) -> None:
        self.phase = phase if phase in {"absent", "loading", "ready", "navigated", "logged-out"} else "absent"
        self.fresh = bool(fresh)
        self.network = network if network in {"unknown", "up", "down"} else "unknown"
        self.identity = identity if identity in {"unchecked", "match", "mismatch"} else "unchecked"


def connection_status(
    host_phase: str,
    host_live: str,
    facts: PageFacts,
    binding_set: bool,
    *,
    live_page: bool = False,
) -> tuple:
    """Model a connection. ``live_page`` is not read from disk.

    The default is false. A boolean ``fresh`` flag is not a page observation,
    so the default result is never ``ready``.
    """

    if facts.phase == "logged-out":
        return "relink", "logged-out"
    if facts.identity == "mismatch":
        return "relink", "identity-mismatch"
    if host_phase == "stale" or host_live == "no":
        return "disconnected", "host-stale"
    if facts.phase == "navigated":
        return "disconnected", "navigated"
    if not live_page or not facts.fresh or facts.phase != "ready":
        if facts.phase == "ready":
            return "disconnected", "stale-page"
    if not binding_set:
        return "disconnected", "binding-missing"
    if facts.network == "down":
        return "recovering", "network-down"
    if facts.phase == "loading" or host_phase != "listening" or host_live != "yes":
        return "recovering", "restart"
    if facts.identity != "match":
        return "recovering", "identity-unchecked"
    if live_page and facts.phase == "ready" and facts.fresh and facts.network == "up":
        return "ready", "revalidated"
    return "recovering", "incomplete"


def disk_status(host_phase: str, host_live: str, binding_set: bool) -> tuple:
    """Status from host.json and the binding file. Never ready."""

    if host_phase == "stale" or host_live == "no":
        return "disconnected", "host-stale"
    if not binding_set:
        return "disconnected", "binding-missing"
    if host_phase == "listening" and host_live == "yes":
        return "recovering", "page-not-observed"
    return "recovering", "restart"


def label(state: str, language: str = "en") -> str:
    if language == "zh-Hant":
        return LABELS_ZH_HANT[state]
    return state


def note_restart(store: Path) -> str:
    """Persist the host's in-flight rule without touching a live process.

    Acknowledged and rejected rows stay as stored. An in-flight row at the
    attempt cap becomes rejected. A symlink is not followed or replaced.
    """

    directory = Path(store)
    if read_host(directory).get("live") == "yes":
        return "skipped-host-live"
    path = directory / "outbox.json"
    if path.is_symlink():
        return "unreadable"
    if not path.is_file():
        return "absent"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "unreadable"
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return "unreadable"
    before = path.read_bytes()
    inflight = [item for item in items if isinstance(item, dict) and item.get("state") == "in_flight"]
    if not inflight:
        return "unchanged"
    box = Outbox(path, Clock())
    if box.blocked:
        return "unreadable"
    if path.is_symlink():
        return "unreadable"
    box.save()
    if path.is_symlink() or path.read_bytes() == before:
        return "unchanged"
    item_ids = [item.get("eventId") for item in inflight if isinstance(item.get("eventId"), str)]
    changed = [box.items[item_id] for item_id in item_ids if item_id in box.items]
    if changed and all(item.state == "rejected" and item.reason == "GAVE_UP" for item in changed):
        return "capped"
    return "kept"


def unlink_regular(path: Path) -> bool:
    """Remove one regular file. Do not follow a symlink or a directory."""

    try:
        info = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        held = os.fstat(descriptor)
        if not stat.S_ISREG(held.st_mode) or held.st_ino != info.st_ino:
            return False
    finally:
        os.close(descriptor)
    try:
        current = path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(current.st_mode) or current.st_ino != info.st_ino:
        return False
    path.unlink()
    return True


def unresolved_count(store: Path) -> int | None:
    path = Path(store) / "outbox.json"
    if path.is_symlink() or not path.is_file():
        return 0 if not path.exists() else None
    box = Outbox(path, Clock())
    if box.blocked:
        return None
    return sum(1 for item in box.items.values() if item.state in UNRESOLVED_STATES)


def apply_relink(store: Path) -> None:
    """Drop the chat binding. Leave the scope mode file untouched."""

    directory = Path(store)
    if directory.is_symlink() or not directory.is_dir():
        return
    for name in (BINDING_NAME, WINDOW_NAME):
        unlink_regular(directory / name)


def binding_state(store: Path) -> str:
    path = Path(store) / BINDING_NAME
    if path.is_symlink():
        return "unreadable"
    if not path.exists():
        return "missing"
    if load_binding(store) is None:
        return "unreadable"
    return "set"
