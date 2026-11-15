import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from tests.wake.support import pipeline, start_private_bus
from wake.client import WebhookClient
from wake.clock import Clock
from wake.log import Log
from wake.__main__ import status
from wake.observe import NotifyParser, monitor, notifications_service, notify_match_rule
from wake.outbox import Outbox
from wake.pipeline import Pipeline
from wake.routine import RoutineStore, serve

SAMPLE = """signal time=1.0 sender=org.freedesktop.DBus -> destination=:1.0 serial=2 path=/org/freedesktop/DBus; interface=org.freedesktop.DBus; member=NameAcquired
   string ":1.0"
method call time=2.0 sender=:1.1 -> destination=org.freedesktop.Notifications serial=2 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "Spoofed WhatsApp"
   uint32 7
   string ""
   string "contact-a"
   string "CANARY-BODY-991"
   array [
   ]
   array [
   ]
   int32 -1
"""

TOKEN = "local-test-only"


class ParserTests(unittest.TestCase):
    def test_sample_keeps_summary_and_drops_body(self):
        parser = NotifyParser()
        found = []
        for line in SAMPLE.splitlines():
            found.extend(parser.feed(line))
        self.assertEqual(len(found), 1)
        obs = found[0]
        self.assertEqual(obs.app_name, "Spoofed WhatsApp")
        self.assertEqual(obs.replaces_id, 7)
        self.assertEqual(obs.summary, "contact-a")
        self.assertEqual(obs.origin, "session-bus")
        self.assertFalse(hasattr(obs, "body"))
        self.assertNotIn("CANARY-BODY-991", json.dumps(obs.__dict__))

    def test_incomplete_notify_is_malformed_not_a_message(self):
        parser = NotifyParser()
        parser.feed(
            "method call time=1 sender=:1.1 -> destination=org.freedesktop.Notifications serial=1 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify"
        )
        parser.feed('   string "WhatsApp"')
        failed = parser.feed("signal time=2 sender=:1.2 -> destination=:1.0 serial=1 path=/org/freedesktop/DBus; interface=org.freedesktop.DBus; member=NameAcquired")
        self.assertEqual(len(failed), 1)
        self.assertEqual(str(failed[0]), "MALFORMED_NOTIFY")

    def test_parser_drops_a_foreign_body_before_the_pipeline_stores_anything(self):
        foreign = """method call time=2.0 sender=:1.1 -> destination=org.freedesktop.Notifications serial=3 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "WhatsApp"
   uint32 4
   string ""
   string "FixtureOther"
   string "FOREIGN-BODY-991"
   array [
   ]
   array [
   ]
   int32 -1
"""
        parser = NotifyParser()
        found = []
        for line in foreign.splitlines():
            found.extend(parser.feed(line))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].summary, "FixtureOther")
        self.assertNotIn("FOREIGN-BODY-991", repr(found[0]))
        self.assertNotIn("body", found[0].__dict__)
        with tempfile.TemporaryDirectory(prefix="wake-foreign-") as raw:
            made, _clock, log, transport = pipeline(Path(raw))
            result = made.handle(found[0])
            self.assertEqual(result.reason, "WRONG_OR_AMBIGUOUS")
            made.flush()
            self.assertEqual(transport.calls, [])
            blob = log.text() + (Path(raw) / "outbox.json").read_text(encoding="utf-8")
            self.assertNotIn("FOREIGN-BODY-991", blob)
            self.assertNotIn("FixtureOther", blob)


class IsolatedBusTests(unittest.TestCase):
    def test_private_bus_notify_reaches_local_routine_only(self):
        with tempfile.TemporaryDirectory(prefix="wake-bus-") as raw:
            directory = Path(raw)
            daemon, address = start_private_bus(directory)
            store = RoutineStore(directory / "store", TOKEN)
            server = serve(store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            outbox = Outbox(directory / "outbox.json", Clock())
            log = Log()
            made = Pipeline(
                outbox=outbox,
                allowlist="contact-a",
                enabled=True,
                client=WebhookClient(
                    f"http://127.0.0.1:{server.server_address[1]}/",
                    TOKEN,
                ),
                log=log,
            )
            found = threading.Event()
            errors = []

            def handler(item):
                try:
                    made.handle(item)
                    made.flush()
                    if any(row.state == "acked" for row in made.outbox.items.values()):
                        found.set()
                except Exception as exc:
                    errors.append(repr(exc))
                    found.set()

            stop = threading.Event()
            tape = []
            watcher = threading.Thread(
                target=monitor,
                kwargs={
                    "address": address,
                    "handler": handler,
                    "stop": stop,
                    "allowlist": "contact-a",
                    "tape": tape,
                },
                daemon=True,
            )
            watcher.start()
            unscoped_path = directory / "unscoped.log"
            unscoped_handle = unscoped_path.open("w", encoding="utf-8")
            unscoped_env = os.environ.copy()
            unscoped_env["DBUS_SESSION_BUS_ADDRESS"] = address
            for secret_name in (
                "WHATSAPP_WAKE_URL",
                "WHATSAPP_WAKE_AUTHORIZATION",
                "WHATSAPP_WAKE_ROUTINE_AUTHORIZATION",
            ):
                unscoped_env.pop(secret_name, None)
            unscoped = subprocess.Popen(
                [
                    "stdbuf",
                    "-oL",
                    "-eL",
                    "dbus-monitor",
                    "--session",
                    "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
                ],
                env=unscoped_env,
                stdout=unscoped_handle,
                stderr=subprocess.DEVNULL,
            )
            unscoped_handle.close()
            try:
                import time

                time.sleep(0.6)
                self._send(address, "WhatsApp", "FixtureOther", "FOREIGN-BODY-991")
                self._send(address, "Chrome", "", "EMPTY-TITLE-BODY-991")
                self._send(address, "NotWhatsApp", "contact-a", "CANARY-BODY-991")
                self.assertTrue(found.wait(5), "isolated bus did not deliver a Notify; this is not a live wake")
                self.assertEqual(errors, [])
                names = subprocess.run(
                    [
                        "dbus-send",
                        f"--bus={address}",
                        "--dest=org.freedesktop.DBus",
                        "--print-reply",
                        "/org/freedesktop/DBus",
                        "org.freedesktop.DBus.ListNames",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertNotIn("org.freedesktop.Notifications", names.stdout)
                item = next(iter(made.outbox.items.values()))
                self.assertEqual(item.payload["source"], "linux-session-notify")
                self.assertEqual(item.payload["conversationScope"], "contact-a")
                self.assertTrue(item.payload["testOnly"])
                self.assertFalse(item.draft["sent"])
                self.assertFalse(item.draft["readsChat"])
                receipt = (directory / "store" / "latest-receipt.txt").read_text(encoding="utf-8")
                self.assertIn("unique=yes", receipt)
                self.assertIn("readsChat=no", receipt)
                blob = log.text() + receipt + (directory / "outbox.json").read_text(encoding="utf-8")
                blob += (directory / "store" / "drafts.json").read_text(encoding="utf-8")
                self.assertNotIn("CANARY-BODY-991", blob)
                self.assertNotIn("WhatsApp", item.payload["source"])
                self.assertNotIn("CANARY-BODY-991", json.dumps(item.payload))
                scoped = "".join(tape)
                self.assertIn("CANARY-BODY-991", scoped)
                self.assertNotIn("FOREIGN-BODY-991", scoped)
                self.assertNotIn("EMPTY-TITLE-BODY-991", scoped)
                self.assertIn("arg3='contact-a'", notify_match_rule("contact-a"))
                self.assertNotIn("arg0", notify_match_rule("contact-a"))
                unscoped.terminate()
                unscoped.wait(timeout=2)
                unscoped_text = unscoped_path.read_text(encoding="utf-8")
                self.assertIn("FOREIGN-BODY-991", unscoped_text)
                self.assertIn("EMPTY-TITLE-BODY-991", unscoped_text)
                self.assertNotIn("FOREIGN-BODY-991", blob)
                bus_env = {
                    "PATH": os.environ.get("PATH", ""),
                    "WHATSAPP_WAKE_CONFIG": "",
                    "DBUS_SESSION_BUS_ADDRESS": address,
                }
                self.assertEqual(notifications_service(bus_env), "absent")
                from io import StringIO
                from contextlib import redirect_stdout

                buffer = StringIO()
                with redirect_stdout(buffer):
                    self.assertEqual(status(bus_env), 2)
                report = buffer.getvalue()
                self.assertIn("desktop-bus: present", report)
                self.assertIn("notifications-service: absent", report)
                self.assertNotIn(address, report)
                self.assertNotIn("FOREIGN-BODY-991", report)
                self.assertNotIn("CANARY-BODY-991", report)
            finally:
                stop.set()
                watcher.join(timeout=3)
                if unscoped.poll() is None:
                    unscoped.terminate()
                    try:
                        unscoped.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        unscoped.kill()
                server.shutdown()
                server.server_close()
                if daemon.poll() is None:
                    daemon.terminate()
                    try:
                        daemon.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        daemon.kill()

    def _send(self, address: str, app_name: str, summary: str, body: str) -> None:
        subprocess.run(
            [
                "dbus-send",
                f"--bus={address}",
                "--dest=org.freedesktop.Notifications",
                "--type=method_call",
                "--print-reply",
                "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications.Notify",
                f"string:{app_name}",
                "uint32:7",
                "string:",
                f"string:{summary}",
                f"string:{body}",
                "array:string:",
                "dict:string:string:",
                "int32:-1",
            ],
            check=False,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
