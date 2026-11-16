import os
import unittest
from pathlib import Path

from wake.__main__ import main
from wake.setupcheck import report

REPO = Path(__file__).resolve().parents[2]
SECRET_URL = "https://user.example/wake/secret-path-771"
SECRET = "local-test-only-auth-771"
LABEL = "contact-a"


class SetupCheckTests(unittest.TestCase):
    def test_clean_public_tree_passes_without_a_credential(self):
        code, text = report(_bare_env(), REPO)
        self.assertEqual(code, 0, text)
        self.assertIn("setup-check: public\n", text)
        self.assertIn("contract: wake-evidence-1\n", text)
        self.assertIn("included-bot: no\n", text)
        self.assertIn("sends-whatsapp: no\n", text)
        self.assertIn("live-send-armed: false\n", text)
        self.assertIn("reference-receiver: example-only\n", text)
        self.assertIn("response-interface: absent\n", text)
        self.assertIn("response-handoff: unverified\n", text)
        self.assertIn("http-2xx-means: transport-accepted\n", text)
        self.assertIn("queued-means: not-covered\n", text)
        self.assertIn("fresh-setup: unproven\n", text)
        self.assertIn("webhook: missing\n", text)
        self.assertIn("transmission: blocked\n", text)
        self.assertIn("mock-handler: off\n", text)
        self.assertIn("language-default: en\n", text)
        self.assertIn("language-supported: zh-Hant\n", text)
        self.assertIn("webhook-probe: not-run\n", text)
        self.assertIn("whatsapp-session: not-run\n", text)
        self.assertIn("result: public-package-ok\n", text)
        foundation = (REPO / "docs" / "FOUNDATION.md").read_text(encoding="utf-8")
        self.assertIn("wake-evidence-1", foundation)
        self.assertIn("response-interface: absent", foundation)
        self.assertIn("傳輸已接受", foundation)
        self.assertIn("no quality score", foundation)
        self.assertNotIn("https://", text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("local-mock-handler", text)

    def test_a_configured_webhook_is_not_printed_and_is_not_a_probe(self):
        env = _bare_env()
        env.update(
            {
                "WHATSAPP_WAKE_ENABLED": "1",
                "WHATSAPP_WAKE_URL": SECRET_URL,
                "WHATSAPP_WAKE_AUTHORIZATION": SECRET,
                "WHATSAPP_WAKE_ALLOWLIST_LABEL": LABEL,
            }
        )
        code, text = report(env, REPO)
        self.assertEqual(code, 0, text)
        self.assertIn("webhook: configured\n", text)
        self.assertIn("allowlist: set\n", text)
        self.assertIn("transmission: configured\n", text)
        self.assertIn("webhook-probe: not-run\n", text)
        self.assertNotIn(SECRET_URL, text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(LABEL, text)
        self.assertNotIn("secret-path", text)

    def test_command_uses_the_same_report(self):
        code = main(["wake", "setup-check"], _bare_env())
        self.assertEqual(code, 0)

    def test_send_switch_and_reference_import_fail_closed(self):
        armed = REPO / "web" / "src" / "replyDelivery.ts"
        original = armed.read_text(encoding="utf-8")
        try:
            armed.write_text(original.replace("LIVE_SEND_ARMED = false", "LIVE_SEND_ARMED = true"), encoding="utf-8")
            code, text = report(_bare_env(), REPO)
        finally:
            armed.write_text(original, encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("live-send-armed: true\n", text)
        self.assertIn("result: blocked\n", text)
        self.assertIn("send-armed", text)
        host = REPO / "wake" / "bridge.py"
        source = host.read_text(encoding="utf-8")
        try:
            host.write_text(source + "\nimport examples.routine.reference_receiver\n", encoding="utf-8")
            code, text = report(_bare_env(), REPO)
        finally:
            host.write_text(source, encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertIn("reference-receiver: imported-by-host\n", text)


def _bare_env() -> dict:
    return {"PATH": os.environ.get("PATH", ""), "WHATSAPP_WAKE_CONFIG": ""}
