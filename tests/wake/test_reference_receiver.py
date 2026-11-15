import unittest
from pathlib import Path

from examples.routine.reference_receiver import MAX_FOLLOWUP_ROUNDS, ReferenceReceiver
from wake.envelope import build_v3

EVENT_A = "event-a"
EVENT_B = "event-b"
EVENT_C = "event-c"
OBSERVED_A = 1_700_000_100
OBSERVED_B = 1_700_000_110
SAMPLED_AFTER_B = 1_700_000_140


def clock_alone_marks_covered(observed_at: int, sampled_at: int) -> bool:
    """Faulty rule, used only to show what this receiver must not do."""

    return observed_at < sampled_at


class LateWakeTests(unittest.TestCase):
    def test_unique_event_held_across_a_later_empty_sample_is_not_covered_by_the_clock(self):
        receiver = ReferenceReceiver()
        self.assertEqual(receiver.accept(EVENT_A, OBSERVED_A), "INSPECT")
        self.assertFalse(receiver.incoming)
        self.assertEqual(receiver.accept(EVENT_B, OBSERVED_B), "HELD")
        self.assertTrue(clock_alone_marks_covered(OBSERVED_B, SAMPLED_AFTER_B))
        outcome = receiver.complete(
            SAMPLED_AFTER_B,
            new_turn=False,
            covered_event_ids=(),
            handled_message_keys=(),
        )
        self.assertEqual(outcome, "FOLLOWUP")
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertIn(EVENT_B, receiver.queued)
        self.assertIn(EVENT_A, receiver.inspected)
        self.assertNotIn(EVENT_B, receiver.inspected)
        self.assertFalse(receiver.incoming)
        self.assertEqual(receiver.request_send(), "NOT_SENT")
        self.assertEqual(receiver.sends, 0)
        source = Path(__file__).resolve().parents[2].joinpath("examples/routine/reference_receiver.py").read_text(encoding="utf-8")
        self.assertNotIn("clock_alone_marks_covered", source)
        self.assertNotIn("observed_at <", source)

    def test_the_same_gap_is_not_tied_to_one_pair_of_ids(self):
        for left, right, observed_left, observed_right, sampled in (
            ("event-1", "event-2", 10, 20, 30),
            ("event-q", "event-r", 50, 40, 45),
        ):
            receiver = ReferenceReceiver()
            self.assertEqual(receiver.accept(left, observed_left), "INSPECT")
            self.assertEqual(receiver.accept(right, observed_right), "HELD")
            self.assertEqual(
                receiver.complete(sampled, new_turn=False),
                "FOLLOWUP",
            )
            self.assertIn(right, receiver.queued)
            self.assertNotIn(right, receiver.covered)

    def test_an_explicit_event_id_is_covered_and_a_message_key_is_not_that_id(self):
        receiver = ReferenceReceiver()
        receiver.accept(EVENT_A, OBSERVED_A)
        receiver.accept(EVENT_B, OBSERVED_B)
        outcome = receiver.complete(
            SAMPLED_AFTER_B,
            new_turn=False,
            covered_event_ids=(EVENT_B,),
            handled_message_keys=("row-1",),
        )
        self.assertEqual(outcome, "SETTLED")
        self.assertIn(EVENT_B, receiver.covered)
        self.assertEqual(receiver.queued, set())
        self.assertTrue(receiver.message_handled("row-1"))
        self.assertFalse(receiver.message_handled(EVENT_B))

    def test_a_repeated_event_id_does_not_start_another_worker(self):
        receiver = ReferenceReceiver()
        self.assertEqual(receiver.accept(EVENT_A, OBSERVED_A), "INSPECT")
        self.assertEqual(receiver.accept(EVENT_A, OBSERVED_A + 5), "DUPLICATE_EVENT")
        self.assertEqual(receiver.lock, EVENT_A)
        self.assertEqual(receiver.pending, [])

    def test_several_held_ids_share_one_followup_and_that_pass_does_not_loop(self):
        receiver = ReferenceReceiver()
        receiver.accept(EVENT_A, OBSERVED_A)
        receiver.accept(EVENT_B, OBSERVED_B)
        receiver.accept(EVENT_C, OBSERVED_B + 1)
        self.assertEqual(receiver.complete(SAMPLED_AFTER_B, new_turn=False), "FOLLOWUP")
        self.assertEqual(receiver.queued, {EVENT_B, EVENT_C})
        self.assertEqual(receiver.rounds, 1)
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        self.assertEqual(receiver.accept("event-d", SAMPLED_AFTER_B + 5), "HELD")
        self.assertEqual(receiver.begin_followup(), "BUSY")
        later = SAMPLED_AFTER_B + 20
        self.assertTrue(clock_alone_marks_covered(OBSERVED_B, later))
        self.assertEqual(receiver.complete(later, new_turn=False), "FOLLOWUP")
        self.assertIn(EVENT_B, receiver.followup_done)
        self.assertNotIn(EVENT_B, receiver.queued)
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertEqual(receiver.queued, {"event-d"})
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        self.assertEqual(receiver.complete(later + 20, new_turn=False), "SETTLED")
        self.assertIn("event-d", receiver.followup_done)
        self.assertEqual(receiver.rounds, MAX_FOLLOWUP_ROUNDS)
        self.assertEqual(receiver.request_send(), "NOT_SENT")

    def test_a_third_round_stays_uncovered_instead_of_being_marked_done_by_the_clock(self):
        receiver = ReferenceReceiver()
        receiver.accept("event-0", 1)
        receiver.accept("event-1", 2)
        self.assertEqual(receiver.complete(3, new_turn=False), "FOLLOWUP")
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        receiver.accept("event-2", 4)
        self.assertEqual(receiver.complete(5, new_turn=False), "FOLLOWUP")
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        receiver.accept("event-3", 6)
        self.assertEqual(receiver.complete(9, new_turn=False), "FOLLOWUP_CAP")
        self.assertIn("event-3", receiver.capped)
        self.assertNotIn("event-3", receiver.covered)
        self.assertNotIn("event-3", receiver.followup_done)
        self.assertTrue(clock_alone_marks_covered(6, 9))

    def test_a_v3_payload_is_only_an_event_id_and_a_clock(self):
        receiver = ReferenceReceiver()
        payload = build_v3(event_id="evt-" + "ab" * 16, observed_at="2026-01-01T00:00:00Z")
        self.assertEqual(set(payload), {"field", "eventId", "source", "observedAt", "testOnly"})
        self.assertEqual(receiver.accept_v3(payload), "INSPECT")
        self.assertFalse(receiver.incoming)
        self.assertEqual(receiver.accept_v3(payload), "DUPLICATE_EVENT")
        self.assertEqual(receiver.accept_v3({"field": "other"}), "UNUSABLE")
