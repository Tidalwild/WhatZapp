# Reference wake receiver

`reference_receiver.py` is a test implementation of the late-wake rule. It is not installed into Grok Bot. The extension does not import it. The native host does not import it. `wake/ledger.py` keeps late event ids pending in the store and does not import this file, mark those ids covered, or install this module into a bot. Updating this repository does not change a routine that is already running. Copy the rule into the receiver you operate. `python3 -m wake setup-check` reports this file as `example-only`.

## What you configure

Point your own webhook at `whatsapp-wake-test-v3`. Leave transport official. The posted object has `field`, `eventId`, `source`, `observedAt`, and `testOnly`. It has no message text. Your receiver, not this repository, decides what to do after the HTTP request is accepted.

Keep one worker on the WhatsApp Web window. Pass each new event id to the same receiver. When that worker is already reading the page, hold later ids. When the read finishes, tell the receiver the sample clock, whether the rendered tail had a new turn, the event ids that read explicitly included, and any message keys you actually compared. Do not pass the sample clock as a substitute for those ids.

## Late events

An event observed while the worker was busy stays pending. `observedAt` earlier than the sample clock does not cover it. An incomplete tail that reports no new turn does not cover it either.

Queue one followup for the pending ids. That schedule blocks a second schedule. The ids remain scheduled, not covered. Starting the followup makes them in flight, still not covered. Cover an id only when the finished observation lists it.

If that observation fails or times out, put the ids back to pending. Do not mark them covered and do not delete them. A later schedule may try once more. After two followup rounds, further ids stay unresolved: they remain stored, and they are not covered. Do not start a second worker. The wake itself is not a new incoming message. This example never sends.
