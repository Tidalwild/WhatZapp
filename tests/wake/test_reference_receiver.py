import unittest
from pathlib import Path

from examples.routine.reference_receiver import MAX_FOLLOWUP_ROUNDS, ReferenceReceiver
from wake.envelope import build_v3

EVENT_A = "event-a"
EVENT_B = "event-b"
EVENT_C = "event-c"
OBSERVED_A = 100
OBSERVED_B = 110
SAMPLED_AFTER_B = 140


def clock_alone_marks_covered(observed_at: int, sampled_at: int) -> bool:
    """Faulty rule, used only to show what this receiver must not do."""

    return observed_at < sampled_at


def assert_one_state(receiver: ReferenceReceiver) -> None:
    buckets = (
        receiver.pending,
        receiver.scheduled,
        receiver.inflight,
        receiver.covered,
        receiver.unresolved,
    )
    for event_id in receiver.seen:
        places = [event_id in bucket for bucket in buckets]
        if sum(places) != 1:
            raise AssertionError(event_id)


class LateWakeTests(unittest.TestCase):
    def test_unique_event_held_across_a_later_empty_sample_is_scheduled_not_covered(self):
        receiver = ReferenceReceiver()
        self.assertEqual(receiver.accept(EVENT_A, OBSERVED_A), "INSPECT")
        self.assertEqual(receiver.state(EVENT_A), "inflight")
        self.assertFalse(receiver.incoming)
        self.assertEqual(receiver.accept(EVENT_B, OBSERVED_B), "HELD")
        self.assertEqual(receiver.state(EVENT_B), "pending")
        self.assertTrue(clock_alone_marks_covered(OBSERVED_B, SAMPLED_AFTER_B))
        outcome = receiver.complete(
            SAMPLED_AFTER_B,
            new_turn=False,
            covered_event_ids=(),
            handled_message_keys=(),
        )
        self.assertEqual(outcome, "FOLLOWUP")
        self.assertEqual(receiver.state(EVENT_A), "scheduled")
        self.assertEqual(receiver.state(EVENT_B), "scheduled")
        self.assertNotIn(EVENT_A, receiver.covered)
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertFalse(receiver.incoming)
        self.assertEqual(receiver.request_send(), "NOT_SENT")
        self.assertEqual(receiver.sends, 0)
        assert_one_state(receiver)
        source = Path(__file__).resolve().parents[2].joinpath("examples/routine/reference_receiver.py").read_text(encoding="utf-8")
        self.assertNotIn("clock_alone_marks_covered", source)
        self.assertNotIn("observed_at <", source)
        self.assertNotIn("also proof", source)

    def test_the_same_gap_is_not_tied_to_one_pair_of_ids(self):
        for left, right, observed_left, observed_right, sampled in (
            ("event-1", "event-2", 10, 20, 30),
            ("event-q", "event-r", 50, 40, 45),
        ):
            receiver = ReferenceReceiver()
            self.assertEqual(receiver.accept(left, observed_left), "INSPECT")
            self.assertEqual(receiver.accept(right, observed_right), "HELD")
            self.assertEqual(receiver.complete(sampled, new_turn=False), "FOLLOWUP")
            self.assertEqual(receiver.state(right), "scheduled")
            self.assertNotIn(right, receiver.covered)
            assert_one_state(receiver)

    def test_only_an_explicit_captured_id_is_covered(self):
        receiver = ReferenceReceiver()
        receiver.accept(EVENT_A, OBSERVED_A)
        receiver.accept(EVENT_B, OBSERVED_B)
        outcome = receiver.complete(
            SAMPLED_AFTER_B,
            new_turn=False,
            covered_event_ids=(EVENT_A,),
            handled_message_keys=("row-1",),
        )
        self.assertEqual(outcome, "FOLLOWUP")
        self.assertEqual(receiver.state(EVENT_A), "covered")
        self.assertEqual(receiver.state(EVENT_B), "scheduled")
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertTrue(receiver.message_handled("row-1"))
        self.assertFalse(receiver.message_handled(EVENT_B))
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        self.assertEqual(receiver.state(EVENT_B), "inflight")
        self.assertNotIn(EVENT_B, receiver.covered)
        settled = receiver.complete(
            SAMPLED_AFTER_B + 10,
            new_turn=False,
            covered_event_ids=(EVENT_B,),
        )
        self.assertEqual(settled, "SETTLED")
        self.assertEqual(receiver.state(EVENT_B), "covered")
        assert_one_state(receiver)

    def test_a_repeated_event_id_does_not_start_another_worker(self):
        receiver = ReferenceReceiver()
        self.assertEqual(receiver.accept(EVENT_A, OBSERVED_A), "INSPECT")
        self.assertEqual(receiver.accept(EVENT_A, OBSERVED_A + 5), "DUPLICATE_EVENT")
        self.assertEqual(receiver.lock, EVENT_A)
        self.assertEqual(receiver.pending, set())
        self.assertEqual(receiver.state(EVENT_A), "inflight")

    def test_queued_then_failed_observation_stays_pending_and_uncovered(self):
        receiver = ReferenceReceiver()
        receiver.accept(EVENT_A, OBSERVED_A)
        receiver.accept(EVENT_B, OBSERVED_B)
        self.assertEqual(receiver.complete(SAMPLED_AFTER_B, new_turn=False), "FOLLOWUP")
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        self.assertEqual(receiver.state(EVENT_B), "inflight")
        self.assertEqual(receiver.fail("timeout"), "PENDING")
        self.assertEqual(receiver.state(EVENT_A), "pending")
        self.assertEqual(receiver.state(EVENT_B), "pending")
        self.assertNotIn(EVENT_A, receiver.covered)
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertNotIn(EVENT_B, receiver.unresolved)
        self.assertIn(EVENT_B, receiver.seen)
        self.assertIsNone(receiver.lock)
        self.assertEqual(receiver.fail("failed"), "NO_LOCK")
        self.assertEqual(receiver.schedule_pending(), "FOLLOWUP")
        self.assertEqual(receiver.state(EVENT_B), "scheduled")
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertEqual(receiver.request_send(), "NOT_SENT")
        assert_one_state(receiver)

    def test_several_ids_share_one_schedule_and_a_missed_sample_does_not_cover_them(self):
        receiver = ReferenceReceiver()
        receiver.accept(EVENT_A, OBSERVED_A)
        receiver.accept(EVENT_B, OBSERVED_B)
        receiver.accept(EVENT_C, OBSERVED_B + 1)
        self.assertEqual(receiver.complete(SAMPLED_AFTER_B, new_turn=False), "FOLLOWUP")
        self.assertEqual(receiver.scheduled, {EVENT_A, EVENT_B, EVENT_C})
        self.assertEqual(receiver.rounds, 1)
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        self.assertEqual(receiver.accept("event-d", SAMPLED_AFTER_B + 5), "HELD")
        self.assertEqual(receiver.begin_followup(), "BUSY")
        later = SAMPLED_AFTER_B + 20
        self.assertTrue(clock_alone_marks_covered(OBSERVED_B, later))
        self.assertEqual(receiver.complete(later, new_turn=False), "FOLLOWUP")
        self.assertEqual(receiver.state(EVENT_B), "scheduled")
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertEqual(receiver.state("event-d"), "scheduled")
        self.assertEqual(receiver.rounds, MAX_FOLLOWUP_ROUNDS)
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        self.assertEqual(receiver.complete(later + 20, new_turn=False), "FOLLOWUP_CAP")
        for event_id in (EVENT_A, EVENT_B, EVENT_C, "event-d"):
            self.assertEqual(receiver.state(event_id), "unresolved")
            self.assertIn(event_id, receiver.seen)
            self.assertNotIn(event_id, receiver.covered)
        self.assertEqual(receiver.request_send(), "NOT_SENT")
        assert_one_state(receiver)

    def test_round_cap_retains_unresolved_ids(self):
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
        self.assertEqual(receiver.state("event-3"), "unresolved")
        self.assertIn("event-3", receiver.unresolved)
        self.assertIn("event-3", receiver.seen)
        self.assertNotIn("event-3", receiver.covered)
        self.assertEqual(receiver.schedule_pending(), "SETTLED")
        self.assertEqual(receiver.state("event-3"), "unresolved")
        self.assertTrue(clock_alone_marks_covered(6, 9))
        named = receiver.complete(12, new_turn=False, covered_event_ids=("event-3",))
        self.assertEqual(named, "NO_LOCK")
        self.assertEqual(receiver.state("event-3"), "unresolved")
        receiver.accept("event-4", 13)
        self.assertEqual(receiver.state("event-4"), "inflight")
        self.assertEqual(
            receiver.complete(14, new_turn=False, covered_event_ids=("event-3",)),
            "FOLLOWUP_CAP",
        )
        self.assertEqual(receiver.state("event-3"), "covered")
        self.assertEqual(receiver.state("event-4"), "unresolved")
        self.assertIn("event-4", receiver.seen)
        assert_one_state(receiver)

    def test_a_v3_payload_is_only_an_event_id_and_a_clock(self):
        receiver = ReferenceReceiver()
        payload = build_v3(event_id="evt-" + "ab" * 16, observed_at="2026-01-01T00:00:00Z")
        self.assertEqual(set(payload), {"field", "eventId", "source", "observedAt", "testOnly"})
        self.assertEqual(receiver.accept_v3(payload), "INSPECT")
        self.assertEqual(receiver.state(payload["eventId"]), "inflight")
        self.assertFalse(receiver.incoming)
        self.assertEqual(receiver.accept_v3(payload), "DUPLICATE_EVENT")
        self.assertEqual(receiver.accept_v3({"field": "other"}), "UNUSABLE")
