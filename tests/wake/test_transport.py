import json
import unittest
from pathlib import Path

from wake.client import WebhookClient
from wake.config import load_config
from wake.envelope import build_v2, new_event_id
from wake.listchange import apply_list_change
from wake.persons import apply_person_hint
from wake.resolve import permit_open, touch_session
from tests.wake.support import Scripted, pipeline

REF = "ref-0123456789abcdef"


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in directory.iterdir():
            if child.is_file():
                child.unlink()
    directory.mkdir(parents=True, exist_ok=True)


def _post(status, body, mode="official"):
    payload = build_v2(event_id=new_event_id(), observed_at="2026-11-15T00:00:00Z", chat_ref=REF)
    return WebhookClient("http://127.0.0.1:9/", "local-test-only", Scripted([(status, body)]), mode=mode).post(payload)


class OfficialTransportTests(unittest.TestCase):
    def test_default_is_official_and_does_not_need_another_endpoint(self):
        config = load_config({"WHATSAPP_WAKE_CONFIG": "", "WHATSAPP_WAKE_TRANSPORT": "anything-else"})
        self.assertEqual(config.transport, "official")
        selected = load_config({"WHATSAPP_WAKE_CONFIG": "", "WHATSAPP_WAKE_TRANSPORT": "test-receipt"})
        self.assertEqual(selected.transport, "test-receipt")

    def test_empty_and_non_custom_2xx_are_transport_only(self):
        for body in (b"", b"ok", b"{}", b'{"status":"ok"}', b'{"accepted":true,"unique":false,"duplicate":true}'):
            result = _post(200, body)
            self.assertEqual(result.status, "acked", body)
            self.assertEqual(result.classification, "transport", body)
            self.assertFalse(result.duplicate, body)

    def test_http_errors_stay_errors_and_409_is_legacy(self):
        for status in (400, 401, 404, 422):
            result = _post(status, b"")
            self.assertEqual(result.status, "rejected", status)
            self.assertEqual(result.classification, "none", status)
        for status in (500, 503):
            result = _post(status, b'{"accepted":true,"unique":true,"duplicate":false}')
            self.assertEqual(result.status, "retryable", status)
        legacy = _post(409, b"")
        self.assertEqual(legacy.status, "acked")
        self.assertEqual(legacy.classification, "legacy-409")
        self.assertTrue(legacy.duplicate)

    def test_v3_posts_on_an_empty_2xx_and_replay_stays_local(self):
        directory = Path("/tmp/wake-official-list")
        _clear(directory)
        transport = Scripted([(200, b""), (200, b'{"accepted":true,"unique":false,"duplicate":true}')])
        made, clock, _log, transport = pipeline(directory, transport=transport)
        self.assertEqual(
            apply_list_change(directory, {"mark": "count", "count": 1}, pipeline=made, wire="list")["disposition"],
            "COUNT_BASELINE",
        )
        clock.advance(2)
        risen = apply_list_change(directory, {"mark": "count", "count": 2}, pipeline=made, wire="list")
        self.assertTrue(risen["posted"])
        item = made.outbox.items[risen["event"]]
        self.assertEqual(item.state, "acked")
        self.assertEqual(item.reason, "transport-accepted")
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["field"], "whatsapp-wake-test-v3")
        self.assertEqual(payload["source"], "list-change")
        clock.advance(30)
        made.flush()
        self.assertEqual(len(transport.calls), 1)
        again = apply_list_change(directory, {"mark": "count", "count": 2}, pipeline=made, wire="list")
        self.assertEqual(again["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(permit_open(directory, risen["event"], REF, 1), "UNTARGETED")

    def test_official_v2_transport_does_not_queue_an_open(self):
        directory = Path("/tmp/wake-official-v2")
        _clear(directory)
        made, clock, _log, _transport = pipeline(directory, transport=Scripted([(200, b""), (409, b"")]))
        apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 1}, pipeline=made, wire="v2")
        clock.advance(2)
        posted = apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 2}, pipeline=made, wire="v2")
        self.assertEqual(made.outbox.items[posted["event"]].reason, "transport-accepted")
        touch_session(directory, REF, 1_000.0)
        self.assertEqual(permit_open(directory, posted["event"], REF, 1_100.0), "TRANSPORT_ONLY")
        self.assertFalse((directory / "open-permit.json").exists())
        clock.advance(2)
        conflict = apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 3}, pipeline=made, wire="v2")
        self.assertEqual(made.outbox.items[conflict["event"]].reason, "legacy-409")
        self.assertEqual(permit_open(directory, conflict["event"], REF, 1_100.0), "LEGACY_409")
        self.assertFalse((directory / "open-permit.json").exists())

    def test_custom_receipt_is_optional_and_not_the_default(self):
        for body in (b"", b"{}", b'{"accepted":true}', b'{"accepted":true,"unique":true}'):
            result = _post(200, body, mode="test-receipt")
            self.assertEqual(result.status, "rejected", body)
        unique = _post(200, b'{"accepted":true,"unique":true,"duplicate":false}', mode="test-receipt")
        self.assertEqual(unique.classification, "receipt")
        self.assertFalse(unique.duplicate)
        duplicate = _post(200, b'{"accepted":true,"unique":false,"duplicate":true}', mode="test-receipt")
        self.assertEqual(duplicate.classification, "receipt-duplicate")
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(_post(409, b"", mode="test-receipt").status, "rejected")
