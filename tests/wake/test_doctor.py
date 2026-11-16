import json
import os
import unittest
from pathlib import Path

from wake.__main__ import main
from wake.doctor import diagnose, drop_local_state, recover, rollback_report
from wake.envelope import build_v3
from wake.evidence import from_outbox
from wake.outbox import Item, Outbox
from wake.clock import Clock
from wake.recovery import LABELS_ZH_HANT, PageFacts, connection_status, note_restart
from wake.read import load_binding

REPO = Path(__file__).resolve().parents[2]
HEADER = "fixture-header-771"
OWN = "fixture-self-771"
SECRET_URL = "https://user.example/wake/secret-path-772"
SECRET = "local-test-only-auth-772"
EVENT = "evt-" + "ab" * 16


class DoctorTests(unittest.TestCase):
    def test_labels_and_ready_requires_a_fresh_revalidated_page(self):
        self.assertEqual(LABELS_ZH_HANT["relink"], "需要重新連結")
        self.assertNotEqual(LABELS_ZH_HANT["ready"], LABELS_ZH_HANT["recovering"])
        ready, reason = connection_status(
            "listening",
            "yes",
            PageFacts(phase="ready", fresh=True, network="up", identity="match"),
            True,
        )
        self.assertEqual((ready, reason), ("ready", "revalidated"))
        stale, why = connection_status(
            "listening",
            "yes",
            PageFacts(phase="ready", fresh=False, network="up", identity="match"),
            True,
        )
        self.assertEqual((stale, why), ("disconnected", "stale-page"))
        logged_out, _cause = connection_status(
            "listening",
            "yes",
            PageFacts(phase="logged-out", fresh=True, network="up", identity="match"),
            True,
        )
        self.assertEqual(logged_out, "relink")
        mismatch, _cause = connection_status(
            "listening",
            "yes",
            PageFacts(phase="ready", fresh=True, network="up", identity="mismatch"),
            True,
        )
        self.assertEqual(mismatch, "relink")
        down, why = connection_status(
            "listening",
            "yes",
            PageFacts(phase="ready", fresh=True, network="down", identity="match"),
            True,
        )
        self.assertEqual((down, why), ("recovering", "network-down"))
        away, why = connection_status(
            "listening",
            "yes",
            PageFacts(phase="navigated", fresh=True, network="up", identity="match"),
            True,
        )
        self.assertEqual((away, why), ("disconnected", "navigated"))

    def test_doctor_does_not_print_secrets_or_call_a_session_ready(self):
        store = self._store()
        _write_binding(store)
        (store / "handshake.json").write_text(json.dumps({"hello": "READY", "scope": "none", "list": "none"}), encoding="utf-8")
        (store / "host.json").write_text(json.dumps({"phase": "listening", "cause": "none", "detail": "none", "pid": 999999}), encoding="utf-8")
        (store / "scope.json").write_text(json.dumps({"mode": "allowlist", "allow": [HEADER]}), encoding="utf-8")
        env = _env(store)
        code, text = diagnose(env, store, REPO)
        self.assertEqual(code, 0, text)
        self.assertIn("install-proven: no\n", text)
        self.assertIn("package-check: tree-only\n", text)
        self.assertIn("browser: disconnected\n", text)
        self.assertIn("browser-reason: host-stale\n", text)
        self.assertIn("receiver: not-probed\n", text)
        self.assertIn("routine: external\n", text)
        self.assertIn("routine-response: unproven\n", text)
        self.assertIn("approved-delivery: disabled\n", text)
        self.assertIn("live-send-armed: false\n", text)
        self.assertIn("scope-mode: allowlist\n", text)
        self.assertIn("webhook-probe: not-run\n", text)
        self.assertNotIn("browser: ready\n", text)
        self.assertNotIn(SECRET_URL, text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(HEADER, text)
        self.assertNotIn("secret-path", text)

    def test_restart_keeps_an_inflight_id_uncovered_and_recover_is_not_ready(self):
        store = self._store()
        _write_binding(store)
        box = Outbox(store / "outbox.json", Clock())
        box.add(
            Item(
                event_id=EVENT,
                payload=build_v3(event_id=EVENT, observed_at="2026-01-01T00:00:00Z"),
                state="in_flight",
                attempts=1,
                next_attempt_at=0,
                replaces_id=0,
                source="list-change",
                created_at=1,
                updated_at=1,
                acked_at=None,
                reason="",
                draft=None,
            )
        )
        self.assertEqual(note_restart(store), 1)
        reloaded = Outbox(store / "outbox.json", Clock())
        item = reloaded.items[EVENT]
        self.assertEqual(item.state, "retryable")
        self.assertEqual(item.reason, "RESTART")
        record = from_outbox(item.state, item.reason)
        self.assertFalse(record.proves_covered())
        self.assertFalse(record.proves_bot_response())
        code, text = recover({"PATH": os.environ.get("PATH", ""), "WHATSAPP_WAKE_CONFIG": "", "WHATSAPP_WAKE_STORE": str(store)}, store, REPO)
        self.assertEqual(code, 0, text)
        self.assertIn("unresolved: 1\n", text)
        self.assertIn("correlation: none\n", text)
        self.assertNotIn("browser: ready\n", text)
        self.assertNotIn(EVENT, text)

    def test_logout_and_mismatch_require_relink_without_changing_scope(self):
        store = self._store()
        _write_binding(store)
        (store / "scope.json").write_text(json.dumps({"mode": "allowlist", "allow": ["contact-a"]}), encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", ""), "WHATSAPP_WAKE_CONFIG": "", "WHATSAPP_WAKE_STORE": str(store)}
        code, text = recover(env, store, REPO, logged_out=True)
        self.assertEqual(code, 0, text)
        self.assertIn("browser: relink\n", text)
        self.assertIn("browser-reason: logged-out\n", text)
        self.assertIn("scope-mode: allowlist\n", text)
        self.assertIsNone(load_binding(store))
        self.assertNotIn("direct", Path(store / "scope.json").read_text(encoding="utf-8"))
        _write_binding(store)
        code, text = recover(env, store, REPO, identity="mismatch")
        self.assertEqual(code, 0, text)
        self.assertIn("browser-reason: identity-mismatch\n", text)
        self.assertIsNone(load_binding(store))
        self.assertEqual(json.loads((store / "scope.json").read_text(encoding="utf-8"))["mode"], "allowlist")

    def test_rollback_lists_state_and_drops_only_runtime_names(self):
        store = self._store()
        _write_binding(store)
        (store / "outbox.json").write_text("{}\n", encoding="utf-8")
        (store / "scope.json").write_text(json.dumps({"mode": "allowlist"}), encoding="utf-8")
        secret = store / "wake.env"
        secret.write_text("WHATSAPP_WAKE_AUTHORIZATION=" + SECRET + "\n", encoding="utf-8")
        outside = store.parent / "outside-target.txt"
        outside.write_text("keep\n", encoding="utf-8")
        link = store / "outbox.json"
        link.unlink()
        link.symlink_to(outside)
        code, text = rollback_report(store, REPO, drop=False)
        self.assertEqual(code, 0, text)
        self.assertIn("drop: not-run\n", text)
        self.assertIn("whatsapp-session: not-unlinked\n", text)
        self.assertTrue(link.is_symlink())
        removed = drop_local_state(store)
        self.assertIn("binding.json", removed)
        self.assertNotIn("outbox.json", removed)
        self.assertNotIn("scope.json", removed)
        self.assertNotIn("wake.env", removed)
        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep\n")
        self.assertTrue(secret.is_file())
        self.assertIn(SECRET, secret.read_text(encoding="utf-8"))
        code, text = rollback_report(store, REPO, loaded_extension="0.0.0", drop=True)
        self.assertEqual(code, 0, text)
        self.assertIn("extension-pair: mismatch\n", text)
        self.assertIn("secrets: kept-outside-the-runtime-names\n", text)
        self.assertNotIn(SECRET, text)
        self.assertTrue(secret.is_file())
        self.assertTrue((store / "scope.json").is_file())

    def test_commands_do_not_print_the_store_path(self):
        from contextlib import redirect_stdout
        from io import StringIO

        store = self._store()
        env = _env(store)
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["wake", "doctor"], env), 0)
            self.assertEqual(main(["wake", "rollback"], env), 0)
            self.assertEqual(main(["wake", "recover"], env), 0)
        text = buffer.getvalue()
        code, report = diagnose(env, store, REPO, loaded_extension="9.9.9")
        self.assertEqual(code, 0, report)
        self.assertIn("extension-pair: mismatch\n", report)
        self.assertNotIn(str(store), text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(SECRET_URL, text)
        self.assertNotIn("browser: ready\n", text)

    def _store(self) -> Path:
        directory = Path(os.environ.get("TMPDIR", "/tmp")) / f"wake-doctor-{id(self)}-{os.getpid()}"
        directory.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: _clear(directory))
        return directory


def _env(store: Path) -> dict:
    return {
        "PATH": os.environ.get("PATH", ""),
        "WHATSAPP_WAKE_CONFIG": "",
        "WHATSAPP_WAKE_STORE": str(store),
        "WHATSAPP_WAKE_ENABLED": "1",
        "WHATSAPP_WAKE_URL": SECRET_URL,
        "WHATSAPP_WAKE_AUTHORIZATION": SECRET,
        "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
    }


def _write_binding(store: Path) -> None:
    payload = {
        "localScopeId": "scope-" + "cd" * 16,
        "visibleHeader": HEADER,
        "selfLabel": OWN,
        "mode": "messages",
        "verifiedRemoteRecipient": False,
        "confidence": "local-pilot-display-label",
    }
    (store / "binding.json").write_text(json.dumps(payload), encoding="utf-8")


def _clear(directory: Path) -> None:
    if not directory.exists():
        return
    for child in directory.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
    directory.rmdir()
