"""Redacted diagnosis and local rollback. Nothing here calls a webhook.

``install-proven: no`` means the tree check is not a completed installation.
``bot-response: unproven`` means this package has not recorded a draft from
the user's routine. It does not mean that routine cannot draft.
``approved-delivery: disabled`` is the separate send gate. It stays off.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from wake import __version__
from wake.bridge import read_handshake, read_host
from wake.config import load_config, valid_url
from wake.composer import composer_event, composer_state
from wake.evidence import CONTRACT
from wake.ledger import summary as late_summary
from wake.recovery import (
    apply_relink,
    binding_state,
    disk_status,
    note_restart,
    unlink_regular,
    unresolved_count,
)
from wake.scope import MODES
from wake.setupcheck import _extension_version, _send_armed

RUNTIME_NAMES = (
    "STOP",
    "binding.json",
    "composer-sample.json",
    "drafts.json",
    "event-ids.json",
    "event-ledger.json",
    "handshake.json",
    "host.json",
    "latest-receipt.txt",
    "list-change.json",
    "list-window.json",
    "open-permit.json",
    "opened-events.json",
    "outbox.json",
    "pane-hint.json",
    "person-counts.json",
    "person-sessions.json",
    "read-drafts.json",
    "read-window.json",
    "receipts.jsonl",
)


def diagnose(env: dict, store: Path, root: Path, loaded_extension: str = "", restart: str = "not-run") -> tuple:
    config = load_config(env)
    host = read_host(store)
    linked = binding_state(store) == "set"
    state, reason = disk_status(host["phase"], host.get("live") or "unverified", linked)
    if state == "ready":
        state, reason = "recovering", "page-not-observed"
    if restart not in {"not-run", "kept", "unchanged", "capped", "skipped-host-live", "unreadable", "absent"}:
        restart = "not-run"
    count = unresolved_count(store)
    extension, problem = _extension_version(root)
    if loaded_extension == "":
        pair = "unchecked"
    elif extension and loaded_extension == extension:
        pair = "match"
    else:
        pair = "mismatch"
    armed = _send_armed(root)
    lines = [
        "doctor: public",
        "install-proven: no",
        "package-check: tree-only",
        f"browser: {state}",
        f"browser-reason: {reason}",
        "browser-integration: not-wired",
        "page-observed: no",
        f"sample-at: {_sample_at(store, host.get('live') or 'unverified')}",
        f"restart: {restart}",
        f"receiver: {_receiver(config)}",
        "routine: external",
        "routine-response: unproven",
        f"composer: {composer_state(store)}",
        f"composer-event: {composer_event(store)}",
        "response-absence: not-inability",
        f"correlation: {_correlation(store)}",
        f"approved-delivery: {'blocked-send-armed' if armed == 'true' else 'disabled'}",
        f"live-send-armed: {armed}",
        f"unresolved: {count if count is not None else 'unreadable'}",
        f"late-events: {late_summary(store)}",
        f"binding: {binding_state(store)}",
        f"scope-mode: {_scope_mode(store)}",
        f"retained: {_retained(store)}",
        f"pair: extension={extension or 'unreadable'} host={__version__} contract={CONTRACT}",
        f"extension-pair: {pair}",
        "rollback: reload-this-checkout",
        "secrets-printed: no",
        "webhook-probe: not-run",
        "whatsapp-session: not-run",
    ]
    if problem:
        lines.append("manifest: unreadable")
    code = 1 if armed == "true" else 0
    text = "\n".join(lines) + "\n"
    if not _redacted(text, config):
        return 1, "doctor: blocked\nreason: report-would-include-a-secret\n"
    return code, text


def rollback_report(store: Path, root: Path, loaded_extension: str = "", drop: bool = False) -> tuple:
    extension, _problem = _extension_version(root)
    if loaded_extension == "":
        pair = "unchecked"
    elif extension and loaded_extension == extension:
        pair = "match"
    else:
        pair = "mismatch"
    removed = []
    if drop:
        removed = drop_local_state(store)
        drop_line = "drop: " + (",".join(removed) if removed else "none")
    else:
        drop_line = "drop: not-run"
    lines = [
        "rollback: plan",
        "code: reload-unpacked-extension-from-this-checkout",
        f"pair: extension={extension or 'unreadable'} host={__version__} contract={CONTRACT}",
        f"extension-pair: {pair}",
        f"retained: {_retained(store)}",
        drop_line,
        "secrets: kept-outside-the-runtime-names",
        "whatsapp-session: not-unlinked",
        "approved-delivery: disabled",
        "install-proven: no",
    ]
    return 0, "\n".join(lines) + "\n"


def recover(env: dict, store: Path, root: Path, *, logged_out: bool = False, identity: str = "") -> tuple:
    """Restart from the store. Operator flags only drop a binding.

    They are not a page observation, and the report is never ready.
    """

    restart = note_restart(store)
    operator = "none"
    if restart != "skipped-host-live" and (logged_out or identity == "mismatch"):
        apply_relink(store)
        operator = "logged-out" if logged_out else "identity-mismatch"
    code, text = diagnose(env, store, root, restart=restart)
    if "browser: ready\n" in text:
        return 1, "doctor: blocked\nreason: disk-cannot-be-ready\n"
    text = text.replace("page-observed: no\n", f"page-observed: no\noperator-relink: {operator}\n", 1)
    return code, text


def drop_local_state(store: Path) -> list:
    directory = Path(store)
    if directory.is_symlink() or not directory.is_dir():
        return []
    removed = []
    for name in RUNTIME_NAMES:
        if "/" in name or name in {"", ".", ".."}:
            continue
        path = directory / name
        if path.parent != directory:
            continue
        if unlink_regular(path):
            removed.append(name)
    return removed


def _sample_at(store: Path, host_live: str) -> str:
    stamp = read_handshake(store).get("at") or "none"
    if stamp == "none":
        return "absent"
    try:
        parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return "invalid"
    if parsed > datetime.now(timezone.utc).timestamp() + 120:
        return "invalid"
    if host_live != "yes":
        return "stale"
    return "not-a-page-proof"


def _receiver(config) -> str:
    if config.url and valid_url(config.url) and config.authorization:
        return "not-probed"
    return "unconfigured"


def _correlation(store: Path) -> str:
    box_path = Path(store) / "outbox.json"
    if not box_path.is_file() or box_path.is_symlink():
        return "none"
    try:
        data = json.loads(box_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "none"
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return "none"
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("state") == "acked" and item.get("reason") == "transport-accepted":
            return "local-transport"
        draft = item.get("draft")
        if isinstance(draft, dict) and draft.get("handler") == "local-mock-handler":
            return "local-test-fixture"
    return "none"


def _scope_mode(store: Path) -> str:
    path = Path(store) / "scope.json"
    if not path.is_file() or path.is_symlink():
        return "absent"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "unreadable"
    mode = data.get("mode") if isinstance(data, dict) else None
    if mode in MODES:
        return mode
    return "absent"


def _retained(store: Path) -> str:
    directory = Path(store)
    if not directory.is_dir():
        return "none"
    found = [name for name in RUNTIME_NAMES if (directory / name).is_file() and not (directory / name).is_symlink()]
    if (directory / "scope.json").is_file() and not (directory / "scope.json").is_symlink():
        found.append("scope.json")
    if not found:
        return "none"
    return ",".join(sorted(found))


def _redacted(text: str, config) -> bool:
    for secret in (config.url, config.authorization, config.routine_authorization):
        if secret and secret in text:
            return False
    return True
