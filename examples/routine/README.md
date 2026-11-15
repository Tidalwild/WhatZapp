# Reference wake receiver

`reference_receiver.py` is a test implementation of the late-wake rule. It is not installed into Grok Bot. The extension does not import it. The native host does not import it. Updating this repository does not change a routine that is already running. Copy the rule into the receiver you operate.

## What you configure

Point your own webhook at `whatsapp-wake-test-v3`. Leave transport official. The posted object has `field`, `eventId`, `source`, `observedAt`, and `testOnly`. It has no message text. Your receiver, not this repository, decides what to do after the HTTP request is accepted.

Keep one worker on the WhatsApp Web window. Pass each new event id to the same receiver. When that worker is already reading the page, hold later ids. When the read finishes, tell the receiver the sample clock, whether the rendered tail had a new turn, the event ids that read explicitly included, and any message keys you actually compared. Do not pass the sample clock as a substitute for those ids.

## Late events

An event observed while the worker was busy still needs a followup when all of these are true:

- the event id has not been seen before
- the finished sample did not name that event id
- no followup is already queued for that event id

`observedAt` earlier than the sample clock is not one of those facts. An incomplete tail that reports no new turn does not cover the held event. Queue one followup and put every such id on it. Do not start a second worker. After that followup is read, do not queue those same ids again. A later new id can join a new followup until two followup rounds have been used; further ids stay uncapped rather than marked covered. The wake itself is not a new incoming message. This example never sends.
