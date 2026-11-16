import argparse
import json
import os
import sys
import time
from pathlib import Path

from wake.bridge import HOST_NAME, read_handshake, read_host, run_stdio, store_path
from wake.resolve import permit_open
from wake.client import WebhookClient
from wake.clock import Clock, iso
from wake.config import load_config, transmission_ready, valid_url
from wake.envelope import build, new_event_id
from wake.doctor import diagnose, recover, rollback_report
from wake.setupcheck import run as setup_check
from wake.lifecycle import (
    ObserveOptions,
    clear_stop,
    outbox_stopped,
    request_stop,
    session_bus_address,
    stop_requested,
)
from wake.log import Log
from wake.observe import monitor, notifications_service, user_bus_available
from wake.outbox import Outbox
from wake.page import apply_page
from wake.pipeline import Pipeline
from wake.policy import valid_label
from wake.read import bind_local, bind_metadata, load_binding, read_snapshot
from wake.routine import DEFAULT_STORE, RoutineStore, serve
from wake.schedule import flush_until, outstanding

BLOCKED = "blocked: webhook is not configured. Nothing was sent."
STOPPED = "blocked: capture is stopped. Run python3 -m wake resume. Nothing was sent."


def main(argv=None, env=None) -> int:
    args = list(sys.argv if argv is None else argv)
    source = os.environ if env is None else env
    command = args[1] if len(args) > 1 else "status"
    rest = args[2:]
    if command == "setup-check":
        return setup_check(source)
    if command == "doctor":
        return _doctor_command(source, rest)
    if command == "recover":
        return _recover_command(source, rest)
    if command == "rollback":
        return _rollback_command(source, rest)
    if command == "status":
        return status(source)
    if command == "probe":
        return probe(source)
    if command == "observe":
        options = _observe_options(rest)
        if options is None:
            return 2
        return observe(source, options)
    if command == "stop":
        return stop(source)
    if command == "resume":
        return resume(source)
    if command == "flush":
        seconds = _bounded_seconds(rest, allow_zero=True, limit=120)
        if seconds is None:
            return 2
        return flush(source, seconds)
    if command == "ingest":
        return _ingest_command(source, rest)
    if command == "bind":
        return _bind_command(rest)
    if command == "read":
        return _read_command(rest)
    if command == "page":
        return _page_command(source, rest)
    if command == "bridge":
        return bridge(source)
    if command == "routine":
        return routine(source)
    if command == "permit-open":
        return permit_open_command(source, rest)
    print(
        "usage: python -m wake "
        "[setup-check|doctor|recover|rollback|status|probe|observe|stop|resume|flush|ingest|bind|read|page|bridge|routine|permit-open]"
    )
    return 2


def status(env: dict) -> int:
    config = load_config(env)
    print(f"enabled: {'yes' if config.enabled else 'no'}")
    print(f"transmission: {'configured' if transmission_ready(config) else 'blocked'}")
    print(f"auth: {config.auth_form}")
    print(f"allowlist: {'set' if valid_label(config.label) else 'missing'}")
    print(f"wake-wire: {config.wire}")
    print(f"wake-transport: {config.transport}")
    print(f"desktop-bus: {'present' if user_bus_available(env) else 'absent'}")
    print(f"notifications-service: {notifications_service(env)}")
    print(f"capture: {'stopped' if _capture_stopped(DEFAULT_STORE) else 'armed'}")
    print(f"read-binding: {'set' if load_binding(DEFAULT_STORE) else 'missing'}")
    print("verified-remote-recipient: no")
    if config.transport == "test-receipt":
        print("mock-handler: local-mock-handler")
    else:
        print("mock-handler: off")
    print("included-bot: no")
    print("sends-whatsapp: no")
    print("chat-read: no")
    print(f"page-bridge: {'manifest-present' if _bridge_manifest_present(env) else 'manifest-absent'}")
    try:
        handshake_store = store_path(env)
    except ValueError:
        handshake_store = DEFAULT_STORE
    handshake = read_handshake(handshake_store)
    print(f"hello: {handshake['hello']}")
    print(f"scope: {handshake['scope']}")
    print(f"list: {handshake['list']}")
    recent = handshake.get("listRecent") or []
    print("list-recent: " + (" ".join(recent) if recent else "none"))
    change = handshake.get("change") or "none"
    count = handshake.get("count")
    if isinstance(count, int) and not isinstance(count, bool):
        print(f"count: {count}")
    elif change == "held":
        print("count: held")
    else:
        print("count: none")
    print(f"change: {change}")
    stored = handshake.get("stored")
    if isinstance(stored, int) and not isinstance(stored, bool):
        print(f"stored-count: {stored}")
    else:
        print("stored-count: none")
    print(f"sample-posted: {'yes' if handshake['posted'] else 'no'}")
    print(f"handshake-posted: {'yes' if handshake['posted'] else 'no'}")
    print(f"forward: {handshake.get('forward') or 'none'}")
    print(f"event: {handshake.get('event') or 'none'}")
    print(f"last-forward: {handshake.get('lastForward') or 'none'}")
    print(f"last-event: {handshake.get('lastEvent') or 'none'}")
    print(f"last-at: {handshake.get('lastAt') or 'none'}")
    print("ack-means: webhook-not-chat")
    host_state = read_host(handshake_store)
    print(f"host-phase: {host_state['phase']}")
    print(f"host-live: {host_state.get('live') or 'unverified'}")
    print(f"host-cause: {host_state['cause']}")
    print(f"host-detail: {host_state['detail']}")
    if _capture_stopped(DEFAULT_STORE):
        print(STOPPED)
        return 2
    if not config.enabled or not config.authorization.strip() or not valid_url(config.url):
        print(BLOCKED)
        return 2
    if not valid_label(config.label):
        print("blocked: allowlist label is missing. Nothing was sent.")
        return 2
    return 0


def probe(env: dict) -> int:
    config = load_config(env)
    if not config.enabled or not config.authorization.strip() or not valid_url(config.url):
        print(BLOCKED)
        return 2
    if _capture_stopped(DEFAULT_STORE):
        print(STOPPED)
        return 2
    payload = build(
        event_id=new_event_id(),
        source="manual-connectivity-probe",
        observed_at=iso(Clock().now()),
    )
    result = WebhookClient(config.url, config.authorization, mode=config.transport).post(payload)
    if result.status != "acked":
        print("receiver did not accept the probe. Nothing was sent to WhatsApp.")
        return 1
    print("connectivity-probe: answered")
    print(f"eventId: {payload['eventId']}")
    print(f"classification: {result.classification}")
    if result.classification == "transport":
        print("unique: not-read")
    elif result.classification == "legacy-409":
        print("unique: legacy-409")
    else:
        print(f"unique: {'no' if result.duplicate else 'yes'}")
    print("not-a-whatsapp-notification: true")
    print("chat-read: no")
    print("whatsapp-send: no")
    return 0


def observe(env: dict, options: ObserveOptions | None = None) -> int:
    options = options or ObserveOptions()
    store = Path(options.store)
    if stop_requested(store) or outbox_stopped(store):
        print(STOPPED)
        return 2
    if not user_bus_available(env):
        print(
            "blocked: no user session notification bus. "
            "A private test bus is not this desktop. Nothing was sent."
        )
        return 2
    config = load_config(env)
    if not transmission_ready(config):
        print(BLOCKED)
        return 2
    address = session_bus_address(env)
    if not address:
        print("blocked: session bus address is missing. Nothing was sent.")
        return 2
    pipeline = _pipeline(store, config)
    stop_flag = _Stop()
    started = time.monotonic()
    matched = {"seen": False}

    def tick() -> None:
        if stop_requested(store):
            pipeline.stop()
            stop_flag.event.set()
            return
        if options.seconds is not None and time.monotonic() - started >= options.seconds:
            stop_flag.event.set()
            return
        pipeline.flush()
        if options.once and matched["seen"] and not outstanding(pipeline.outbox):
            stop_flag.event.set()

    def handler(item) -> None:
        result = pipeline.handle(item)
        pipeline.flush()
        if result.disposition in ("enqueued", "replaced"):
            matched["seen"] = True
        if options.once and matched["seen"] and not outstanding(pipeline.outbox):
            stop_flag.event.set()

    if options.once or options.seconds is not None:
        print("lifecycle: finite")
    else:
        print("lifecycle: until-stop")
    print(
        "observing Notify calls whose summary equals the allowlist token. "
        "The app name is not a filter and is not WhatsApp authentication. "
        "A browser may never emit this signal. WhatsApp send is off."
    )
    try:
        monitor(
            address,
            handler,
            stop_flag.event,
            allowlist=config.label,
            on_tick=tick,
        )
    except KeyboardInterrupt:
        stop_flag.event.set()
    finally:
        pipeline.note_disconnect()
    print("observe-exited: yes")
    print("sends-whatsapp: no")
    return 0


def stop(_env: dict, store: Path = DEFAULT_STORE) -> int:
    request_stop(store)
    print("capture: stopped")
    print("transmission: stopped")
    print("sends-whatsapp: no")
    return 0


def resume(_env: dict, store: Path = DEFAULT_STORE) -> int:
    if not clear_stop(store):
        print("blocked: outbox is corrupt. It was not cleared and nothing was sent.")
        return 2
    print("capture: armed")
    print("transmission: still requires the enabled switch")
    print("sends-whatsapp: no")
    return 0


def flush(env: dict, seconds: float, store: Path = DEFAULT_STORE) -> int:
    if stop_requested(store) or outbox_stopped(store):
        print(STOPPED)
        return 2
    config = load_config(env)
    if not transmission_ready(config):
        print(BLOCKED)
        return 2
    pipeline = _pipeline(store, config)
    if seconds <= 0:
        pipeline.flush()
        outcome = "settled" if not outstanding(pipeline.outbox) else "pending"
    else:
        outcome = flush_until(pipeline, seconds=seconds, sleep=time.sleep, now=time.monotonic)
    print(f"flush: {outcome}")
    print("sends-whatsapp: no")
    return 0 if outcome in ("settled", "idle") else 1


def ingest(
    env: dict,
    *,
    package: str,
    notification_key: str,
    title: str,
    store: Path = DEFAULT_STORE,
    seconds: float = 0,
) -> int:
    if stop_requested(store) or outbox_stopped(store):
        print(STOPPED)
        return 2
    config = load_config(env)
    if not transmission_ready(config):
        print(BLOCKED)
        return 2
    pipeline = _pipeline(store, config)
    result = pipeline.handle_listener(
        package=package,
        notification_key=notification_key,
        title=title,
        post_time_ms=None,
    )
    if seconds > 0 and result.disposition in ("enqueued", "replaced"):
        outcome = flush_until(pipeline, seconds=seconds, sleep=time.sleep, now=time.monotonic)
        print(f"flush: {outcome}")
    else:
        pipeline.flush()
    print(f"disposition: {result.disposition}")
    print(f"reason: {result.reason}")
    if result.event_id:
        print(f"eventId: {result.event_id}")
    print("phone-install: no")
    print("sends-whatsapp: no")
    print("chat-read: no")
    return 0 if result.disposition in ("enqueued", "replaced") else 1


def bind(header: str, self_label: str, store: Path = DEFAULT_STORE) -> int:
    return _print_bind(bind_local(store, header, self_label))


def bind_scope(header: str, store: Path = DEFAULT_STORE) -> int:
    return _print_bind(bind_metadata(store, header))


def _print_bind(result: tuple) -> int:
    _binding, reason = result
    print(f"binding: {reason}")
    print("verified-remote-recipient: no")
    print("sends-whatsapp: no")
    if _binding is not None:
        print(f"mode: {_binding.get('mode', 'messages')}")
        print(f"direction: {'unproven' if _binding.get('mode') == 'metadata' else 'proven'}")
    return 0 if reason == "BOUND" else 2


def read(snapshot_path: Path, event_id: str | None = None, store: Path = DEFAULT_STORE) -> int:
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("disposition: UNREADABLE_SNAPSHOT")
        print("draft: no")
        print("verified-remote-recipient: no")
        print("live-whatsapp: no")
        print("sends-whatsapp: no")
        return 2
    box = Outbox(Path(store) / "outbox.json", Clock())
    result = read_snapshot(store, snapshot, box, event_id)
    print(f"disposition: {result['disposition']}")
    print(f"draft: {'yes' if result['draft'] else 'no'}")
    if result.get("ack"):
        print(f"ack: {result['ack']}")
    print("verified-remote-recipient: no")
    print("live-whatsapp: no")
    print("sends-whatsapp: no")
    if result["disposition"] == "ONE_INBOUND":
        return 0
    if result["disposition"] in ("BASELINE", "NO_NEW", "CONTEXT_ONLY"):
        return 0
    return 1


def page(env: dict, snapshot_path: Path, store: Path = DEFAULT_STORE) -> int:
    if stop_requested(store) or outbox_stopped(store):
        print(STOPPED)
        return 2
    config = load_config(env)
    if not transmission_ready(config):
        print(BLOCKED)
        return 2
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("disposition: UNREADABLE_SNAPSHOT")
        print("posted: no")
        print("draft: no")
        print("sends-whatsapp: no")
        return 2
    result = apply_page(store, snapshot, allowlist=config.label, pipeline=_pipeline(store, config))
    print(f"disposition: {result['disposition']}")
    print(f"signal: {result['signal']}")
    print(f"posted: {'yes' if result['posted'] else 'no'}")
    print(f"draft: {'yes' if result['draft'] else 'no'}")
    if result.get("ack"):
        print(f"ack: {result['ack']}")
    print("verified-remote-recipient: no")
    print("live-whatsapp: no")
    print("sends-whatsapp: no")
    if result["posted"] and result["disposition"] in ("ONE_INBOUND", "ONE_UNREAD"):
        return 0
    if result["disposition"] in ("BASELINE", "NO_NEW", "CONTEXT_ONLY", "READ_CLEARED", "REORDER_ONLY", "ALREADY_UNREAD"):
        return 0
    return 1


def bridge(env: dict) -> int:
    """Speak Chrome native messaging on stdin/stdout. Diagnostics stay on stderr."""

    config = load_config(env)
    sys.stderr.write("bridge: listening\n")
    sys.stderr.write("sends-whatsapp: no\n")
    sys.stderr.write(f"host: {HOST_NAME}\n")
    pipeline = Pipeline(
        outbox=Outbox(store_path(env) / "outbox.json", Clock()),
        allowlist=config.label,
        enabled=bool(config.enabled),
        client=WebhookClient(config.url, config.authorization, mode=config.transport) if transmission_ready(config) else None,
        log=Log(),
    )
    try:
        return run_stdio(env, sys.stdin.buffer, sys.stdout.buffer, pipeline)
    except BrokenPipeError:
        return 0


def _bridge_manifest_present(env: dict) -> bool:
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    name = f"{HOST_NAME}.json"
    for product in ("google-chrome", "google-chrome-for-testing", "chromium"):
        if Path(base, product, "NativeMessagingHosts", name).exists():
            return True
    return False


def routine(env: dict) -> int:
    config = load_config(env)
    if not config.routine_authorization:
        print("blocked: routine authorization is not configured. The listener was not started.")
        return 2
    store = RoutineStore(DEFAULT_STORE, config.routine_authorization)
    server = serve(store, "127.0.0.1", int(env.get("WHATSAPP_WAKE_ROUTINE_PORT") or "8791"))
    print(f"routine: 127.0.0.1:{server.server_address[1]}")
    print("reads-chat: no")
    print("sends-whatsapp: no")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


def _pipeline(store: Path, config) -> Pipeline:
    return Pipeline(
        outbox=Outbox(Path(store) / "outbox.json", Clock()),
        allowlist=config.label,
        enabled=True,
        client=WebhookClient(config.url, config.authorization, mode=config.transport),
        log=Log(),
    )


def _capture_stopped(store: Path) -> bool:
    return stop_requested(store) or outbox_stopped(store)


def _observe_options(rest: list) -> ObserveOptions | None:
    parser = argparse.ArgumentParser(prog="wake observe", add_help=False)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--seconds", type=float, default=None)
    try:
        parsed = parser.parse_args(rest)
    except SystemExit:
        print("blocked: observe accepts --once and --seconds. Nothing was sent.")
        return None
    if parsed.seconds is not None and not (1 <= parsed.seconds <= 600):
        print("blocked: --seconds must be from 1 to 600. Nothing was sent.")
        return None
    return ObserveOptions(once=bool(parsed.once), seconds=parsed.seconds)


def _bounded_seconds(rest: list, *, allow_zero: bool, limit: float):
    parser = argparse.ArgumentParser(prog="wake flush", add_help=False)
    parser.add_argument("--seconds", type=float, default=0 if allow_zero else None)
    try:
        parsed = parser.parse_args(rest)
    except SystemExit:
        print("blocked: flush accepts --seconds. Nothing was sent.")
        return None
    seconds = parsed.seconds
    if seconds is None:
        print("blocked: --seconds is required. Nothing was sent.")
        return None
    floor = 0 if allow_zero else 1
    if not (floor <= seconds <= limit):
        print(f"blocked: --seconds must be from {floor:g} to {limit:g}. Nothing was sent.")
        return None
    return float(seconds)


def _ingest_command(env: dict, rest: list) -> int:
    if any(arg == "--body" or arg.startswith("--body=") for arg in rest):
        print("blocked: message text is not accepted. Nothing was stored.")
        return 2
    parser = argparse.ArgumentParser(prog="wake ingest", add_help=False)
    parser.add_argument("--package", required=True)
    parser.add_argument("--notification-key", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--seconds", type=float, default=0)
    try:
        parsed = parser.parse_args(rest)
    except SystemExit:
        print("blocked: ingest requires --package and --notification-key. Nothing was stored.")
        return 2
    if not (0 <= parsed.seconds <= 120):
        print("blocked: --seconds must be from 0 to 120. Nothing was stored.")
        return 2
    return ingest(
        env,
        package=parsed.package,
        notification_key=parsed.notification_key,
        title=parsed.title,
        seconds=parsed.seconds,
    )


def permit_open_command(env: dict, rest: list) -> int:
    if len(rest) != 4 or rest[0] != "--event" or rest[2] != "--ref":
        print("usage: python -m wake permit-open --event EVENT --ref REF", file=sys.stderr)
        return 2
    code = permit_open(store_path(env), rest[1], rest[3], time.time())
    print(f"permit: {code}")
    return 0 if code == "OPEN_QUEUED" else 1


def _bind_command(rest: list) -> int:
    parser = argparse.ArgumentParser(prog="wake bind", add_help=False)
    parser.add_argument("--header", required=True)
    parser.add_argument("--self", dest="self_label")
    parser.add_argument("--metadata", action="store_true")
    try:
        parsed = parser.parse_args(rest)
    except SystemExit:
        print("blocked: bind requires --header and --self, or --header and --metadata. Nothing was stored.")
        return 2
    if parsed.metadata and parsed.self_label:
        print("blocked: metadata scope does not take a self label. Nothing was stored.")
        return 2
    if parsed.metadata:
        return bind_scope(parsed.header)
    if not parsed.self_label:
        print("blocked: bind requires --header and --self, or --header and --metadata. Nothing was stored.")
        return 2
    return bind(parsed.header, parsed.self_label)


def _page_command(env: dict, rest: list) -> int:
    parser = argparse.ArgumentParser(prog="wake page", add_help=False)
    parser.add_argument("--snapshot", required=True)
    try:
        parsed = parser.parse_args(rest)
    except SystemExit:
        print("blocked: page requires --snapshot. Nothing was sent.")
        return 2
    return page(env, Path(parsed.snapshot))


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _doctor_command(env: dict, rest: list) -> int:
    if rest:
        print("usage: python -m wake doctor")
        return 2
    code, text = diagnose(env, store_path(env), _package_root())
    print(text, end="")
    return code


def _recover_command(env: dict, rest: list) -> int:
    logged_out = False
    identity = "unchecked"
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--logged-out":
            logged_out = True
            index += 1
            continue
        if token == "--identity" and index + 1 < len(rest) and rest[index + 1] == "mismatch":
            identity = "mismatch"
            index += 2
            continue
        print("usage: python -m wake recover [--logged-out] [--identity mismatch]")
        return 2
    code, text = recover(env, store_path(env), _package_root(), logged_out=logged_out, identity=identity)
    print(text, end="")
    return code


def _rollback_command(env: dict, rest: list) -> int:
    if rest == ["--drop-local-state"]:
        drop = True
    elif not rest:
        drop = False
    else:
        print("usage: python -m wake rollback [--drop-local-state]")
        return 2
    _code, text = rollback_report(store_path(env), _package_root(), drop=drop)
    print(text, end="")
    return 0


def _read_command(rest: list) -> int:
    parser = argparse.ArgumentParser(prog="wake read", add_help=False)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--event", default=None)
    try:
        parsed = parser.parse_args(rest)
    except SystemExit:
        print("blocked: read requires --snapshot. Nothing was stored.")
        return 2
    return read(Path(parsed.snapshot), parsed.event)


class _Stop:
    def __init__(self) -> None:
        import threading

        self.event = threading.Event()


if __name__ == "__main__":
    sys.exit(main())
