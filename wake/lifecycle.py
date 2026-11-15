"""Finite observer lifetime and an explicit stop switch.

The observer stays scoped to one allowlist summary. ``--seconds`` and
``--once`` make that process exit. ``stop`` persists even if the process is
gone, and both capture and transmission stay off until ``resume``.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from wake.clock import Clock
from wake.outbox import Outbox
from wake.routine import DEFAULT_STORE

STOP_NAME = "STOP"


@dataclass
class ObserveOptions:
    once: bool = False
    seconds: float | None = None
    store: Path = DEFAULT_STORE


def stop_path(store: Path) -> Path:
    return Path(store) / STOP_NAME


def stop_requested(store: Path) -> bool:
    return stop_path(store).exists()


def outbox_stopped(store: Path) -> bool:
    path = Path(store) / "outbox.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    if not isinstance(data, dict):
        return True
    return bool(data.get("stopped"))


def request_stop(store: Path) -> None:
    directory = Path(store)
    directory.mkdir(parents=True, exist_ok=True)
    stop_path(directory).write_text("stop\n", encoding="utf-8")
    box = Outbox(directory / "outbox.json", Clock())
    if not box.blocked:
        box.set_stopped(True)


def clear_stop(store: Path) -> bool:
    """Clear the sentinel. A corrupt outbox stays untouched and stays stopped."""

    directory = Path(store)
    path = stop_path(directory)
    if path.exists():
        path.unlink()
    box = Outbox(directory / "outbox.json", Clock())
    if box.blocked:
        return False
    box.set_stopped(False)
    return True


def session_bus_address(env: dict, path_exists=os.path.exists) -> str:
    address = env.get("DBUS_SESSION_BUS_ADDRESS") or ""
    if address:
        return address
    runtime = env.get("XDG_RUNTIME_DIR") or ""
    if runtime and path_exists(os.path.join(runtime, "bus")):
        return "unix:path=" + os.path.join(runtime, "bus")
    candidate = f"/run/user/{os.getuid()}/bus"
    if path_exists(candidate):
        return "unix:path=" + candidate
    return ""
