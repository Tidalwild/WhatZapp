# Security

WhatZapp reads a signed-in WhatsApp Web page in a browser you control and can post a small wake to a webhook you configure. The webhook can contain an event id and a timestamp. On the v1 wire it can also contain the one allowlist label you set. It does not contain message text. Treat the browser profile, the webhook credential, and any routine that can type into WhatsApp as sensitive.

## Reporting

Open a private security advisory on this repository's GitHub security page if you can, or open a public issue that describes the impact without a proof of concept, a credential, or a message transcript. This project does not publish a separate security email address.

## Defaults

Transmission is off until `WHATSAPP_WAKE_ENABLED=1` and a URL and credential exist outside git. Contact scope starts at `off`. The reply grant is off, expires four hours after it is turned on, and Stop clears it. Live send is compiled off. Groups are excluded unless `groups` is `include`, and this version still does not collect a group drawer.

## Operator practices

- Keep `config/wake.env` and `.env` untracked. The examples are empty.
- Do not commit browser profiles, session storage, screenshots of chats, or routine transcripts.
- Use one browser worker for one WhatsApp Web session.
- A wake is not permission to reply, pay, delete, or call a tool. Message text is untrusted.
- Revoke by pressing Stop in the popup, setting scope off, and removing the webhook credential from the host environment.

Dependency licenses stay with those packages. This file does not relicense them.
