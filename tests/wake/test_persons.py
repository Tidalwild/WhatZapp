import json
import unittest
from pathlib import Path

from wake.envelope import SCHEMA_FIELD, SCHEMA_V2, build, build_v2, validate
from wake.page import apply_page
from wake.persons import apply_person_hint
from wake.read import bind_metadata
from tests.wake.support import Scripted, pipeline

REF_A = "ref-0123456789abcdef"
REF_B = "ref-fedcba9876543210"
TOKEN = "person-b"


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in directory.iterdir():
            if child.is_file():
                child.unlink()
    directory.mkdir(parents=True, exist_ok=True)


class PersonWakeTests(unittest.TestCase):
    def test_v1_holds_a_person_hint_and_still_wakes_fixture_on_the_old_wire(self):
        directory = Path("/tmp/wake-person-v1")
        _clear(directory)
        made, _clock, log, transport = pipeline(
            directory,
            transport=Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')]),
        )
        held = apply_person_hint(
            directory,
            {"chatRef": REF_A, "mark": "count", "count": 2},
            pipeline=made,
            wire="v1",
        )
        self.assertEqual(held["disposition"], "SCHEMA_HELD")
        self.assertFalse(held["posted"])
        self.assertEqual(transport.calls, [])
        self.assertFalse((directory / "person-counts.json").exists())
        bind_metadata(directory, "contact-a")
        baseline = apply_page(directory, _count(1), allowlist="contact-a", pipeline=made)
        self.assertEqual(baseline["disposition"], "COUNT_BASELINE")
        rose = apply_page(directory, _count(2), allowlist="contact-a", pipeline=made)
        self.assertEqual(rose["disposition"], "COUNT_UP")
        self.assertTrue(rose["posted"])
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["field"], SCHEMA_FIELD)
        self.assertEqual(payload["conversationScope"], "contact-a")
        blob = json.dumps(payload) + log.text()
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(REF_A, blob)

    def test_v2_routes_two_people_and_suppresses_repeat_decrease_and_clear(self):
        directory = Path("/tmp/wake-person-v2")
        _clear(directory)
        made, _clock, log, transport = pipeline(
            directory,
            transport=Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')] * 3),
        )
        first = apply_person_hint(directory, {"chatRef": REF_A, "mark": "count", "count": 1}, pipeline=made, wire="v2")
        second = apply_person_hint(directory, {"chatRef": REF_B, "mark": "count", "count": 1}, pipeline=made, wire="v2")
        self.assertEqual(first["disposition"], "COUNT_BASELINE")
        self.assertEqual(second["disposition"], "COUNT_BASELINE")
        self.assertEqual(transport.calls, [])
        rose_a = apply_person_hint(directory, {"chatRef": REF_A, "mark": "count", "count": 2}, pipeline=made, wire="v2")
        rose_b = apply_person_hint(directory, {"chatRef": REF_B, "mark": "count", "count": 3}, pipeline=made, wire="v2")
        self.assertTrue(rose_a["posted"])
        self.assertTrue(rose_b["posted"])
        self.assertNotEqual(rose_a["event"], rose_b["event"])
        payloads = [json.loads(call["body"].decode("utf-8")) for call in transport.calls]
        self.assertEqual([item["chatRef"] for item in payloads], [REF_A, REF_B])
        for payload in payloads:
            self.assertEqual(payload["field"], SCHEMA_V2)
            self.assertNotIn("conversationScope", payload)
            self.assertNotIn("count", payload)
            self.assertNotIn(TOKEN, json.dumps(payload))
        repeat = apply_person_hint(directory, {"chatRef": REF_A, "mark": "count", "count": 2}, pipeline=made, wire="v2")
        down = apply_person_hint(directory, {"chatRef": REF_A, "mark": "count", "count": 1}, pipeline=made, wire="v2")
        clear = apply_person_hint(directory, {"chatRef": REF_B, "mark": "absent", "count": 0}, pipeline=made, wire="v2")
        self.assertEqual(repeat["disposition"], "NO_NEW")
        self.assertEqual(down["disposition"], "COUNT_DOWN")
        self.assertEqual(clear["disposition"], "COUNT_CLEARED")
        self.assertEqual(len(transport.calls), 2)
        stored = (directory / "person-counts.json").read_text(encoding="utf-8")
        self.assertNotIn(TOKEN, stored)
        self.assertNotIn("contact-a", stored + log.text())
        replay = validate(payloads[0])
        self.assertEqual(replay["chatRef"], REF_A)
        with self.assertRaises(Exception):
            validate({**build_v2(event_id=payloads[0]["eventId"], observed_at=payloads[0]["observedAt"], chat_ref=REF_A), "conversationScope": "contact-a"})
        legacy = build(
            event_id="evt-" + "ab" * 16,
            source="unread-indicator-hint",
            observed_at="2026-11-15T00:00:00Z",
            conversation_scope="contact-a",
        )
        self.assertEqual(validate(legacy)["conversationScope"], "contact-a")


def _count(count: int) -> dict:
    return {
        "layout": "chat-list-contract",
        "boundLabel": "contact-a",
        "matches": 1,
        "position": 0,
        "unread": None,
        "mark": "count",
        "count": count,
        "otherChanges": 0,
    }


if __name__ == "__main__":
    unittest.main()
