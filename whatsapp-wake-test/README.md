# Local wake-test receipts

This directory is runtime state for the local test routine. It is not a
saved production routine and it does not contain a webhook URL or an
Authorization value.

The routine writes at most 100 event ids, a unique receipt, and a draft
placeholder. It does not read a chat and it does not send a WhatsApp message.
Receipt files are gitignored.
