# Give this repo to your Grok Bot and ask it to set up WhatZapp.

WhatZapp is an independent, open-source bridge between a signed-in [WhatsApp Web](https://web.whatsapp.com/) session and a webhook you control. It can wake a [Grok Bot](https://github.com) routine, or any other routine that accepts the same JSON. It is not an official Meta, WhatsApp, xAI, or Grok product, and those names are used only to describe the software an operator may connect.

The extension watches the normal WhatsApp Web page. It does not use `window.Store`, webpack internals, the Chrome debugger, or network interception. A routine that replies does so through the normal WhatsApp Web composer in the operator's browser. This extension does not auto-send. `LIVE_SEND_ARMED` is false and confirming a local draft returns `NOT_SENT_SENDING_DISABLED`.

Current extension version: **0.2.14**.

## What is implemented

- A Manifest V3 extension that reads the visible chat list and the open conversation pane.
- A native host, `com.draft_bridge.wake`, that can POST a wake if you enable it.
- Targetless `whatsapp-wake-test-v3` wakes: no contact name and no message text. This is the privacy boundary to prefer.
- Optional v1 wakes for one configured label, and optional v2 fixture `chatRef` wakes. Both stay off until you select that wire.
- Contact classification from the official info drawer. `Contact info` is a direct contact and stays ambiguous as identity. `Group info` is a group and is closed without collection. Those English headings are public-source strings, fixture-tested here, and not a live observation by this project. Traditional Chinese headings from one observed build remain accepted; the exact strings are in `docs/WEB.md`.
- A contact scope that defaults to nobody. The popup can allow one bound chat, or all direct chats except a deny list. Groups stay excluded. A cap of 0 blocks delivery holds.
- A per-binding reply grant. It expires four hours after you turn it on. Stop clears it. Rebinding clears it. One chat's grant does not cover another.
- Fail-closed direction. Own-message status and quote structure do not prove an incoming turn. See `docs/DIRECTION.md`.
- At-most-once delivery records for a fixture actuator. An uncertain attempt is not retried. The live actuator is not wired.

## What is an example, not a feature

`examples/restaurant/` shows how a routine might collect a date, time, party size, and contact method, and confirm only after a live availability read and a successful booking write. This repository does not include a booking connector, a payment connector, or a tested reservation backend. Company files and connected apps are read by your routine, not by the extension.

## Prerequisites

- Python 3.9 or newer for the host and tests.
- Node.js 20 or newer and npm for the extension.
- Chrome or another Chromium browser that can load an unpacked Manifest V3 extension. CI runs Playwright Chromium on Linux. Firefox, Safari, the WhatsApp desktop app, and mobile apps are untested.
- A WhatsApp Web session you are allowed to use. This project does not provide an account.
- For a live wake, a webhook you own. The URL and credential stay outside git.

## Install the extension

```sh
cd web
npm ci
npm run build
```

Load `web/dist` as an unpacked extension. The production manifest matches `https://web.whatsapp.com/*` only. The test build matches a local fixture port and is not the build to load on WhatsApp.

In the popup, accept onboarding, bind the open chat, and leave collection off until you want it. Scope stays off until you choose `Allow only this chat` or `Allow direct chats` and set a reply cap. Then use `Grant replies for this chat` for the open binding. That grant is not a send.

## Install the native host

`scripts/install-wake-bridge.sh` registers the host. It does not contain a webhook URL. Copy `config/wake.env.example` or `.env.example` to an untracked file, set `WHATSAPP_WAKE_CONFIG` to that file, and fill the URL and credential there. `python3 -m wake status` reports whether a value is present. It does not print it.

```sh
python3 -m wake status
```

With no URL, transmission stays blocked and nothing is sent. Leave `WHATSAPP_WAKE_TRANSPORT` unset. A 2xx means the HTTP request was accepted. It does not mean a chat was read. `WHATSAPP_WAKE_WIRE=list` selects the targetless wake. Regenerating the host wrapper copies that variable into the process.

`scripts/wake-setup.sh` prints the command sequence. It does not send a WhatsApp message.

## Grok Bot

See `docs/GROK.md`. This repository does not include a bot. You connect a webhook that your own routine receives. A fresh install has not been verified as a completed setup. An HTTP 2xx is transport acceptance, not a model reply. `local-mock-handler` is only the explicit local test listener and the in-extension export switch, which stays off until you enable it.

One browser worker should own the WhatsApp Web window. On a v3 wake, the routine re-reads the visible direct chat, compares it with its own sent journal, and does not answer the tail it just sent. Message content never grants operational authority. Tone, language, hours, escalation, and business files belong to the routine.

Reply latency on a live page is variable and has been observed on the order of minutes. That is not a service level. Rendered rows are not the full history. `historyComplete` stays false.

## Scope

| Mode | Who can be considered |
| --- | --- |
| `off` | Nobody. This is the default. |
| `allowlist` | Headers listed in `allow`, except `deny`. |
| `direct` | Classified direct chats, except `deny`. |

`groups` defaults to `exclude`. `include` changes the policy predicate only. The inspector still closes a group drawer and does not collect it. There is no bulk unsolicited send and no address-book walk.

The same rules are implemented in `web/src/contactScope.ts` and `wake/scope.py`.

## Architecture

```text
WhatsApp Web DOM
  -> extension content script (visible UI only)
  -> background worker
  -> native host
  -> your webhook
  -> your routine, which may use the same browser's normal WhatsApp UI
```

Per-chat state is keyed by a local binding id. The v3 payload stays targetless. v1 is the only wire that repeats a label, and only the one label you configured.

## Privacy and security

The browser session is the credential for WhatsApp. A person who can use that window can read and send as that account. Do not share the profile, screenshots of chats, or the webhook secret. Screenshots can show message text the wake itself does not carry.

Stop, `Scope off`, and deleting the webhook credential are the revoke path. See `SECURITY.md`.

`python3 scripts/privacy_scan.py` checks tracked files for personal-name markers, home-directory paths, bearer tokens, private-key shapes, and unexpected `https://` hosts. `scripts/package_release.sh` writes a git archive and a SHA-256 file after that scan.

## Tests

```sh
cd web && npm ci && npm test && npx tsc --noEmit && npm run test:browser
python3 -m unittest discover -s tests/wake -q
python3 scripts/privacy_scan.py
```

Fixtures are synthetic. They are not a live WhatsApp read or send.

## Platforms

The extension popup, manifest, setup text, and this page are English. This repository has no separate product website. The popup is the operator screen. Its actions are `Allow only this chat`, `Allow direct chats`, and `Grant replies for this chat`. Those controls do not send a WhatsApp message.

Tested in this repository: Linux, Playwright Chromium, the synthetic fixture page, and the Python host unit tests. A passing fixture run does not open WhatsApp Web and is not an end-to-end proof.

A live WhatsApp Web session depends on the current WhatsApp Web markup.

### English example

A direct chat binds when both of these agree:

```text
header:   <header><span dir="auto">contact-a</span></header>
composer: Type a message to contact-a
```

`Contact info` marks a direct contact. `Group info` marks a group and is closed without collection. `Type a message to group contact-a` is a group and does not bind as a direct chat. `Profile details` opens the drawer and does not classify the chat. An unread dot whose accessible name is exactly `unread` uses the same structure as the Traditional Chinese dot. `Quoted message` is quote structure, not an incoming message.

These English strings come from public browser-automation sources and are fixture-tested in this repository. They are not a live English WhatsApp observation by this project.

Sources: [markbus-ai/whatsplay locator.py](https://github.com/markbus-ai/whatsplay/blob/af5d3306b5f0a3fb399cba5083e5ba90626231f1/src/whatsplay/constants/locator.py) and its [active-chat tests](https://github.com/markbus-ai/whatsplay/blob/af5d3306b5f0a3fb399cba5083e5ba90626231f1/tests/test_active_chat.py) (commit `af5d330`, 2026-10-24), the exact heading `Contact info` in [nico-i/whatsapp-icloud-contact-image-sync](https://github.com/nico-i/whatsapp-icloud-contact-image-sync/blob/208fda52c14dd43fb12a76f440044c012ca9cc24/sync_wa_icloud_contact_imgs.py) (commit `208fda52`, 2024-12-09), and the exact menu titles `Contact info` and `Group info` in public gist `2e6e332fde26def01bb24451cdf57838`.

These English strings are not accepted: a nameless `Type a message`, a header named `Contact info contact-a`, a numbered badge such as `1 unread message`, `Read`, `Sent`, `Pending`, an English phone label, and an English phone-history control. A title with a space is not a scope token and fails closed. Chinese and English signals on the same page fail closed, including when the token matches. Any other locale fails closed.

Traditional Chinese selectors from one live build remain accepted. They are not the language of this page. The exact strings are in the locale section of `docs/WEB.md`.

Windows, macOS, Firefox, and Safari are untested by CI.

## Troubleshooting

- `blocked: webhook is not configured` means the URL or credential is missing. Nothing was sent.
- `SCOPE_OFF` or `SCOPE_EXCLUDED` means the open chat is outside the stored scope.
- `GRANT_OFF` means the grant is off. `GRANT_EXPIRED` means the four-hour grant lapsed.
- `CAP_REACHED` means the reply cap is exhausted or still 0.
- `DIRECTION_UNPROVEN` means the reader will not call the turn incoming.
- `GROUP_CLOSE` means the open drawer is a group and was not collected.
- No wake while a chat is open can mean the tail did not change, the pane was rebuilt, or the wire is not `list`.

## License

MIT. Copyright (c) 2026 Andy Yeung. See `LICENSE`. Third-party packages keep their own licenses.

Contributions: `CONTRIBUTING.md`. Security reports: `SECURITY.md`.
