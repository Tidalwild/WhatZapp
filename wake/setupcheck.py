"""Public setup check. It does not call a webhook and does not print secrets.

A clean tree can pass this check with no credential file. Passing it does
not mean a browser is linked, a routine answered, or a message was sent.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from wake import __version__
from wake.config import load_config, transmission_ready
from wake.evidence import (
    CONTRACT,
    from_client,
    from_reference_state,
    labels_cover_contract,
    response_blocker,
)
from wake.client import ClientResult

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path("examples/routine/reference_receiver.py")
SEND_LINE = "export const LIVE_SEND_ARMED = false;"


def run(env: dict, root: Path | None = None) -> int:
    code, text = report(env, root)
    print(text, end="")
    return code


def report(env: dict, root: Path | None = None) -> tuple:
    base = ROOT if root is None else Path(root)
    config = load_config(env)
    problems = []
    extension, extension_problem = _extension_version(base)
    if extension_problem:
        problems.append(extension_problem)
    readme = _readme_matches(base, extension)
    if extension and not readme:
        problems.append("readme-version")
    armed = _send_armed(base)
    if armed != "false":
        problems.append("send-armed")
    reference = _reference_state(base)
    if reference != "example-only":
        problems.append("reference")
    if sys.version_info < (3, 10):
        problems.append("python")
    if not labels_cover_contract():
        problems.append("labels")
    sample = from_client(ClientResult("acked", False, "transport"), "official")
    if sample.stage != "transport-accepted" or sample.proves_bot_response() or sample.proves_incoming():
        problems.append("transport-meaning")
    if from_reference_state("pending").proves_covered():
        problems.append("pending-covered")
    if from_reference_state("scheduled").proves_covered():
        problems.append("scheduled-covered")
    if from_reference_state("inflight").proves_covered():
        problems.append("inflight-covered")
    if response_blocker(sample) == "complete":
        problems.append("response-interface")
    node = _node_major()
    extension_build = "ready" if node.isdigit() and int(node) >= 20 else "blocked"
    lines = [
        "setup-check: public",
        f"contract: {CONTRACT}",
        f"python: {'ok' if sys.version_info >= (3, 10) else 'too-old'}",
        f"extension: {extension or 'unreadable'}",
        f"extension-readme: {'match' if readme else 'mismatch'}",
        f"host: {__version__}",
        "included-bot: no",
        "sends-whatsapp: no",
        f"live-send-armed: {armed}",
        f"reference-receiver: {reference}",
        "response-recorder: not-in-this-package",
        "bot-response: unproven",
        "authorship: unproven",
        "draft-interface: page-composer",
        "candidate: draft-only",
        "http-2xx-means: transport-accepted",
        "install-proven: no",
        "install-evidence: tree-only",
        "queued-means: not-covered",
        "fresh-setup: unproven",
        f"webhook: {'configured' if config.url else 'missing'}",
        f"allowlist: {'set' if config.label else 'missing'}",
        f"transmission: {'configured' if transmission_ready(config) else 'blocked'}",
        f"mock-handler: {'local-mock-handler' if config.transport == 'test-receipt' else 'off'}",
        "language-default: en",
        "language-supported: zh-Hant",
        f"extension-build: {extension_build}",
        f"node: {node}",
        "webhook-probe: not-run",
        "whatsapp-session: not-run",
    ]
    if problems:
        lines.append("result: blocked")
        lines.append("blocked: " + ",".join(problems))
        code = 1
    else:
        lines.append("result: public-package-ok")
        code = 0
    text = "\n".join(lines) + "\n"
    if not _redacted(text, config):
        return 1, "setup-check: blocked\nreason: report-would-include-a-secret\n"
    return code, text


def _extension_version(root: Path) -> tuple:
    path = root / "web" / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "", "manifest"
    version = data.get("version")
    if not isinstance(version, str) or not version or any(char.isspace() for char in version):
        return "", "manifest"
    return version, ""


def _readme_matches(root: Path, version: str) -> bool:
    if not version:
        return False
    path = root / "README.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return f"Current extension version: **{version}**." in text


def _send_armed(root: Path) -> str:
    path = root / "web" / "src" / "replyDelivery.ts"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "unreadable"
    if SEND_LINE in text.splitlines():
        return "false"
    if "LIVE_SEND_ARMED = true" in text:
        return "true"
    return "unreadable"


def _reference_state(root: Path) -> str:
    path = root / REFERENCE
    if not path.is_file():
        return "missing"
    if _host_imports_reference(root):
        return "imported-by-host"
    return "example-only"


def _host_imports_reference(root: Path) -> bool:
    roots = (root / "wake", root / "web" / "src")
    for base in roots:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".ts", ".js"} or not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                return True
            for line in lines:
                if _imports_example(line):
                    return True
    return False


def _imports_example(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*"):
        return False
    if "import" not in stripped:
        return False
    name = "reference_" + "receiver"
    package = "examples." + "routine"
    return name in stripped or package in stripped


def _node_major() -> str:
    binary = shutil.which("node")
    if not binary:
        return "absent"
    try:
        completed = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unreadable"
    text = (completed.stdout or "").strip()
    if not text.startswith("v"):
        return "unreadable"
    major = text[1:].split(".", 1)[0]
    if not major.isdigit():
        return "unreadable"
    return major


def _redacted(text: str, config) -> bool:
    for secret in (config.url, config.authorization, config.routine_authorization):
        if secret and secret in text:
            return False
    return True
