"""Copy the native host into a home directory and check that copy.

The copy is the program a browser would start. This module does not start a
browser, read a credential, send a message, or register a routine.
"""

import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path

from wake.bridge import HOST_NAME
from wake.evidence import CONTRACT

PRODUCTS = ("google-chrome", "google-chrome-for-testing", "chromium")
LIB_PARTS = (".local", "share", "draft-bridge")
WRAPPER_NAME = "wake-bridge-host"
STAMP_NAME = "install-stamp"
LIST_NAME = ".installed-files"
RUNTIME_NAME = "runtime-path"
EXTENSION_COPY = "extension-manifest.json"
_ID = re.compile(r"^[a-p]{32}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_MODULE = re.compile(r"^[A-Za-z0-9_]+\.py$")
_HOST_VERSION = re.compile(r'(?m)^__version__ = "([^"]+)"$')
INSTALL_USAGE = "usage: install-wake-bridge.sh [--extension-id ID] [--home DIR] [--repo DIR] [--uninstall]"
CHECK_USAGE = "usage: python -m wake install-check [--home DIR] [--dist DIR]"


class InstallError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def install_main(rest: list[str]) -> int:
    try:
        home, repo, extension_id, uninstall = _install_args(rest)
        if uninstall:
            text = uninstall_host(Path(home))
        else:
            text = install_host(Path(home), Path(repo), extension_id)
    except InstallError as exc:
        print(exc.message, file=sys.stderr)
        return 2
    print(text, end="")
    return 0


def check_main(rest: list[str]) -> int:
    try:
        home, dist = _check_args(rest)
        code, text = check_host(Path(home), dist)
    except InstallError as exc:
        print(exc.message, file=sys.stderr)
        return 2
    print(text, end="")
    return code


def install_host(home: Path, repo: Path, extension_id: str) -> str:
    lib, runtime, config = _layout(home)
    _refuse_world_writable(home)
    if not _ID.fullmatch(extension_id or ""):
        raise InstallError("blocked: extension id must be 32 characters from a-p. Nothing was installed.")
    source = _source_package(repo)
    manifest = _read_extension_manifest(repo / "web" / "manifest.json")
    host_version = _version_in(_HOST_VERSION, (source / "__init__.py").read_text(encoding="utf-8"), "host version")
    extension_version = _version_in(None, manifest.get("version"), "extension version")
    wrapper = lib / WRAPPER_NAME
    modules = sorted(
        path.name
        for path in source.glob("*.py")
        if path.is_file() and not path.is_symlink() and _MODULE.fullmatch(path.name)
    )
    _preflight(home, lib, runtime, config, wrapper)
    _mkdirs(lib, runtime / "wake", *[config / product / "NativeMessagingHosts" for product in PRODUCTS])
    previous = _read_list(runtime / "wake" / LIST_NAME)
    for name in modules:
        _write_regular(runtime / "wake" / name, (source / name).read_bytes(), 0o644)
    for name in previous - set(modules):
        _unlink_entry(runtime / "wake" / name)
    _write_regular(runtime / "wake" / LIST_NAME, ("".join(f"{name}\n" for name in modules)).encode("utf-8"), 0o644)
    _write_regular(lib / EXTENSION_COPY, json.dumps(manifest, indent=2).encode("utf-8") + b"\n", 0o644)
    _write_regular(lib / RUNTIME_NAME, (str(runtime) + "\n").encode("utf-8"), 0o644)
    python = sys.executable
    _write_regular(wrapper, _wrapper(runtime, python).encode("utf-8"), 0o755)
    body = _native_manifest(wrapper, extension_id)
    for product in PRODUCTS:
        _write_regular(config / product / "NativeMessagingHosts" / f"{HOST_NAME}.json", body, 0o644)
    stamp = "\n".join(
        [
            "format: host-install-1",
            f"host: {host_version}",
            f"extension: {extension_version}",
            f"contract: {CONTRACT}",
            "",
        ]
    )
    _write_regular(lib / STAMP_NAME, stamp.encode("utf-8"), 0o644)
    return "\n".join(
        [
            "install: files",
            f"host: {host_version}",
            f"extension: {extension_version}",
            "pair: recorded",
            "allowed-origin: one",
            "host-copy: install-runtime",
            "browser-loaded: no",
            "template-installed: no",
            "credential-file: untouched",
            "sends-whatsapp: no",
            f"wrapper: {wrapper}",
            "",
        ]
    )


def uninstall_host(home: Path) -> str:
    lib, runtime, config = _layout(home)
    _refuse_world_writable(home)
    package = runtime / "wake"
    targets = [lib / WRAPPER_NAME, lib / STAMP_NAME, lib / RUNTIME_NAME, lib / EXTENSION_COPY, package / LIST_NAME]
    for product in PRODUCTS:
        targets.append(config / product / "NativeMessagingHosts" / f"{HOST_NAME}.json")
    for target in targets:
        if _chain(home, target) == "symlink":
            raise InstallError("blocked: destination is a symlink. Nothing was removed.")
    removed = []
    for name in _read_list(package / LIST_NAME):
        if _unlink_entry(package / name):
            removed.append(name)
    if _unlink_entry(package / LIST_NAME):
        removed.append(LIST_NAME)
    _remove_pycache(package)
    _rmdir_if_empty(package)
    _rmdir_if_empty(runtime)
    for name in (WRAPPER_NAME, STAMP_NAME, RUNTIME_NAME, EXTENSION_COPY):
        if _unlink_entry(lib / name):
            removed.append(name)
    wrapper = str(lib / WRAPPER_NAME)
    manifests = 0
    for product in PRODUCTS:
        path = config / product / "NativeMessagingHosts" / f"{HOST_NAME}.json"
        if _remove_manifest(path, wrapper):
            manifests += 1
    if manifests:
        removed.append("native-host-manifest")
    credential = _credential_file(home)
    return "\n".join(
        [
            "uninstall: done" if removed else "uninstall: absent",
            "removed: " + (" ".join(removed) if removed else "none"),
            f"credential-file: {'kept' if credential.exists() and not credential.is_symlink() else 'absent'}",
            "unknown-files: kept",
            "store: kept",
            "browser-loaded: no",
            "sends-whatsapp: no",
            "",
        ]
    )


def check_host(home: Path, dist: Path | None) -> tuple[int, str]:
    lib, runtime, config = _layout(home)
    _refuse_world_writable(home)
    stamp_path = lib / STAMP_NAME
    if stamp_path.is_symlink() or not stamp_path.is_file():
        return 1, _absent()
    stamp = _parse_stamp(stamp_path.read_text(encoding="utf-8"))
    problems = []
    if stamp.get("format") != "host-install-1" or stamp.get("contract") != CONTRACT:
        problems.append("stamp")
    host_version = stamp.get("host") or ""
    extension_version = stamp.get("extension") or ""
    if not _VERSION.fullmatch(host_version) or not _VERSION.fullmatch(extension_version):
        problems.append("version")
    init_path = runtime / "wake" / "__init__.py"
    copied = _host_version(init_path)
    if copied != host_version:
        problems.append("host")
    try:
        extension_copy = json.loads((lib / EXTENSION_COPY).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        extension_copy = {}
    if not isinstance(extension_copy, dict) or extension_copy.get("version") != extension_version:
        problems.append("extension")
    runtime_text = _regular_text(lib / RUNTIME_NAME)
    if runtime_text != str(runtime) + "\n":
        problems.append("runtime")
    wrapper = lib / WRAPPER_NAME
    wrapper_text = _regular_text(wrapper)
    if not _wrapper_matches(wrapper_text, runtime):
        problems.append("wrapper")
    elif not wrapper.is_file() or wrapper.is_symlink() or not os.access(wrapper, os.X_OK):
        problems.append("wrapper")
    origins = _origins(config, wrapper)
    if origins != "one":
        problems.append("origin")
    imported = _import_version(runtime) if "host" not in problems else ""
    if imported != host_version:
        problems.append("import")
    dist_line = _dist_line(dist, extension_version)
    if dist_line == "extension-dist: mismatch":
        problems.append("dist")
    pair = "match" if not problems else "mismatch"
    credential = _credential_file(home)
    lines = [
        "install-check: files" if pair == "match" else "install-check: mismatch",
        "install-proven: files" if pair == "match" else "install-proven: mismatch",
        "install-evidence: installed-copy",
        f"host: {host_version if _VERSION.fullmatch(host_version) else 'unreadable'}",
        f"extension: {extension_version if _VERSION.fullmatch(extension_version) else 'unreadable'}",
        f"pair: {pair}",
        f"contract: {stamp.get('contract') if stamp.get('contract') == CONTRACT else 'mismatch'}",
        "host-copy: install-runtime" if "wrapper" not in problems and "runtime" not in problems else "host-copy: not-install-runtime",
        f"credential-file: {'present' if credential.is_file() and not credential.is_symlink() else 'absent'}",
        "browser-loaded: no",
        "template-installed: no",
        "response-recorder: not-in-this-package",
        "bot-response: unproven",
        dist_line,
        "webhook-probe: not-run",
        "whatsapp-session: not-run",
        "fresh-setup: unproven",
        "sends-whatsapp: no",
    ]
    text = "\n".join(lines) + "\n"
    if str(home) and str(home) in text:
        raise InstallError("blocked: report would include the install path. Nothing was printed.")
    return (0 if pair == "match" else 1), text


def _install_args(rest: list[str]) -> tuple[str, str, str, bool]:
    home = os.environ.get("HOME") or ""
    repo = str(Path(__file__).resolve().parents[1])
    extension_id = ""
    uninstall = False
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--uninstall":
            uninstall = True
            index += 1
            continue
        if token in {"--home", "--repo", "--extension-id"} and index + 1 < len(rest):
            value = rest[index + 1]
            if token == "--home":
                home = value
            elif token == "--repo":
                repo = value
            else:
                extension_id = value
            index += 2
            continue
        raise InstallError(INSTALL_USAGE)
    if not home:
        raise InstallError("blocked: home directory is missing. Nothing was installed.")
    return home, repo, extension_id, uninstall


def _check_args(rest: list[str]) -> tuple[str, Path | None]:
    home = os.environ.get("HOME") or ""
    dist = None
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in {"--home", "--dist"} and index + 1 < len(rest):
            if token == "--home":
                home = rest[index + 1]
            else:
                dist = Path(rest[index + 1])
            index += 2
            continue
        raise InstallError(CHECK_USAGE)
    if not home:
        raise InstallError("blocked: home directory is missing.")
    return home, dist


def _layout(home: Path) -> tuple[Path, Path, Path]:
    if not home.is_dir() or home.is_symlink():
        raise InstallError("blocked: home directory is missing. Nothing was installed.")
    config = _config_home(home)
    lib = home.joinpath(*LIB_PARTS)
    runtime = lib / "runtime"
    return lib, runtime, config


def _config_home(home: Path) -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME") or ""
    config = Path(raw) if raw else home / ".config"
    try:
        config.resolve().relative_to(home.resolve())
    except (OSError, ValueError):
        raise InstallError("blocked: config home must stay inside the install home. Nothing was installed.") from None
    if config.is_symlink():
        raise InstallError("blocked: destination is a symlink. Nothing was installed.")
    return config


def _source_package(repo: Path) -> Path:
    source = repo / "wake"
    if not source.is_dir() or source.is_symlink():
        raise InstallError("blocked: wake package was not found. Nothing was installed.")
    modules = [path for path in source.glob("*.py") if path.is_file() and not path.is_symlink() and _MODULE.fullmatch(path.name)]
    if not any(path.name == "__init__.py" for path in modules):
        raise InstallError("blocked: wake package was not found. Nothing was installed.")
    return source


def _read_extension_manifest(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise InstallError("blocked: extension manifest was not found. Nothing was installed.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InstallError("blocked: extension manifest was not found. Nothing was installed.") from None
    if not isinstance(data, dict):
        raise InstallError("blocked: extension manifest was not found. Nothing was installed.")
    return data


def _version_in(pattern, value, label: str) -> str:
    if pattern is not None:
        match = pattern.search(value or "")
        value = match.group(1) if match else ""
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise InstallError(f"blocked: {label} is unreadable. Nothing was installed.")
    return value


def _preflight(home: Path, lib: Path, runtime: Path, config: Path, wrapper: Path) -> None:
    _refuse_world_writable(home)
    targets = [
        wrapper,
        lib / STAMP_NAME,
        lib / EXTENSION_COPY,
        lib / RUNTIME_NAME,
        runtime / "wake" / "__init__.py",
    ]
    for product in PRODUCTS:
        targets.append(config / product / "NativeMessagingHosts" / f"{HOST_NAME}.json")
    for target in targets:
        if _chain(home, target) == "symlink":
            raise InstallError("blocked: destination is a symlink. Nothing was installed.")


def _refuse_world_writable(home: Path) -> None:
    text = str(home)
    if text == "/tmp" or text.startswith("/tmp/") or text == "/var/tmp" or text.startswith("/var/tmp/") or text == "/dev/shm" or text.startswith("/dev/shm/"):
        raise InstallError("blocked: Chrome ignores a native host under a world-writable directory. Choose a home outside /tmp.")
    current = home
    while True:
        if current.is_symlink():
            raise InstallError("blocked: destination is a symlink. Nothing was installed.")
        try:
            mode = current.stat(follow_symlinks=False).st_mode
        except OSError:
            raise InstallError("blocked: home directory is missing. Nothing was installed.") from None
        if mode & stat.S_IWOTH:
            raise InstallError("blocked: Chrome ignores a native host under a world-writable directory. Choose a home outside /tmp.")
        if current.parent == current:
            return
        current = current.parent


def _chain(home: Path, path: Path) -> str:
    current = home
    if current.is_symlink():
        return "symlink"
    if not current.is_dir():
        return "absent"
    try:
        relative = path.relative_to(home)
    except ValueError:
        return "symlink"
    for part in relative.parts[:-1]:
        current = current / part
        if not os.path.lexists(current):
            return "absent"
        if current.is_symlink() or not current.is_dir():
            return "symlink"
    if path.is_symlink():
        return "symlink"
    return "ok"


def _mkdirs(*paths: Path) -> None:
    for path in paths:
        current = path
        missing = []
        while not current.exists():
            missing.append(current)
            if current.parent == current:
                break
            current = current.parent
        for directory in reversed(missing):
            if directory.is_symlink():
                raise InstallError("blocked: destination is a symlink. Nothing was installed.")
            directory.mkdir(mode=0o755)


def _write_regular(path: Path, data: bytes, mode: int) -> None:
    # ponytail: symlink check then replace, not a directory lock
    if path.is_symlink():
        raise InstallError("blocked: destination is a symlink. Nothing was installed.")
    path.parent.mkdir(mode=0o755, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.is_symlink():
        raise InstallError("blocked: destination is a symlink. Nothing was installed.")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    except OSError:
        raise InstallError("blocked: destination is a symlink. Nothing was installed.") from None
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(temporary, mode)
    if path.is_symlink():
        temporary.unlink(missing_ok=True)
        raise InstallError("blocked: destination is a symlink. Nothing was installed.")
    os.replace(temporary, path)


def _wrapper(runtime: Path, python: str) -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "# No webhook address and no credential are stored in this file.",
            "# The env file is copied as literal assignments. It is not executed.",
            "set -eu",
            f"export PYTHONPATH={shlex.quote(str(runtime))}${{PYTHONPATH:+:$PYTHONPATH}}",
            'envfile="${WHATSAPP_WAKE_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/draft-bridge/wake.env}"',
            'if [ -f "$envfile" ]; then',
            '  while IFS= read -r line || [ -n "$line" ]; do',
            "    cr=$(printf '\\r')",
            '    line=${line%$cr}',
            '    line=${line#"${line%%[![:space:]]*}"}',
            '    line=${line%"${line##*[![:space:]]}"}',
            '    case "$line" in',
            "      ''|\\#*) continue ;;",
            "    esac",
            "    key=${line%%=*}",
            "    value=${line#*=}",
            "    key=${key#export }",
            '    key=${key#"${key%%[![:space:]]*}"}',
            '    key=${key%"${key##*[![:space:]]}"}',
            '    case "$key" in',
            "      WHATSAPP_WAKE_ENABLED|WHATSAPP_WAKE_URL|WHATSAPP_WAKE_AUTHORIZATION|WHATSAPP_WAKE_ALLOWLIST_LABEL|WHATSAPP_WAKE_ROUTINE_AUTHORIZATION|WHATSAPP_WAKE_STORE|WHATSAPP_WAKE_BRIDGE_TRACE|WHATSAPP_WAKE_WIRE|WHATSAPP_WAKE_TRANSPORT)",
            "        ;;",
            "      *) continue ;;",
            "    esac",
            '    value=${value#"${value%%[![:space:]]*}"}',
            '    value=${value%"${value##*[![:space:]]}"}',
            '    case "$value" in',
            '      \\"*\\") value=${value#\\"}; value=${value%\\"} ;;',
            "      \\'*\\') value=${value#\\'}; value=${value%\\'} ;;",
            "    esac",
            '    export "$key=$value"',
            '  done < "$envfile"',
            "fi",
            f"exec {shlex.quote(python)} -u -m wake bridge",
            "",
        ]
    )


def _native_manifest(wrapper: Path, extension_id: str) -> bytes:
    payload = {
        "name": HOST_NAME,
        "description": "Local page-change wake receiver for one extension. It does not send WhatsApp messages.",
        "path": str(wrapper),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _read_list(path: Path) -> set[str]:
    if path.is_symlink() or not path.is_file():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if _MODULE.fullmatch(line):
            names.add(line)
    return names


def _unlink_entry(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    return False


def _remove_pycache(package: Path) -> None:
    cache = package / "__pycache__"
    if not cache.is_dir() or cache.is_symlink():
        return
    for child in cache.iterdir():
        if (child.is_symlink() or child.is_file()) and child.suffix == ".pyc":
            child.unlink()
    _rmdir_if_empty(cache)


def _rmdir_if_empty(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        return
    if any(path.iterdir()):
        return
    path.rmdir()


def _remove_manifest(path: Path, wrapper: str) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or data.get("name") != HOST_NAME or data.get("path") != wrapper:
        return False
    path.unlink()
    return True


def _credential_file(home: Path) -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME") or ""
    base = Path(raw) if raw else home / ".config"
    return base / "draft-bridge" / "wake.env"


def _absent() -> str:
    return "\n".join(
        [
            "install-check: absent",
            "install-proven: absent",
            "install-evidence: installed-copy",
            "browser-loaded: no",
            "template-installed: no",
            "response-recorder: not-in-this-package",
            "bot-response: unproven",
            "webhook-probe: not-run",
            "whatsapp-session: not-run",
            "fresh-setup: unproven",
            "sends-whatsapp: no",
            "",
        ]
    )


def _parse_stamp(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        if key in {"format", "host", "extension", "contract"} and key not in values:
            values[key] = value
    return values


def _host_version(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    match = _HOST_VERSION.search(text)
    return match.group(1) if match else ""


def _regular_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _wrapper_matches(text: str, runtime: Path) -> bool:
    expected = f"export PYTHONPATH={shlex.quote(str(runtime))}${{PYTHONPATH:+:$PYTHONPATH}}"
    if expected not in text.splitlines():
        return False
    for line in text.splitlines():
        if line.startswith("exec ") and line.endswith(" -u -m wake bridge"):
            try:
                parts = shlex.split(line)
            except ValueError:
                return False
            return len(parts) == 6 and parts[2:6] == ["-u", "-m", "wake", "bridge"] and Path(parts[1]).is_file()
    return False


def _origins(config: Path, wrapper: Path) -> str:
    seen = []
    for product in PRODUCTS:
        path = config / product / "NativeMessagingHosts" / f"{HOST_NAME}.json"
        if path.is_symlink() or not path.is_file():
            return "missing"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return "unreadable"
        origins = data.get("allowed_origins") if isinstance(data, dict) else None
        if data.get("path") != str(wrapper) or data.get("name") != HOST_NAME or not isinstance(origins, list) or len(origins) != 1:
            return "mismatch"
        origin = origins[0]
        if not isinstance(origin, str) or not origin.startswith("chrome-extension://") or not origin.endswith("/"):
            return "mismatch"
        if not _ID.fullmatch(origin[len("chrome-extension://") : -1]):
            return "mismatch"
        seen.append(origin)
    if len(set(seen)) != 1:
        return "mismatch"
    return "one"


def _import_version(runtime: Path) -> str:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(runtime),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-c", "import wake; from wake import bridge; print(wake.__version__)"],
            cwd=str(runtime),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _dist_line(dist: Path | None, extension_version: str) -> str:
    if dist is None:
        return "extension-dist: not-checked"
    path = dist / "manifest.json"
    if path.is_symlink() or not path.is_file():
        return "extension-dist: absent"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "extension-dist: mismatch"
    if isinstance(data, dict) and data.get("version") == extension_version:
        return "extension-dist: match"
    return "extension-dist: mismatch"
