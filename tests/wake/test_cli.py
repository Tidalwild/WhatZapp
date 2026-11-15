import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path

from wake.__main__ import observe, probe, routine, status
from wake.observe import notifications_service, user_bus_available
from wake.routine import RoutineStore, serve

TOKEN = "local-test-only"
REPO = Path(__file__).resolve().parents[2]


class CliTests(unittest.TestCase):
    def test_status_and_probe_are_blocked_without_credentials(self):
        env = {"PATH": os.environ.get("PATH", ""), "WHATSAPP_WAKE_CONFIG": ""}
        self.assertEqual(status(env), 2)
        self.assertEqual(probe(env), 2)
        self.assertEqual(observe(env), 2)
        self.assertEqual(routine(env), 2)
        completed = subprocess.run(
            [sys.executable, "-m", "wake", "probe"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("blocked:", completed.stdout)
        self.assertNotIn("http", completed.stdout)
        self.assertNotIn("Authorization", completed.stdout)

    def test_observe_does_not_start_when_the_webhook_is_missing(self):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "WHATSAPP_WAKE_CONFIG": "",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/wake-not-a-live-bus",
        }
        before = _notification_monitors()
        self.assertEqual(observe(env), 2)
        self.assertEqual(_notification_monitors(), before)

    def test_status_separates_the_session_bus_from_notification_ownership(self):
        env = {"PATH": os.environ.get("PATH", ""), "WHATSAPP_WAKE_CONFIG": ""}
        if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            env["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
        if os.environ.get("XDG_RUNTIME_DIR"):
            env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = status(env)
        text = buffer.getvalue()
        self.assertEqual(code, 2)
        if user_bus_available(env):
            self.assertIn("desktop-bus: present", text)
            self.assertIn(f"notifications-service: {notifications_service(env)}", text)
            self.assertNotIn("notifications-service: unavailable", text)
        else:
            self.assertIn("desktop-bus: absent", text)
            self.assertIn("notifications-service: unavailable", text)
        self.assertIn("sends-whatsapp: no", text)
        self.assertNotIn("manual-connectivity-probe", text)
        address = env.get("DBUS_SESSION_BUS_ADDRESS") or ""
        if address:
            self.assertNotIn(address, text)

    def test_status_does_not_print_a_configured_secret(self):
        secret_url = "https://user.example/wake/secret-path-991"
        secret = "local-test-only-auth-991"
        env = {
            "WHATSAPP_WAKE_CONFIG": "",
            "WHATSAPP_WAKE_ENABLED": "1",
            "WHATSAPP_WAKE_URL": secret_url,
            "WHATSAPP_WAKE_AUTHORIZATION": secret,
            "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
        }
        from io import StringIO
        from contextlib import redirect_stdout

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = status(env)
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("transmission: configured", text)
        self.assertNotIn(secret_url, text)
        self.assertNotIn(secret, text)
        self.assertNotIn("contact-a", text)
        self.assertIn("wake-wire: v1", text)

    def test_probe_against_local_routine_is_not_a_live_wake(self):
        directory = Path("/tmp/wake-cli-probe")
        if directory.exists():
            for child in directory.iterdir():
                if child.is_file():
                    child.unlink()
        directory.mkdir(parents=True, exist_ok=True)
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
            "WHATSAPP_WAKE_AUTHORIZATION": TOKEN,
            "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
        }
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = probe(env)
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("not-a-whatsapp-notification: true", text)
        self.assertIn("chat-read: no", text)
        self.assertIn("whatsapp-send: no", text)
        self.assertNotIn(TOKEN, text)
        ids = json.loads((directory / "event-ids.json").read_text(encoding="utf-8"))["ids"]
        self.assertEqual(len(ids), 1)
        self.assertIn(ids[0], text)
        draft = json.loads((directory / "drafts.json").read_text(encoding="utf-8"))["drafts"][0]
        self.assertFalse(draft["sent"])
        self.assertFalse(draft["readsChat"])
        self.assertEqual(draft["handler"], "local-mock-handler")

    def test_disabled_flag_blocks_even_when_a_url_is_present(self):
        env = {
            "WHATSAPP_WAKE_CONFIG": "",
            "WHATSAPP_WAKE_ENABLED": "0",
            "WHATSAPP_WAKE_URL": "http://127.0.0.1:9/",
            "WHATSAPP_WAKE_AUTHORIZATION": TOKEN,
            "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
        }
        from contextlib import redirect_stdout
        from io import StringIO

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = probe(env)
        self.assertEqual(code, 2)
        self.assertIn("blocked:", buffer.getvalue())
        self.assertNotIn("127.0.0.1", buffer.getvalue())


def _notification_monitors() -> list:
    result = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, check=False)
    return [
        line
        for line in result.stdout.splitlines()
        if "dbus-monitor" in line and "org.freedesktop.Notifications" in line
    ]


if __name__ == "__main__":
    unittest.main()
