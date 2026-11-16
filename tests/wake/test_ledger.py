import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from wake.__main__ import _print_bind
from wake.ledger import Ledger, load, note_held, note_posted, save
from wake.listchange import apply_list_change
from wake.page import apply_page
from wake.pane import apply_pane_hint
from wake.read import bind_local
from tests.wake.support import pipeline


def _clear(directory: Path) -> None:
    if directory.exists():
        for child in directory.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
    directory.mkdir(parents=True, exist_ok=True)


class LedgerTests(unittest.TestCase):
    def test_same_event_is_duplicate_and_a_later_event_stays_pending(self):
        directory = Path("/tmp/wake-ledger-events")
        _clear(directory)
        event = "evt-" + "ab" * 16
        self.assertEqual(note_posted(directory, event, "pane:1", 10), "INSPECT")
        self.assertEqual(note_posted(directory, event, "pane:1", 11), "DUPLICATE_EVENT")
        outcome, late = note_held(directory, "pane:2", 12)
        self.assertEqual(outcome, "HELD")
        self.assertNotEqual(late, event)
        self.assertTrue(late.startswith("evt-"))
        self.assertEqual(note_held(directory, "pane:2", 13)[0], "DUPLICATE")
        ledger = load(directory)
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.state(event), "inflight")
        self.assertEqual(ledger.state(late), "pending")
        self.assertEqual(ledger.covered, set())
        self.assertEqual(ledger.message_keys, {"pane:1", "pane:2"})
        self.assertTrue(ledger.message_keys.isdisjoint(ledger.seen))
        self.assertEqual(ledger.note_message(event), "UNUSABLE")
        self.assertEqual(ledger.note_message("quoted-message"), "ADDED")
        self.assertEqual(ledger.accept("quoted-message", 14), "UNUSABLE")
        self.assertNotIn("quoted-message", ledger.seen)
        self.assertEqual(ledger.covered, set())

    def test_clock_and_followup_cap_do_not_cover_or_drop_ids(self):
        ledger = Ledger()
        first = "evt-" + "11" * 16
        late = "evt-" + "22" * 16
        self.assertEqual(ledger.accept(first, 5), "INSPECT")
        self.assertEqual(ledger.accept(late, 6), "HELD")
        self.assertEqual(ledger.complete(100, new_turn=True, covered_event_ids=(), handled_message_keys=("quoted-message",)), "FOLLOWUP")
        self.assertEqual(ledger.covered, set())
        self.assertEqual(ledger.state(first), "scheduled")
        self.assertEqual(ledger.state(late), "scheduled")
        self.assertIn("quoted-message", ledger.message_keys)
        self.assertNotIn("quoted-message", ledger.seen)
        third = "evt-" + "33" * 16
        self.assertEqual(ledger.accept(third, 7), "COALESCED")
        self.assertEqual(ledger.state(third), "scheduled")
        self.assertIsNone(ledger.lock)
        self.assertEqual(ledger.begin_followup(), "INSPECT")
        self.assertEqual(ledger.state(first), "inflight")
        self.assertEqual(ledger.fail("timeout"), "PENDING")
        self.assertEqual(ledger.state(first), "pending")
        self.assertEqual(ledger.fail("failed"), "NO_LOCK")
        self.assertEqual(ledger.schedule_pending(), "FOLLOWUP")
        self.assertEqual(ledger.rounds, 2)
        self.assertEqual(ledger.begin_followup(), "INSPECT")
        self.assertEqual(ledger.fail("failed"), "PENDING")
        self.assertEqual(ledger.schedule_pending(), "FOLLOWUP_CAP")
        self.assertEqual(ledger.state(late), "unresolved")
        self.assertEqual(ledger.state(third), "unresolved")
        self.assertEqual(ledger.covered, set())
        self.assertEqual(ledger.pending, set())
        directory = Path("/tmp/wake-ledger-cap")
        _clear(directory)
        self.assertTrue(save(directory, ledger))
        loaded = load(directory)
        self.assertEqual(loaded.state(late), "unresolved")
        self.assertEqual(loaded.accept(first, 9), "DUPLICATE_EVENT")
        self.assertEqual(loaded.covered, set())
        blob = (directory / "event-ledger.json").read_text(encoding="utf-8")
        self.assertNotIn("quoted-message-body", blob)
        self.assertIn(late, json.loads(blob)["unresolved"])

    def test_a_listed_observation_covers_only_the_named_id(self):
        ledger = Ledger()
        event = "evt-" + "44" * 16
        other = "evt-" + "55" * 16
        self.assertEqual(ledger.accept(event, 1), "INSPECT")
        self.assertEqual(ledger.accept(other, 2), "HELD")
        self.assertEqual(ledger.complete(3, new_turn=True, covered_event_ids=(event,)), "FOLLOWUP")
        self.assertEqual(ledger.state(event), "covered")
        self.assertEqual(ledger.state(other), "scheduled")
        self.assertNotIn(other, ledger.covered)

    def test_message_binding_does_not_claim_direction(self):
        directory = Path("/tmp/wake-ledger-bind")
        _clear(directory)
        buffer = StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(_print_bind(bind_local(directory, "contact-a", "Me")), 0)
        text = buffer.getvalue()
        self.assertIn("direction: unproven\n", text)
        self.assertNotIn("direction: proven", text)

    def test_symlink_ledger_does_not_post(self):
        directory = Path("/tmp/wake-ledger-link")
        _clear(directory)
        (directory / "event-ledger.json").symlink_to(directory / "other.json")
        made, _clock, _log, transport = pipeline(directory)
        result = apply_pane_hint(directory, {"generation": 1}, pipeline=made, wire="list")
        self.assertEqual(result["disposition"], "UNREADABLE")
        self.assertFalse(result["posted"])
        self.assertEqual(transport.calls, [])

    def test_list_rise_after_transport_ack_is_held_once(self):
        directory = Path("/tmp/wake-ledger-list")
        _clear(directory)
        made, clock, _log, transport = pipeline(directory)
        self.assertEqual(apply_list_change(directory, {"mark": "count", "count": 2}, pipeline=made, wire="list")["disposition"], "COUNT_BASELINE")
        clock.advance(2)
        risen = apply_list_change(directory, {"mark": "count", "count": 3}, pipeline=made, wire="list")
        self.assertTrue(risen["posted"])
        self.assertFalse(risen["covered"])
        clock.advance(2)
        held = apply_list_change(directory, {"mark": "count", "count": 4}, pipeline=made, wire="list")
        self.assertEqual(held["disposition"], "HELD")
        self.assertFalse(held["posted"])
        self.assertFalse(held["covered"])
        self.assertNotEqual(held["event"], risen["event"])
        self.assertEqual(len(transport.calls), 1)
        clock.advance(2)
        again = apply_list_change(directory, {"mark": "count", "count": 4}, pipeline=made, wire="list")
        self.assertEqual(again["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 1)
        ledger = load(directory)
        self.assertEqual(ledger.state(risen["event"]), "inflight")
        self.assertEqual(ledger.state(held["event"]), "pending")
        self.assertEqual(ledger.covered, set())
        self.assertEqual(ledger.rounds, 0)
        self.assertTrue(ledger.message_keys.isdisjoint(ledger.seen))

    def test_open_tail_holds_a_later_row_and_stores_no_text(self):
        directory = Path("/tmp/wake-ledger-tail")
        _clear(directory)
        made, _clock, _log, transport = pipeline(directory)
        bind_local(directory, "contact-a", "Me")
        self.assertEqual(apply_page(directory, _tail(_SEEDS), allowlist="contact-a", pipeline=made)["disposition"], "BASELINE")
        first = apply_page(directory, _tail(_SEEDS + (("contact-a", "one-body", "09:02"),)), allowlist="contact-a", pipeline=made)
        self.assertEqual(first["disposition"], "ONE_INBOUND")
        self.assertTrue(first["posted"])
        self.assertFalse(first["covered"])
        second = apply_page(directory, _tail(_SEEDS + (("contact-a", "one-body", "09:02"), ("contact-a", "later-body", "09:04"))), allowlist="contact-a", pipeline=made)
        self.assertEqual(second["disposition"], "HELD")
        self.assertFalse(second["posted"])
        self.assertFalse(second["covered"])
        self.assertEqual(len(transport.calls), 1)
        third = apply_page(directory, _tail(_SEEDS + (("contact-a", "one-body", "09:02"), ("contact-a", "later-body", "09:04"))), allowlist="contact-a", pipeline=made)
        self.assertEqual(third["disposition"], "NO_NEW")
        self.assertEqual(len(transport.calls), 1)
        ledger = load(directory)
        self.assertEqual(ledger.covered, set())
        self.assertEqual(ledger.rounds, 0)
        self.assertEqual(len(ledger.pending), 1)
        self.assertTrue(ledger.message_keys.isdisjoint(ledger.seen))
        blob = "\n".join(path.read_text(encoding="utf-8") for path in directory.iterdir() if path.is_file())
        self.assertNotIn("one-body", blob)
        self.assertNotIn("later-body", blob)
        self.assertNotIn("Quoted message", blob)


_SEEDS = (("Me", "seed-one", "09:00"), ("contact-a", "seed-two", "09:01"))


def _tail(rows, header="contact-a"):
    return {
        "layout": "probe-contract",
        "header": header,
        "phase": "ready",
        "slots": [{"kind": "message", "sender": sender, "text": text, "timeText": clock} for sender, text, clock in rows],
    }
