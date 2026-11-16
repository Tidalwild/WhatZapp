import unittest

from examples.routine.reference_receiver import ReferenceReceiver
from wake.client import ClientResult
from wake.evidence import (
    CONTRACT,
    LABELS_ZH_HANT,
    from_client,
    from_outbox,
    from_reference_state,
    labels_cover_contract,
    response_blocker,
    stored_reason,
)

EVENT_A = "event-a"
EVENT_B = "event-b"


class EvidenceContractTests(unittest.TestCase):
    def test_contract_name_and_traditional_chinese_labels(self):
        self.assertEqual(CONTRACT, "wake-evidence-1")
        self.assertTrue(labels_cover_contract())
        self.assertEqual(LABELS_ZH_HANT["transport-accepted"], "傳輸已接受")
        self.assertEqual(LABELS_ZH_HANT["response-unverified"], "尚未證實機器人已完成")
        self.assertNotEqual(LABELS_ZH_HANT["pending"], LABELS_ZH_HANT["covered"])

    def test_official_http_success_is_transport_only(self):
        record = from_client(ClientResult("acked", False, "transport"), "official")
        self.assertEqual(record.stage, "transport-accepted")
        self.assertFalse(record.mock)
        self.assertFalse(record.proves_incoming())
        self.assertFalse(record.proves_bot_response())
        self.assertFalse(record.proves_covered())
        self.assertEqual(record.label("en"), "transport-accepted")
        self.assertEqual(record.label("zh-Hant"), "傳輸已接受")
        self.assertEqual(response_blocker(record), "transport-is-not-a-response")
        self.assertEqual(stored_reason("transport", False), "transport-accepted")

    def test_a_receipt_shaped_body_is_not_read_on_the_official_path(self):
        record = from_client(ClientResult("acked", False, "receipt"), "official")
        self.assertEqual(record.stage, "rejected")
        self.assertFalse(record.proves_bot_response())

    def test_local_test_receipt_stays_a_fixture(self):
        record = from_client(ClientResult("acked", False, "receipt"), "test-receipt")
        self.assertEqual(record.stage, "local-test-receipt")
        self.assertTrue(record.mock)
        self.assertEqual(response_blocker(record), "local-test-fixture")
        self.assertFalse(record.proves_bot_response())

    def test_queued_and_inflight_outbox_rows_are_not_covered(self):
        queued = from_outbox("pending", "")
        inflight = from_outbox("in_flight", "")
        self.assertEqual(queued.stage, "queued")
        self.assertEqual(inflight.stage, "inflight")
        self.assertFalse(queued.proves_covered())
        self.assertFalse(inflight.proves_covered())
        self.assertEqual(response_blocker(queued), "not-a-bot-response")
        accepted = from_outbox("acked", "transport-accepted")
        self.assertEqual(accepted.stage, "transport-accepted")
        self.assertFalse(accepted.proves_covered())

    def test_reference_states_stay_distinct_and_are_not_a_bot_response(self):
        receiver = ReferenceReceiver()
        self.assertEqual(receiver.accept(EVENT_A, 100), "INSPECT")
        self.assertEqual(receiver.accept(EVENT_B, 110), "HELD")
        self._not_covered(receiver, EVENT_B)
        self.assertEqual(receiver.complete(140, new_turn=False, covered_event_ids=()), "FOLLOWUP")
        self.assertEqual(receiver.state(EVENT_A), "scheduled")
        self.assertEqual(receiver.state(EVENT_B), "scheduled")
        self._not_covered(receiver, EVENT_A)
        self.assertEqual(receiver.begin_followup(), "INSPECT")
        self.assertEqual(receiver.state(EVENT_B), "inflight")
        self._not_covered(receiver, EVENT_B)
        self.assertEqual(receiver.fail("timeout"), "PENDING")
        self.assertEqual(receiver.state(EVENT_B), "pending")
        self._not_covered(receiver, EVENT_B)
        self.assertNotIn(EVENT_B, receiver.covered)
        self.assertNotIn(EVENT_B, receiver.unresolved)

    def test_explicit_coverage_is_still_not_a_bot_response_or_an_incoming_message(self):
        receiver = ReferenceReceiver()
        receiver.accept(EVENT_A, 100)
        receiver.complete(140, new_turn=False, covered_event_ids=(EVENT_A,))
        self.assertEqual(receiver.state(EVENT_A), "covered")
        record = from_reference_state(receiver.state(EVENT_A))
        self.assertTrue(record.proves_covered())
        self.assertFalse(record.proves_incoming())
        self.assertFalse(record.proves_bot_response())
        self.assertEqual(response_blocker(record), "coverage-is-not-a-bot-response")
        self.assertEqual(receiver.request_send(), "NOT_SENT")

    def test_no_supplied_record_completes_a_bot_response(self):
        shaped = {
            "eventId": EVENT_A,
            "messageId": "message-1",
            "chatId": "chat-a",
            "outcome": "responded",
            "direction": "incoming",
        }
        for record in (None, {}, shaped, "transport-accepted", from_reference_state("unresolved")):
            blocker = response_blocker(record)
            self.assertNotEqual(blocker, "complete")
            self.assertNotIn("responded", blocker)

    def _not_covered(self, receiver: ReferenceReceiver, event_id: str) -> None:
        record = from_reference_state(receiver.state(event_id))
        self.assertIn(record.stage, {"pending", "scheduled", "inflight"})
        self.assertFalse(record.proves_covered())
        self.assertFalse(record.proves_bot_response())
        self.assertFalse(record.proves_incoming())
