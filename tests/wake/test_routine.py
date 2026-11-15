import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from wake.envelope import build, new_event_id
from wake.routine import DEFAULT_STORE, MAX_EVENT_IDS, RoutineStore, serve

TOKEN = "local-test-only"
CANARY = "CANARY-BODY-991"


def post(url, body, authorization=TOKEN):
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if authorization is not None:
        request.add_header("Authorization", authorization)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def envelope(event_id=None, source="linux-session-notify", scope="contact-a"):
    payload = build(
        event_id=event_id or new_event_id(),
        source=source,
        observed_at="2026-11-12T06:22:00Z",
        conversation_scope=scope,
    )
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


class RoutineTests(unittest.TestCase):
    def test_cap_is_one_hundred_and_replays_do_not_grow(self):
        self.assertEqual(MAX_EVENT_IDS, 100)
        store = RoutineStore(self._dir(), TOKEN)
        first = None
        for index in range(100):
            event_id = f"evt-cap{index:04d}abcd"
            if first is None:
                first = event_id
            code, payload = store.handle(TOKEN, envelope(event_id, scope=None))
            self.assertEqual(code, 200, payload)
            self.assertTrue(payload["unique"])
        code, payload = store.handle(TOKEN, envelope(first, scope=None))
        self.assertEqual(code, 200)
        self.assertFalse(payload["unique"])
        self.assertEqual(payload["uniqueCount"], 100)
        code, payload = store.handle(TOKEN, envelope("evt-capoverlimit", scope=None))
        self.assertEqual(code, 429)
        self.assertEqual(len(json.loads((self._dir() / "event-ids.json").read_text())["ids"]), 100)
        drafts = json.loads((self._dir() / "drafts.json").read_text())["drafts"]
        self.assertEqual(len(drafts), 100)
        self.assertFalse(any(item["sendingEnabled"] or item["sent"] or item["readsChat"] for item in drafts))
        self.assertTrue(all(item["handler"] == "local-mock-handler" for item in drafts))

    def test_out_of_order_malformed_auth_and_no_secret_files(self):
        store = RoutineStore(self._dir(), TOKEN)
        later = envelope("evt-later0001", scope=None)
        earlier = envelope("evt-early0001", scope=None)
        self.assertEqual(store.handle(TOKEN, later)[0], 200)
        code, payload = store.handle(TOKEN, earlier)
        self.assertEqual(code, 200)
        self.assertTrue(payload["unique"])
        self.assertEqual(payload["uniqueCount"], 2)
        self.assertEqual(store.handle(None, earlier)[0], 401)
        self.assertEqual(store.handle("wrong-token-value", earlier)[0], 401)
        hostile = b'{"field":"whatsapp-wake-test-v1","body":"CANARY-BODY-991","target":"https://evil.invalid/x"}'
        self.assertEqual(store.handle(TOKEN, hostile)[0], 400)
        self.assertEqual(store.handle(TOKEN, b"{")[0], 400)
        self.assertEqual(store.handle(TOKEN, envelope("evt-false0001", scope=None).replace(b"true", b"false"))[0], 400)
        text = "\n".join(path.read_text(encoding="utf-8") for path in self._dir().iterdir() if path.is_file())
        self.assertNotIn(CANARY, text)
        self.assertNotIn("evil.invalid", text)
        self.assertNotIn(TOKEN, text)
        self.assertIn("evt-early0001", text)
        self.assertIn("evt-later0001", text)

    def test_http_server_is_loopback_and_writes_a_unique_receipt(self):
        store = RoutineStore(self._dir(), TOKEN)
        server = serve(store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with self.assertRaises(RuntimeError):
            serve(store, "0.0.0.0", 9)
        code, raw = post(url, envelope("evt-loop000001"))
        self.assertEqual(code, 200)
        body = json.loads(raw)
        self.assertTrue(body["unique"])
        code, raw = post(url, envelope("evt-loop000001"))
        self.assertFalse(json.loads(raw)["unique"])
        code, raw = post(url, b" ", authorization=TOKEN)
        self.assertEqual(code, 400)
        code, _raw = post(url, b"x" * 600, authorization=TOKEN)
        self.assertEqual(code, 400)
        code, _raw = post(url, envelope("evt-loop000002"), authorization=None)
        self.assertEqual(code, 401)
        receipt = (self._dir() / "latest-receipt.txt").read_text(encoding="utf-8")
        self.assertIn("unique=no", receipt)
        self.assertIn("readsChat=no", receipt)
        self.assertIn("sends=no", receipt)
        self.assertNotIn(CANARY, receipt)

    def test_workspace_store_reports_one_unique_receipt(self):
        self._clean_workspace()
        try:
            store = RoutineStore(DEFAULT_STORE, TOKEN, max_ids=100)
            code, payload = store.handle(TOKEN, envelope("evt-workspace01", source="manual-connectivity-probe", scope=None))
            self.assertEqual(code, 200)
            self.assertTrue(payload["unique"])
            code, payload = store.handle(TOKEN, envelope("evt-workspace01", source="manual-connectivity-probe", scope=None))
            self.assertFalse(payload["unique"])
            self.assertEqual(payload["uniqueCount"], 1)
            receipt = (DEFAULT_STORE / "latest-receipt.txt").read_text(encoding="utf-8")
            self.assertIn("eventId=evt-workspace01", receipt)
            self.assertIn("readsChat=no", receipt)
            self.assertIn("sends=no", receipt)
            self.assertTrue(str(DEFAULT_STORE).endswith("whatsapp-wake-test"))
        finally:
            self._clean_workspace()

    def test_corrupt_store_refuses(self):
        directory = self._dir()
        (directory / "event-ids.json").write_text("{", encoding="utf-8")
        store = RoutineStore(directory, TOKEN)
        code, payload = store.handle(TOKEN, envelope(scope=None))
        self.assertEqual(code, 503)
        self.assertEqual(payload["reason"], "corrupt")
        self.assertEqual((directory / "event-ids.json").read_text(encoding="utf-8"), "{")

    def _dir(self) -> Path:
        cached = getattr(self, "_cached_dir", None)
        if cached is not None:
            return cached
        path = Path("/tmp") / "wake-routine" / self.id().replace(".", "_")
        path.mkdir(parents=True, exist_ok=True)
        for child in path.iterdir():
            if child.is_file():
                child.unlink()
        self._cached_dir = path
        return path

    def _clean_workspace(self) -> None:
        for name in ("event-ids.json", "receipts.jsonl", "drafts.json", "latest-receipt.txt"):
            path = DEFAULT_STORE / name
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
