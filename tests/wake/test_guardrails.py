import json
import os
import unittest
from pathlib import Path

from wake.config import load_config, valid_url
from wake.observe import notify_match_rule, user_bus_available
from wake.policy import valid_label

ROOT = Path(__file__).resolve().parents[2]


class GuardrailTests(unittest.TestCase):
    def test_extension_cannot_listen_to_other_notifications(self):
        for name in ("web/manifest.json", "web/manifest.test.json"):
            manifest = json.loads((ROOT / name).read_text(encoding="utf-8"))
            self.assertEqual(manifest["permissions"], ["storage", "nativeMessaging"])
            self.assertNotIn("notifications", json.dumps(manifest))
            self.assertNotIn("<all_urls>", json.dumps(manifest))

    def test_wake_package_does_not_own_the_bus_or_the_page(self):
        banned = (
            "RequestName",
            "chrome.notifications",
            "window.Store",
            "web.whatsapp.com",
            "graph.facebook.com",
            "playwright",
        )
        text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "wake").glob("*.py"))
        for token in banned:
            self.assertNotIn(token, text)

    def test_example_config_is_off_and_empty(self):
        example = (ROOT / "config" / "wake.env.example").read_text(encoding="utf-8")
        self.assertIn("WHATSAPP_WAKE_ENABLED=0", example)
        self.assertIn("WHATSAPP_WAKE_URL=\n", example)
        self.assertIn("WHATSAPP_WAKE_AUTHORIZATION=\n", example)
        self.assertNotIn("sk-", example)
        self.assertNotIn("Bearer ", example)
        self.assertNotIn("https://", example)
        loaded = load_config({"WHATSAPP_WAKE_CONFIG": str(ROOT / "config" / "wake.env.example")})
        self.assertFalse(loaded.enabled)
        self.assertEqual(loaded.url, "")
        self.assertEqual(loaded.authorization, "")

    def test_public_http_and_userinfo_are_rejected(self):
        self.assertFalse(valid_url("http://example.com/hook"))
        self.assertFalse(valid_url("https://user:secret@example.com/hook"))
        self.assertFalse(valid_url("http://127.0.0.1/hook"))
        self.assertTrue(valid_url("http://127.0.0.1:8791/"))
        self.assertTrue(valid_url("https://routine.example/wake"))

    def test_bus_presence_follows_the_probe_on_this_machine(self):
        env = {"PATH": os.environ.get("PATH", ""), "WHATSAPP_WAKE_CONFIG": ""}
        if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            env["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
        if os.environ.get("XDG_RUNTIME_DIR"):
            env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
        runtime = env.get("XDG_RUNTIME_DIR") or ""
        expected = bool(env.get("DBUS_SESSION_BUS_ADDRESS")) or (
            bool(runtime) and Path(runtime, "bus").exists()
        ) or Path(f"/run/user/{os.getuid()}/bus").exists()
        self.assertEqual(user_bus_available(env), expected)

    def test_missing_socket_is_not_reported_as_a_bus(self):
        self.assertFalse(user_bus_available({}, path_exists=lambda _path: False))
        self.assertTrue(
            user_bus_available(
                {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/wake-not-a-live-bus"},
                path_exists=lambda _path: False,
            )
        )

    def test_match_rule_filters_the_summary_and_not_the_app_name(self):
        rule = notify_match_rule("contact-a")
        self.assertEqual(
            rule,
            "type='method_call',interface='org.freedesktop.Notifications',member='Notify',arg3='contact-a'",
        )
        self.assertNotIn("arg0", rule)
        self.assertFalse(valid_label("WhatsApp' ,arg0='Chrome"))
        self.assertFalse(valid_label("contact-a "))
        self.assertFalse(valid_label("https://fixture.invalid/x"))
        with self.assertRaises(ValueError):
            notify_match_rule("contact-a ")


if __name__ == "__main__":
    unittest.main()
