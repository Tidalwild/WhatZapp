import json
import unittest
from pathlib import Path

from wake.envelope import SCHEMA_V3
from wake.pane import apply_pane_hint
from tests.wake.support import Scripted, pipeline


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in directory.iterdir():
            if child.is_file():
                child.unlink()
    directory.mkdir(parents=True, exist_ok=True)


class PaneHintTests(unittest.TestCase):
    def test_list_wire_posts_one_targetless_wake_and_replays_nothing(self):
        directory = Path("/tmp/wake-pane-hint")
        _clear(directory)
        transport = Scripted([(200, b""), (200, b'{"accepted":true,"unique":false,"duplicate":true}')])
        made, clock, _log, transport = pipeline(directory, transport=transport)
        held = apply_pane_hint(directory, {"generation": 1}, pipeline=made, wire="v1")
        self.assertEqual(held["disposition"], "SCHEMA_HELD")
        self.assertEqual(transport.calls, [])
        posted = apply_pane_hint(directory, {"generation": 1}, pipeline=made, wire="list")
        self.assertTrue(posted["posted"])
        item = made.outbox.items[posted["event"]]
        self.assertEqual(item.reason, "transport-accepted")
        payload = json.loads(transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual(payload["field"], SCHEMA_V3)
        self.assertEqual(set(payload), {"field", "eventId", "source", "observedAt", "testOnly"})
        self.assertNotIn("generation", payload)
        clock.advance(2)
        again = apply_pane_hint(directory, {"generation": 1}, pipeline=made, wire="list")
        self.assertEqual(again["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 1)
        clock.advance(2)
        nxt = apply_pane_hint(directory, {"generation": 2}, pipeline=made, wire="list")
        self.assertTrue(nxt["posted"])
        self.assertEqual(len(transport.calls), 2)
        stored = json.loads((directory / "pane-hint.json").read_text(encoding="utf-8"))
        self.assertEqual(set(stored), {"pending", "posted"})

    def test_an_unacked_wake_blocks_a_second_worker(self):
        directory = Path("/tmp/wake-pane-busy")
        _clear(directory)
        transport = Scripted([(200, b"")] * 3)
        made, _clock, _log, transport = pipeline(directory, transport=transport)
        first = apply_pane_hint(directory, {"generation": 1}, pipeline=made, wire="list")
        item = made.outbox.items[first["event"]]
        item.state = "in_flight"
        made.outbox.save()
        busy = apply_pane_hint(directory, {"generation": 2}, pipeline=made, wire="list")
        self.assertEqual(busy["disposition"], "BUSY")
        self.assertEqual(len(transport.calls), 1)
        item.state = "acked"
        item.reason = "transport-accepted"
        made.outbox.save()
        drained = apply_pane_hint(directory, {"generation": 2}, pipeline=made, wire="list")
        self.assertTrue(drained["posted"])
        self.assertEqual(len(transport.calls), 2)
        replay = apply_pane_hint(directory, {"generation": 2}, pipeline=made, wire="list")
        self.assertEqual(replay["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 2)
