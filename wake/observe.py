"""Passive reader for org.freedesktop.Notifications.Notify.

dbus-monitor watches the bus. This process does not own that well-known name,
so it does not replace the desktop notification daemon.
"""

import os
import pty
import re
import select
import subprocess
import threading

from wake.model import Observation, ParseFailure
from wake.policy import LABEL_TOKEN

STRING_RE = re.compile(r'^string "(.*)"$')
UINT_RE = re.compile(r"^uint32 (\d+)$")
INT_RE = re.compile(r"^int32 (-?\d+)$")
SECRET_ENV = (
    "WHATSAPP_WAKE_URL",
    "WHATSAPP_WAKE_AUTHORIZATION",
    "WHATSAPP_WAKE_ROUTINE_AUTHORIZATION",
)


def user_bus_available(env: dict | None = None, *, path_exists=os.path.exists) -> bool:
    source = os.environ if env is None else env
    if source.get("DBUS_SESSION_BUS_ADDRESS"):
        return True
    runtime = source.get("XDG_RUNTIME_DIR")
    if runtime and path_exists(os.path.join(runtime, "bus")):
        return True
    return bool(path_exists(f"/run/user/{os.getuid()}/bus"))


def notify_match_rule(label: str) -> str:
    """Match Notify calls whose summary equals the allowlist token.

    D-Bus arg3 is the summary, the fourth argument. The app name is arg0 and
    is intentionally not part of the rule: it is forgeable and is not proof
    that WhatsApp sent the call. The bus delivers only matching calls, so
    other bodies are not copied into this process.
    """

    if not isinstance(label, str) or LABEL_TOKEN.fullmatch(label) is None:
        raise ValueError("label")
    return (
        "type='method_call',"
        "interface='org.freedesktop.Notifications',"
        "member='Notify',"
        f"arg3='{label}'"
    )


def notifications_service(env: dict | None = None) -> str:
    """Return owned, absent, unavailable, or unknown. This does not own the name."""

    source = os.environ if env is None else env
    if not user_bus_available(source):
        return "unavailable"
    command = [
        "dbus-send",
        "--print-reply",
        "--reply-timeout=1000",
        "--dest=org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus.NameHasOwner",
        "string:org.freedesktop.Notifications",
    ]
    address = source.get("DBUS_SESSION_BUS_ADDRESS") or ""
    command.insert(1, f"--bus={address}" if address else "--session")
    try:
        result = subprocess.run(
            command,
            env=_dbus_env(source),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    if "boolean true" in result.stdout:
        return "owned"
    if "boolean false" in result.stdout:
        return "absent"
    return "unknown"


def _dbus_env(source: dict) -> dict:
    env = os.environ.copy()
    for key in SECRET_ENV:
        env.pop(key, None)
    if "DBUS_SESSION_BUS_ADDRESS" in source:
        address = source.get("DBUS_SESSION_BUS_ADDRESS") or ""
        if address:
            env["DBUS_SESSION_BUS_ADDRESS"] = address
        else:
            env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    return env


def _unescape(value: str) -> str:
    out = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= len(value):
            raise ValueError("escape")
        nxt = value[index + 1]
        if nxt == "\\":
            out.append("\\")
        elif nxt == '"':
            out.append('"')
        elif nxt == "n":
            out.append("\n")
        else:
            raise ValueError("escape")
        index += 2
    return "".join(out)


def try_parse(lines: list) -> Observation | ParseFailure | None:
    """Parse one Notify call. The body string is not kept."""

    if not lines or not _notify_header(lines[0]):
        return None
    phase = "app"
    app_name = None
    replaces_id = None
    summary = None
    depth = 0
    saw_expire = False
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("array ["):
            depth += 1
            continue
        if stripped == "]" or stripped.startswith("]"):
            if depth == 0:
                return ParseFailure()
            depth -= 1
            continue
        if depth:
            continue
        string_match = STRING_RE.fullmatch(stripped)
        if string_match:
            if phase == "app":
                try:
                    app_name = _unescape(string_match.group(1))
                except ValueError:
                    return ParseFailure()
                phase = "id"
            elif phase == "icon":
                phase = "summary"
            elif phase == "summary":
                try:
                    summary = _unescape(string_match.group(1))
                except ValueError:
                    return ParseFailure()
                phase = "body"
            elif phase == "body":
                continue
            else:
                return ParseFailure()
            continue
        uint_match = UINT_RE.fullmatch(stripped)
        if uint_match:
            if phase != "id":
                return ParseFailure()
            replaces_id = int(uint_match.group(1))
            phase = "icon"
            continue
        if INT_RE.fullmatch(stripped):
            saw_expire = True
            break
        return ParseFailure()
    if not saw_expire:
        return None
    if phase != "body" or app_name is None or replaces_id is None or summary is None:
        return ParseFailure()
    return Observation(
        app_name=app_name,
        replaces_id=replaces_id,
        summary=summary,
        origin="session-bus",
    )


def _notify_header(line: str) -> bool:
    return (
        line.startswith("method call ")
        and "member=Notify" in line
        and "interface=org.freedesktop.Notifications" in line
    )


def _message_start(line: str) -> bool:
    return line.startswith(("method call ", "signal ", "method return ", "error "))


class NotifyParser:
    def __init__(self) -> None:
        self._buf = []
        self._on = False

    def feed(self, line: str) -> list:
        if _message_start(line):
            pending = self.finish()
            self._buf = [line]
            self._on = _notify_header(line)
            if not self._on:
                self._buf = []
            return pending
        if not self._on:
            return []
        self._buf.append(line)
        parsed = try_parse(self._buf)
        if parsed is None:
            return []
        self._buf = []
        self._on = False
        return [parsed]

    def finish(self) -> list:
        if not self._buf:
            return []
        parsed = try_parse(self._buf)
        self._buf = []
        self._on = False
        if parsed is None:
            return [ParseFailure()]
        if isinstance(parsed, ParseFailure):
            return [parsed]
        return [parsed]


def monitor(address: str, handler, stop: threading.Event, *, allowlist: str, tape=None, on_tick=None) -> None:
    """Block on a summary-scoped dbus-monitor. The handler sees parsed calls only."""

    rule = notify_match_rule(allowlist)
    master, slave = pty.openpty()
    env = os.environ.copy()
    env["DBUS_SESSION_BUS_ADDRESS"] = address
    for key in SECRET_ENV:
        env.pop(key, None)
    proc = subprocess.Popen(
        ["dbus-monitor", "--session", rule],
        stdin=subprocess.DEVNULL,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    parser = NotifyParser()
    pending = ""
    try:
        while not stop.is_set():
            ready, _, _ = select.select([master], [], [], 0.2)
            if on_tick is not None:
                on_tick()
            if stop.is_set() or (proc.poll() is not None and not ready):
                break
            if not ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace")
            if tape is not None:
                tape.append(text)
            pending += text
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                for item in parser.feed(line.rstrip("\r")):
                    handler(item)
        for item in parser.finish():
            handler(item)
    finally:
        stop.set()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        os.close(master)
