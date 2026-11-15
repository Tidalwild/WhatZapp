import json
import unittest
from pathlib import Path

from wake.envelope import SCHEMA_V3, build_v3, new_event_id, validate
from wake.listchange import apply_list_change
from wake.resolve import permit_open
from tests.wake.support import Scripted, pipeline


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in directory.iterdir():
            if child.is_file():
                child.unlink()
    directory.mkdir(parents=True, exist_ok=True)


class ListChangeTests(unittest.TestCase):
    def test_default_wire_holds_and_list_wire_posts_no_target(self):
        directory = Path("/tmp/wake-list-change")
        _clear(directory)
        made, clock, _log, transport = pipeline(
            directory,
            transport=Scripted([(200, b'{"accepted":true,"unique":true,"duplicate":false}')] * 2),
        )
        held = apply_list_change(directory, {"mark": "count", "count": 2}, pipeline=made, wire="v1")
        self.assertEqual(held["disposition"], "SCHEMA_HELD")
        self.assertEqual(transport.calls, [])
        self.assertFalse((directory / "list-change.json").exists())
        baseline = apply_list_change(directory, {"mark": "count", "count": 2}, pipeline=made, wire="list")
        self.assertEqual(baseline["disposition"], "COUNT_BASELINE")
        self.assertEqual(transport.calls, [])
        clock.advance(2)
        risen = apply_list_change(directory, {"mark": "count", "count": 3}, pipeline=made, wire="list")
        self.assertTrue(risen["posted"])
        self.assertEqual(len(transport.calls), 1)
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["field"], SCHEMA_V3)
        self.assertEqual(set(payload), {"field", "eventId", "source", "observedAt", "testOnly"})
        self.assertEqual(payload["source"], "list-change")
        self.assertNotIn("chatRef", payload)
        self.assertNotIn("conversationScope", payload)
        self.assertNotIn("count", payload)
        self.assertTrue(all(value != 3 and value != "3" for value in payload.values()))
        stored = json.loads((directory / "list-change.json").read_text(encoding="utf-8"))
        self.assertEqual(set(stored), {"count", "generation"})
        again = apply_list_change(directory, {"mark": "count", "count": 3}, pipeline=made, wire="list")
        self.assertEqual(again["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 1)
        clock.advance(2)
        down = apply_list_change(directory, {"mark": "absent", "count": 0}, pipeline=made, wire="list")
        self.assertEqual(down["disposition"], "COUNT_CLEARED")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(permit_open(directory, risen["event"], "ref-0123456789abcdef", 1), "UNTARGETED")
        self.assertFalse((directory / "open-permit.json").exists())

    def test_v3_rejects_a_named_target(self):
        payload = build_v3(event_id=new_event_id(), observed_at="2026-11-15T00:00:00Z")
        validate(payload)
        payload["chatRef"] = "ref-0123456789abcdef"
        with self.assertRaises(Exception):
            validate(payload)
