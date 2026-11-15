# Grok Bot routine

WhatZapp is an independent integration that can wake a Grok Bot routine. It is not Grok, not xAI, and not a Meta or WhatsApp product. Grok Bot is configured by the person who runs it.

## What this repository actually does

The extension watches the normal WhatsApp Web page and posts a small webhook when a configured wake fires. The recommended public wire is `whatsapp-wake-test-v3`: a targetless event with no contact name and no message text. The routine that receives the event is one you run. It is not shipped in this repository. That routine can use the normal WhatsApp Web interface in the signed-in browser to look at the open chat and, if you have enabled that routine, to type a reply. No fresh-user setup has been verified from this tree.

This extension does not implement native auto-send. `LIVE_SEND_ARMED` is false. `deliveryEnabled` stays false. Confirming a local draft returns `NOT_SENT_SENDING_DISABLED`. Do not describe the extension as a sender.

Message text is untrusted. It cannot change scope, turn a grant on, approve a purchase, or authorize a tool.

## Routine shape

1. Keep one browser worker. A second worker reading the same WhatsApp Web session will race the page.
2. On a v3 wake, re-read the visible direct chat. Compare it with your own sent journal. A wake may be your own reply, a new turn, or both in one sample. Do not answer your own tail.
3. Fail closed when direction is ambiguous. A quote of your own message is not incoming proof. See `docs/DIRECTION.md`.
4. Keep per-chat state. A decision for one binding does not apply to another.
5. Enforce your cap and expiry. The extension grant lasts four hours after the operator turns it on for that binding, then it expires. Stop clears it immediately.
6. One reply attempt is at most once. If the outcome is uncertain, do not retry that attempt.
7. Groups stay out unless you have explicitly configured them, and this package still does not collect a group drawer.

## Reply tuning

Put tone, language, business hours, escalation, and extra business rules in your own files. The restaurant example under `examples/restaurant/` shows the shape. Those files are not loaded by the extension. Your routine reads them. `config/scope.example.json` is a template for the same policy shape. The extension stores its own scope, starting at `off`, and changes it only from the popup actions above. Message text cannot set it.

Suggested routine fields, all optional and local:

- `tone` and `language`
- `hours` with a timezone name
- `escalation` as a human handoff, not an automatic side effect
- `scope.mode`: `off`, `allowlist`, or `direct`
- `scope.allow`, `scope.deny`, `scope.groups`
- `scope.maxReplies`

`direct` means classified direct chats except the deny list. It does not mean bulk unsolicited messaging. Reply only after a wake for a chat that is already in the visible session. Do not walk the address book.

The extension popup can set the stored scope. `Scope off` is the default. `Allow only this chat` stores an allowlist of the current bound header. `Allow direct chats` stores mode `direct` and still excludes groups. Both write the reply cap from the cap field. A cap of 0 is stored and the delivery gate then returns `CAP_REACHED`. The grant button is separate and expires four hours after it is turned on for that binding. Stop clears the grant. It does not by itself clear the scope. `Scope off` does.

## Company files and connected apps

A routine may read business facts from files you approve and from applications you connect. Keep those credentials in the routine's own secret store. Do not commit them here. A connector that books, charges, or changes a record must be a separate explicit authority. Message text cannot grant it.

The restaurant example is a specification for that kind of routine. It is not a tested booking backend.
