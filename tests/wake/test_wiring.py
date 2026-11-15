import json
import os
import threading
import unittest
from pathlib import Path

from wake.__main__ import ingest, main, observe, probe, status
from wake.client import WebhookClient
from wake.config import authorization_value, load_config
from wake.envelope import build
from wake.lifecycle import ObserveOptions, request_stop, session_bus_address
from wake.observe import monitor
from wake.outbox import Item
from wake.read import bind_local, read_snapshot
from wake.routine import RoutineStore, serve
from wake.schedule import flush_until
from tests.wake.support import Scripted, observation, pipeline, start_private_bus

TOKEN = "local-test-only"
SECRET_TEXT = "private-body-991"
MARKER = "arrived-once-marker"


class WiringTests(unittest.TestCase):
    def test_pasted_header_name_is_removed_and_not_printed(self):
        value, form = authorization_value("  Authorization: Authorization: " + TOKEN + "  ")
        self.assertEqual(value, TOKEN)
        self.assertEqual(form, "normalized")
        bearer, bearer_form = authorization_value("Authorization: Bearer " + TOKEN)
        self.assertEqual(bearer, "Bearer " + TOKEN)
        self.assertEqual(bearer_form, "normalized")
        plain, plain_form = authorization_value(TOKEN)
        self.assertEqual(plain, TOKEN)
        self.assertEqual(plain_form, "value")
        env = {
            "WHATSAPP_WAKE_CONFIG": "",
            "WHATSAPP_WAKE_ENABLED": "1",
            "WHATSAPP_WAKE_URL": "https://routine.example/wake",
            "WHATSAPP_WAKE_AUTHORIZATION": "Authorization: " + TOKEN,
            "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
        }
        loaded = load_config(env)
        self.assertEqual(loaded.authorization, TOKEN)
        self.assertEqual(loaded.auth_form, "normalized")
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(status(env), 0)
        text = buffer.getvalue()
        self.assertIn("auth: normalized", text)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("routine.example", text)
        self.assertNotIn("Bearer", text)

    def test_prefixed_authorization_is_accepted_by_the_local_routine(self):
        directory = Path("/tmp/wake-auth-prefix")
        _clear(directory)
        store = RoutineStore(directory, TOKEN)
        server = serve(store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        env = {
            "WHATSAPP_WAKE_CONFIG": "",
            "WHATSAPP_WAKE_ENABLED": "1",
            "WHATSAPP_WAKE_URL": f"http://127.0.0.1:{server.server_address[1]}/",
            "WHATSAPP_WAKE_AUTHORIZATION": "Authorization: " + TOKEN,
            "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
        }
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = probe(env)
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("chat-read: no", text)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("Authorization:", text)
        ids = json.loads((directory / "event-ids.json").read_text(encoding="utf-8"))["ids"]
        self.assertEqual(len(ids), 1)

    def test_client_sends_the_value_once(self):
        transport = Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')])
        client = WebhookClient("http://127.0.0.1:9/", "Authorization: " + TOKEN, transport)
        payload = build(
            event_id="evt-" + "ab" * 16,
            source="manual-connectivity-probe",
            observed_at="2023-11-14T22:13:20Z",
        )
        result = client.post(payload)
        self.assertEqual(result.status, "acked")
        self.assertEqual(transport.calls[0]["authorization"], TOKEN)

    def test_retry_timer_waits_and_then_delivers(self):
        directory = Path("/tmp/wake-retry-timer")
        _clear(directory)
        transport = Scripted(
            [
                (503, b"{}"),
                (200, b'{"accepted":true,"unique":true,"duplicate":false}'),
            ]
        )
        made, clock, log, _transport = pipeline(directory, transport=transport)
        made.handle(observation())
        slept = []

        def sleep(step):
            slept.append(step)
            clock.advance(step)

        outcome = flush_until(made, seconds=10, sleep=sleep, now=clock.now)
        self.assertEqual(outcome, "settled")
        self.assertEqual(slept, [1.0])
        self.assertEqual(next(iter(made.outbox.items.values())).state, "acked")
        self.assertNotIn("127.0.0.1", log.text())
        self.assertNotIn(TOKEN, log.text())

    def test_stop_blocks_observe_before_a_monitor_starts(self):
        directory = Path("/tmp/wake-stop-observe")
        _clear(directory)
        request_stop(directory)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "WHATSAPP_WAKE_CONFIG": "",
            "WHATSAPP_WAKE_ENABLED": "1",
            "WHATSAPP_WAKE_URL": "http://127.0.0.1:9/",
            "WHATSAPP_WAKE_AUTHORIZATION": TOKEN,
            "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/wake-not-a-live-bus",
        }
        before = _monitors()
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = observe(env, ObserveOptions(store=directory, once=True, seconds=30))
        self.assertEqual(code, 2)
        self.assertIn("capture is stopped", buffer.getvalue())
        self.assertEqual(_monitors(), before)
        self.assertNotIn(TOKEN, buffer.getvalue())

    def test_tick_stops_a_scoped_monitor(self):
        directory = Path("/tmp/wake-finite-monitor")
        _clear(directory)
        daemon, address = start_private_bus(directory)
        seen = []
        stop = threading.Event()

        def tick():
            stop.set()

        try:
            monitor(address, seen.append, stop, allowlist="contact-a", on_tick=tick)
        finally:
            if daemon.poll() is None:
                daemon.terminate()
                daemon.wait(timeout=2)
        self.assertEqual(seen, [])

    def test_session_address_uses_the_env_or_the_socket(self):
        self.assertEqual(
            session_bus_address({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/example-bus"}),
            "unix:path=/tmp/example-bus",
        )
        resolved = session_bus_address(
            {"XDG_RUNTIME_DIR": "/tmp/runtime-wake"},
            path_exists=lambda path: path == "/tmp/runtime-wake/bus",
        )
        self.assertEqual(resolved, "unix:path=/tmp/runtime-wake/bus")
        self.assertEqual(session_bus_address({}, path_exists=lambda _path: False), "")

    def test_ingest_metadata_reaches_the_local_routine_without_a_body(self):
        directory = Path("/tmp/wake-ingest")
        _clear(directory)
        store = RoutineStore(directory / "routine", TOKEN)
        server = serve(store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        env = _ready(server.server_address[1])
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            refused = ingest(env, package="com.example", notification_key="listener-key-991", title="contact-a", store=directory)
        self.assertEqual(refused, 1)
        self.assertIn("reason: WRONG_PACKAGE", buffer.getvalue())
        self.assertFalse((directory / "routine" / "event-ids.json").exists())
        buffer = StringIO()
        with redirect_stdout(buffer):
            accepted = ingest(
                env,
                package="com.whatsapp",
                notification_key="listener-key-991",
                title="contact-a",
                store=directory,
            )
        text = buffer.getvalue()
        self.assertEqual(accepted, 0)
        self.assertIn("phone-install: no", text)
        self.assertIn("chat-read: no", text)
        self.assertNotIn("listener-key-991", text)
        self.assertNotIn(SECRET_TEXT, text)
        saved = (directory / "outbox.json").read_text(encoding="utf-8")
        self.assertNotIn("listener-key-991", saved)
        self.assertNotIn(SECRET_TEXT, saved)
        payload = json.loads(saved)["items"][0]["payload"]
        self.assertEqual(payload["source"], "android-listener")
        self.assertNotIn("body", payload)
        ids = json.loads((directory / "routine" / "event-ids.json").read_text(encoding="utf-8"))["ids"]
        self.assertEqual(len(ids), 1)

    def test_body_argument_is_refused_without_echoing_it(self):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO

        out = StringIO()
        err = StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["wake", "ingest", "--body", SECRET_TEXT, "--package", "com.whatsapp"],
                {"WHATSAPP_WAKE_CONFIG": "", "PATH": os.environ.get("PATH", "")},
            )
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET_TEXT, out.getvalue())
        self.assertNotIn(SECRET_TEXT, err.getvalue())

    def test_stop_blocks_ingest(self):
        directory = Path("/tmp/wake-ingest-stop")
        _clear(directory)
        request_stop(directory)
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = ingest(
                _ready(9),
                package="com.whatsapp",
                notification_key="listener-key-991",
                title="contact-a",
                store=directory,
            )
        self.assertEqual(code, 2)
        self.assertIn("capture is stopped", buffer.getvalue())
        self.assertFalse((directory / "outbox.json").read_text(encoding="utf-8").find("android-listener") >= 0)

    def test_read_drafts_one_new_inbound_and_drops_ambiguous_snapshots(self):
        directory = Path("/tmp/wake-read")
        _clear(directory)
        made, _clock, _log, _transport = pipeline(directory)
        made.handle(observation())
        made.flush()
        binding, reason = bind_local(directory, "fixture chat", "Me")
        self.assertEqual(reason, "BOUND")
        self.assertFalse(binding["verifiedRemoteRecipient"])
        baseline = read_snapshot(directory, _shot(_SEEDS), made.outbox)
        self.assertEqual(baseline["disposition"], "BASELINE")
        self.assertFalse(baseline["draft"])
        duplicate = read_snapshot(
            directory,
            _shot(_SEEDS + (("fixture chat", "one-text", "10:22 PM"), ("fixture chat", "other-text", "10:22 PM"))),
            made.outbox,
        )
        self.assertEqual(duplicate["disposition"], "AMBIGUOUS_CLOCK")
        self.assertFalse(duplicate["draft"])
        weekday = read_snapshot(
            directory,
            _shot(_SEEDS + (("fixture chat", MARKER, "Monday 10:22 PM"), ("fixture chat", MARKER, "Monday 10:22 PM"))),
            made.outbox,
        )
        self.assertEqual(weekday["disposition"], "TIME_AMBIGUOUS")
        burst = read_snapshot(
            directory,
            _shot(_SEEDS + (("fixture chat", "first-new", "09:02"), ("fixture chat", "second-new", "09:03"))),
            made.outbox,
        )
        self.assertEqual(burst["disposition"], "AMBIGUOUS_NEW")
        forged = read_snapshot(directory, _shot(_SEEDS + (("fixture chat", MARKER, "09:02"),), title="contact-a"), made.outbox)
        self.assertEqual(forged["disposition"], "UNTRUSTED_FIELD")
        switched = read_snapshot(directory, _shot([("Other chat", MARKER, "09:02")], header="Other chat"), made.outbox)
        self.assertEqual(switched["disposition"], "CHAT_SWITCH")
        drafted = read_snapshot(directory, _shot(_SEEDS + (("fixture chat", MARKER, "09:02"),)), made.outbox)
        self.assertEqual(drafted["disposition"], "ONE_INBOUND")
        self.assertTrue(drafted["draft"])
        self.assertFalse(drafted["verifiedRemoteRecipient"])
        self.assertFalse(drafted["liveWhatsApp"])
        saved = json.loads((directory / "read-drafts.json").read_text(encoding="utf-8"))["drafts"]
        self.assertEqual(len(saved), 1)
        self.assertFalse(saved[0]["sent"])
        self.assertFalse(saved[0]["sendingEnabled"])
        self.assertFalse(saved[0]["verifiedRemoteRecipient"])
        self.assertEqual(saved[0]["source"], "supplied-snapshot")
        blob = _tree(directory)
        for secret in (MARKER, "one-text", "other-text", "first-new", "second-new", "seed-one"):
            self.assertNotIn(secret, blob)

    def test_connectivity_probe_does_not_authorize_a_read(self):
        directory = Path("/tmp/wake-read-probe")
        _clear(directory)
        made, clock, _log, _transport = pipeline(directory)
        payload = build(
            event_id="evt-" + "cd" * 16,
            source="manual-connectivity-probe",
            observed_at="2023-11-14T22:13:20Z",
        )
        made.outbox.add(
            Item(
                event_id=payload["eventId"],
                payload=payload,
                state="acked",
                attempts=1,
                next_attempt_at=clock.now(),
                replaces_id=0,
                source=payload["source"],
                created_at=clock.now(),
                updated_at=clock.now(),
                acked_at=clock.now(),
                reason="acked",
                draft=None,
            )
        )
        bind_local(directory, "fixture chat", "Me")
        read_snapshot(directory, _shot(_SEEDS), made.outbox)
        result = read_snapshot(directory, _shot(_SEEDS + (("fixture chat", MARKER, "09:02"),)), made.outbox)
        self.assertEqual(result["disposition"], "NO_WAKE")
        self.assertFalse(result["draft"])
        self.assertFalse((directory / "read-drafts.json").exists())
        self.assertNotIn(MARKER, _tree(directory))


def _ready(port: int) -> dict:
    return {
        "WHATSAPP_WAKE_CONFIG": "",
        "WHATSAPP_WAKE_ENABLED": "1",
        "WHATSAPP_WAKE_URL": f"http://127.0.0.1:{port}/",
        "WHATSAPP_WAKE_AUTHORIZATION": "Authorization: " + TOKEN,
        "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
    }


_SEEDS = (
    ("fixture chat", "seed-one", "09:00"),
    ("fixture chat", "seed-two", "09:01"),
)


def _shot(rows, header="fixture chat", title=None):
    payload = {
        "layout": "probe-contract",
        "header": header,
        "phase": "ready",
        "slots": [
            {"kind": "message", "sender": sender, "text": text, "timeText": clock}
            for sender, text, clock in rows
        ],
    }
    if title is not None:
        payload["title"] = title
    return payload


def _tree(directory: Path) -> str:
    parts = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in sorted(directory.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
    directory.mkdir(parents=True, exist_ok=True)


def _monitors() -> list:
    import subprocess

    result = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, check=False)
    return [
        line
        for line in result.stdout.splitlines()
        if "dbus-monitor" in line and "org.freedesktop.Notifications" in line
    ]


if __name__ == "__main__":
    unittest.main()
