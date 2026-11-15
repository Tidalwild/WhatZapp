import io
import json
import os
import time
import unittest
from pathlib import Path

from wake.__main__ import main
from wake.bridge import run_stdio
from wake.client import WebhookClient
from wake.envelope import build, build_v2, new_event_id
from wake.persons import apply_person_hint
from wake.resolve import permit_open, take_permit, touch_session
from tests.wake.support import Scripted, pipeline

REF = "ref-0123456789abcdef"
OTHER = "ref-fedcba9876543210"
TOKEN = "person-b"


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in directory.iterdir():
            if child.is_file():
                child.unlink()
    directory.mkdir(parents=True, exist_ok=True)


def _frames(*messages) -> bytes:
    chunks = []
    for message in messages:
        raw = json.dumps(message, separators=(",", ":")).encode("utf-8")
        chunks.append(len(raw).to_bytes(4, "little") + raw)
    return b"".join(chunks)


def _codes(raw: bytes) -> list:
    stream = io.BytesIO(raw)
    found = []
    while stream.tell() < len(raw):
        size = int.from_bytes(stream.read(4), "little")
        if size <= 0:
            break
        found.append(json.loads(stream.read(size).decode("utf-8")))
    return found


class ResolveTests(unittest.TestCase):
    def test_official_transport_does_not_read_a_receipt_body(self):
        payload = build_v2(event_id=new_event_id(), observed_at="2026-11-15T00:00:00Z", chat_ref=REF)
        for body in (b"", b"{}", b'{"accepted":true}', b'{"accepted":true,"unique":false,"duplicate":true}'):
            result = WebhookClient("http://127.0.0.1:9/", "local-test-only", Scripted([(200, body)])).post(payload)
            self.assertEqual(result.status, "acked", body)
            self.assertEqual(result.classification, "transport", body)
            self.assertFalse(result.duplicate, body)

    def test_permit_opens_only_the_latest_unique_v2_ack(self):
        directory = Path("/tmp/wake-permit-open")
        _clear(directory)
        made, clock, _log, transport = pipeline(
            directory,
            transport=Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')] * 2),
            mode="test-receipt",
        )
        self.assertEqual(
            apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 1}, pipeline=made, wire="v2")["disposition"],
            "COUNT_BASELINE",
        )
        older = apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 2}, pipeline=made, wire="v2")
        clock.advance(2)
        newer = apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 3}, pipeline=made, wire="v2")
        self.assertEqual(len(transport.calls), 2)
        for call in transport.calls:
            body = json.loads(call["body"].decode("utf-8"))
            self.assertEqual(body["field"], "whatsapp-wake-test-v2")
            self.assertNotIn("conversationScope", body)
            self.assertNotIn(TOKEN, call["body"].decode("utf-8"))
        touch_session(directory, REF, 1_000.0)
        self.assertEqual(permit_open(directory, older["event"], REF, 1_100.0), "STALE_EVENT")
        self.assertEqual(permit_open(directory, newer["event"], OTHER, 1_100.0), "REF_MISMATCH")
        self.assertEqual(permit_open(directory, newer["event"], REF, 1_700.0), "SESSION_EXPIRED")
        self.assertEqual(permit_open(directory, newer["event"], REF, 1_100.0), "OPEN_QUEUED")
        permit = json.loads((directory / "open-permit.json").read_text(encoding="utf-8"))
        self.assertEqual(set(permit), {"eventId", "chatRef", "expires", "state"})
        self.assertNotIn(TOKEN, json.dumps(permit))
        transport.results.append((200, b'{"accepted":true,"unique":true,"duplicate":false}'))
        self.assertEqual(
            apply_person_hint(directory, {"chatRef": OTHER, "mark": "count", "count": 1}, pipeline=made, wire="v2")["disposition"],
            "COUNT_BASELINE",
        )
        clock.advance(2)
        other = apply_person_hint(directory, {"chatRef": OTHER, "mark": "count", "count": 2}, pipeline=made, wire="v2")
        touch_session(directory, OTHER, 1_000.0)
        self.assertEqual(permit_open(directory, other["event"], OTHER, 1_100.0), "PERMIT_PENDING")
        taken = take_permit(directory, 1_100.0)
        self.assertEqual(taken, {"eventId": newer["event"], "chatRef": REF})
        self.assertIsNone(take_permit(directory, 1_100.0))
        self.assertEqual(permit_open(directory, newer["event"], REF, 1_100.0), "DUPLICATE_OPEN")
        self.assertFalse((directory / "open-permit.json").exists())

    def test_v1_duplicate_and_unacked_events_do_not_queue_an_open(self):
        directory = Path("/tmp/wake-permit-closed")
        _clear(directory)
        v1 = build(
            event_id=new_event_id(),
            source="unread-indicator-hint",
            observed_at="2026-11-15T00:00:00Z",
            conversation_scope="contact-a",
        )
        _write_item(directory, v1, "acked", "acked")
        touch_session(directory, REF, 1_000.0)
        self.assertEqual(permit_open(directory, v1["eventId"], REF, 1_100.0), "V1_SCOPE")
        self.assertFalse((directory / "open-permit.json").exists())
        duplicate_payload = build_v2(event_id=new_event_id(), observed_at="2026-11-15T00:00:01Z", chat_ref=REF)
        _write_item(directory, duplicate_payload, "acked", "duplicate")
        self.assertEqual(permit_open(directory, duplicate_payload["eventId"], REF, 1_100.0), "DUPLICATE_EVENT")
        rejected = build_v2(event_id=new_event_id(), observed_at="2026-11-15T00:00:02Z", chat_ref=REF)
        _write_item(directory, rejected, "rejected", "REJECTED")
        self.assertEqual(permit_open(directory, rejected["eventId"], REF, 1_100.0), "NOT_ACKED")
        self.assertEqual(permit_open(directory, new_event_id(), REF, 1_100.0), "UNKNOWN_EVENT")
        self.assertEqual(permit_open(directory, "not-an-event", REF, 1_100.0), "MALFORMED")

    def test_cli_refuses_a_payload_target_and_prints_only_the_code(self):
        directory = Path("/tmp/wake-permit-cli")
        _clear(directory)
        env = {"WHATSAPP_WAKE_STORE": str(directory), "WHATSAPP_WAKE_CONFIG": ""}
        code = main(["wake", "permit-open", "--event", new_event_id(), "--ref", REF, "--target", TOKEN], env)
        self.assertEqual(code, 2)
        self.assertFalse((directory / "open-permit.json").exists())

    def test_host_session_survives_v1_and_take_permit_returns_only_the_ref(self):
        directory = Path("/tmp/wake-permit-host")
        _clear(directory)
        made, _clock, _log, transport = pipeline(
            directory,
            transport=Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')]),
            mode="test-receipt",
        )
        env = {
            "PATH": os.environ.get("PATH", ""),
            "WHATSAPP_WAKE_CONFIG": "",
            "WHATSAPP_WAKE_ENABLED": "1",
            "WHATSAPP_WAKE_URL": "http://127.0.0.1:9/",
            "WHATSAPP_WAKE_AUTHORIZATION": "local-test-only",
            "WHATSAPP_WAKE_ALLOWLIST_LABEL": "contact-a",
            "WHATSAPP_WAKE_STORE": str(directory),
            "WHATSAPP_WAKE_WIRE": "v1",
        }
        stdout = io.BytesIO()
        run_stdio(
            env,
            io.BytesIO(_frames({"v": 2, "kind": "person-hint", "chatRef": REF, "mark": "count", "count": 1})),
            stdout,
            made,
        )
        self.assertEqual(transport.calls, [])
        sessions = (directory / "person-sessions.json").read_text(encoding="utf-8")
        self.assertIn(REF, sessions)
        self.assertNotIn(TOKEN, sessions)
        held = apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 1}, pipeline=made, wire="v2")
        self.assertEqual(held["disposition"], "COUNT_BASELINE")
        posted = apply_person_hint(directory, {"chatRef": REF, "mark": "count", "count": 2}, pipeline=made, wire="v2")
        self.assertEqual(permit_open(directory, posted["event"], REF, 10**10), "SESSION_EXPIRED")
        now = time.time()
        touch_session(directory, REF, now)
        self.assertEqual(permit_open(directory, posted["event"], REF, now), "OPEN_QUEUED")
        reply = io.BytesIO()
        run_stdio(env, io.BytesIO(_frames({"v": 2, "kind": "take-permit"})), reply, made)
        frames = _codes(reply.getvalue())
        permit = next(frame for frame in frames if frame.get("kind") == "permit")
        self.assertEqual(permit["disposition"], "READY")
        self.assertEqual(permit["chatRef"], REF)
        self.assertNotIn("label", permit)
        self.assertNotIn(TOKEN, json.dumps(permit))
        again = io.BytesIO()
        run_stdio(env, io.BytesIO(_frames({"v": 2, "kind": "take-permit"})), again, made)
        second = next(frame for frame in _codes(again.getvalue()) if frame.get("kind") == "permit")
        self.assertEqual(second["disposition"], "NONE")


def _write_item(directory: Path, payload: dict, state: str, reason: str) -> None:
    path = directory / "outbox.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": []}
    current["items"].append(
        {
            "eventId": payload["eventId"],
            "payload": payload,
            "state": state,
            "attempts": 1,
            "nextAttemptAt": 0,
            "replacesId": 1,
            "source": payload["source"],
            "createdAt": 1,
            "updatedAt": 1,
            "ackedAt": 1,
            "reason": reason,
            "draft": None,
        }
    )
    path.write_text(json.dumps(current), encoding="utf-8")
