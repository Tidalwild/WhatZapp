"""Connection recovery. A stored file cannot make the session ready.

Ready requires a live host, a fresh ready page, a network that is up, a
binding, and an explicit identity match. Logout and a mismatched chat
require a new link. They do not widen scope. This module does not send.
"""

from pathlib import Path

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


def connection_status(host_phase: str, host_live: str, facts: PageFacts, binding_set: bool) -> tuple:
    """Return the connection state and a short reason. Never infer incoming."""

    if facts.phase == "logged-out":
        return "relink", "logged-out"
    if facts.identity == "mismatch":
        return "relink", "identity-mismatch"
    if host_phase == "stale" or host_live == "no":
        return "disconnected", "host-stale"
    if facts.phase == "navigated":
        return "disconnected", "navigated"
    if facts.phase == "ready" and not facts.fresh:
        return "disconnected", "stale-page"
    if not binding_set:
        return "disconnected", "binding-missing"
    if facts.network == "down":
        return "recovering", "network-down"
    if facts.phase == "loading" or host_phase != "listening" or host_live != "yes":
        return "recovering", "restart"
    if facts.identity != "match":
        return "recovering", "identity-unchecked"
    if facts.phase == "ready" and facts.fresh and facts.network == "up":
        return "ready", "revalidated"
    return "recovering", "incomplete"


def label(state: str, language: str = "en") -> str:
    if language == "zh-Hant":
        return LABELS_ZH_HANT[state]
    return state


def note_restart(store: Path) -> int:
    """Keep ids that were in flight. Restart does not cover or delete them."""

    path = Path(store) / "outbox.json"
    box = Outbox(path, Clock())
    if box.blocked:
        return -1
    kept = 0
    for item in box.items.values():
        if item.state in UNRESOLVED_STATES:
            kept += 1
    box.save()
    return kept


def unresolved_count(store: Path) -> int | None:
    box = Outbox(Path(store) / "outbox.json", Clock())
    if box.blocked:
        return None
    return sum(1 for item in box.items.values() if item.state in UNRESOLVED_STATES)


def apply_relink(store: Path) -> None:
    """Drop the chat binding. Leave the scope mode file untouched."""

    directory = Path(store)
    for name in (BINDING_NAME, WINDOW_NAME):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            continue
        path.unlink()


def binding_state(store: Path) -> str:
    path = Path(store) / BINDING_NAME
    if not path.exists():
        return "missing"
    if load_binding(store) is None:
        return "unreadable"
    return "set"
