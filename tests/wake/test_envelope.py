import json
import unittest

from wake.envelope import (
    GENERATED_ID,
    SCHEMA_FIELD,
    EnvelopeError,
    build,
    new_event_id,
    validate,
)


class EnvelopeTests(unittest.TestCase):
    def test_generated_id_and_exact_field(self):
        event_id = new_event_id()
        self.assertRegex(event_id, GENERATED_ID)
        payload = build(
            event_id=event_id,
            source="linux-session-notify",
            observed_at="2026-11-12T06:22:00Z",
            conversation_scope="contact-a",
        )
        self.assertEqual(payload["field"], SCHEMA_FIELD)
        self.assertIs(payload["testOnly"], True)
        self.assertEqual(
            set(payload),
            {"field", "eventId", "source", "observedAt", "testOnly", "conversationScope"},
        )
        self.assertNotIn("contact-a-message", json.dumps(payload))

    def test_scope_is_optional(self):
        payload = build(
            event_id=new_event_id(),
            source="manual-connectivity-probe",
            observed_at="2026-11-12T06:22:00Z",
        )
        self.assertNotIn("conversationScope", payload)

    def test_rejects_malformed_and_untrusted_shapes(self):
        good = build(
            event_id=new_event_id(),
            source="android-listener",
            observed_at="2026-11-12T06:22:00Z",
        )
        cases = [
            {**good, "testOnly": False},
            {**good, "testOnly": "true"},
            {**good, "field": "other"},
            {**good, "source": "WhatsApp"},
            {**good, "source": "Google Chrome"},
            {**good, "target": "https://evil.invalid/x"},
            {**good, "body": "hello"},
            {**good, "eventId": "short"},
            {**good, "eventId": "evt-http-deadbeef"},
            {**good, "observedAt": "Monday 10:22 PM"},
            {**good, "conversationScope": "https://evil.invalid/x"},
            {key: value for key, value in good.items() if key != "eventId"},
            ["not-an-object"],
        ]
        for case in cases:
            with self.assertRaises(EnvelopeError):
                validate(case)

    def test_oversize_raw_shape_is_rejected(self):
        payload = build(
            event_id=new_event_id(),
            source="linux-session-notify",
            observed_at="2026-11-12T06:22:00Z",
        )
        payload["eventId"] = "e" * 400
        with self.assertRaises(EnvelopeError) as caught:
            validate(payload)
        self.assertEqual(caught.exception.reason, "malformed")


if __name__ == "__main__":
    unittest.main()
