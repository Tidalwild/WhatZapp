# Setup foundation

This page is the public baseline for a user-owned install. It records what this repository can prove. It is not a release claim, and a passing check is not a completed WhatsApp session.

`python3 -m wake setup-check` is the reproducible check. It does not call a webhook, open a browser, or print a URL, credential, or allowlist label.

## What the public tree shows

Re-run the named tests after you change the tree. A row is unverified when this repository has no test that exercises it.

| Capability | Evidence in this repository | Limit |
| --- | --- | --- |
| Visible-UI extension capture | `web/` unit and fixture tests | A fixture run does not open WhatsApp Web. |
| Native host wake | `tests/wake/` with a stand-in transport | No live webhook is part of the check. |
| Official HTTP 2xx | `wake/client.py`, `wake/evidence.py` | Stage `transport-accepted`. The body is ignored. |
| Local receipt body | `WHATSAPP_WAKE_TRANSPORT=test-receipt` and `python3 -m wake routine` | Labelled `local-mock-handler`. It is not the default and it is not a bot. |
| Late unique event | `examples/routine/reference_receiver.py` and `tests/wake/test_reference_receiver.py` | Reference only. `setup-check` fails if `wake/` or `web/src` imports it. |
| Direction | `docs/DIRECTION.md` and the web reader tests | Ambiguous rows stay unproven. Layout, a clock, and an unread mark are not incoming proof. |
| Sending | `LIVE_SEND_ARMED = false` in `web/src/replyDelivery.ts` | Default off. The reference `request_send` returns `NOT_SENT`. |
| Bot response | No module accepts a response callback | `response-interface: absent`. A caller-supplied dict is still unverified. |
| Fresh install through a real reply | Not exercised here | `fresh-setup: unproven`. |
| Another machine's deployment | Not in this repository | Unverified from this tree. |

## Architecture

The supported boundary is the webhook you configure outside git:

```text
WhatsApp Web, signed in by you
  -> unpacked extension, visible UI only
  -> native host com.draft_bridge.wake
  -> HTTPS POST of a validated wake envelope
  -> the routine you run
```

This repository does not include a bot and does not embed a maintainer account. You give the repository to your own bot. That bot may install and check this package. You link WhatsApp in your own browser and approve any later action. The host cannot see that approval.

The recommended wire is `whatsapp-wake-test-v3`: `field`, `eventId`, `source`, `observedAt`, and `testOnly`. It carries no contact name and no message text. v1 and v2 stay off until you select them.

WhatsApp Web is an unofficial page surface. Markup can change, and this project does not use a paid Meta official API and does not add a Meta fee. A webhook host you choose may have its own terms and charges. Those are not charges by this repository.

Trust stays split. The browser profile is the WhatsApp credential. The webhook credential stays in your untracked env file. Message text is untrusted and cannot change scope or authorize a send. The extension does not receive a model reply on the wake response.

## Evidence contract `wake-evidence-1`

Machine values are English. `Evidence.label("zh-Hant")` returns Traditional Chinese display text. The check prints `language-default: en` and `language-supported: zh-Hant`.

| Stage | Meaning | Not this stage |
| --- | --- | --- |
| `queued` 已排隊 | An outbox row is stored and waiting. | Not covered, not a response. |
| `inflight` 處理中 | The host is posting, or the reference worker holds the id. | Not covered. |
| `transport-accepted` 傳輸已接受 | Official HTTP 2xx. The body was not read. | Not a chat receipt, not a model reply, not exactly-once. |
| `legacy-409` 舊版停止 | Older duplicate stop. The body was not read. | Not a current receipt contract. |
| `retryable` 可再試 | The post can be tried again inside the existing attempt cap. | Not a new wake. |
| `rejected` 已拒絕 | The post will not be retried by this row. | Not a silent drop of a different id. |
| `local-test-receipt` 僅限本機測試回條 | Explicit local test transport only. | Not official, and the draft is a labelled fixture. |
| `pending` 待處理 | Reference: accepted, not yet scheduled. | Not covered. |
| `scheduled` 已排程 | Reference: one followup is queued. A second schedule is blocked. | Not covered and not inspected. |
| `covered` 已由完成的觀察列出 | Reference: a finished observation named the id. | Not a bot response and not incoming proof. |
| `unresolved` 未解決 | Reference: the followup cap left the id stored. | Not deleted and not covered. |
| `response-unverified` 尚未證實機器人已完成 | No supported response interface produced a result. | Not success. |

Outbox states map as `pending` to `queued`, `in_flight` to `inflight`, and `acked` plus `transport-accepted` to `transport-accepted`. There is no transition from `transport-accepted` to a bot response.

Reference rules, already tested and not installed:

- One worker. A second unique id during the lock stays pending.
- `observedAt` earlier than a sample clock does not cover an id.
- A failed or timed-out observation returns in-flight ids to pending.
- After two followup rounds, leftover ids stay unresolved.
- Event ids and handled message keys stay in different sets.
- The reference never sends.

## Scope rubric

Start with one selected one-to-one chat. Groups stay excluded. Other transports stay out until a later change tests them. These are yes-or-no checks. This page sets no quality score and no latency target.

- The reply stays on the selected chat.
- The package does not invent a completed send.
- Context from another chat is not imported.
- English is the default. Traditional Chinese status labels stay distinct and encoded as UTF-8.
- Logs and this check omit secrets and message text.
- Ambiguous direction abstains. A wake hint is not incoming proof.

Fictional ids used by the tests are `event-a`, `event-b`, and `chat-a`.

## Version pairing

One git checkout is the pair. There is no separate release tag claimed here.

- Host: Python 3.10 or newer. `setup-check` prints `python: too-old` below that. The README states the same floor because the modules evaluate union types at import.
- Extension: Node.js 20 or newer, then `npm ci` and `npm run build` in `web/`. The manifest version must match the version sentence in `README.md`. `extension-build: blocked` means Node is missing or older than 20. That does not by itself fail the host check.
- Browser: Chromium that can load an unpacked Manifest V3 extension. Firefox, Safari, the WhatsApp desktop app, and mobile apps are untested.
- Webhook: yours, HTTPS, or HTTP only on `127.0.0.1` or `localhost` with a port. The value stays outside git.

`result: public-package-ok` requires the manifest and README to agree, sending to stay off, the reference to stay unimported, and the contract checks above to hold. `webhook: missing` is expected on a clean tree and still passes.

## Your bot, and the missing response

You connect your own routine. This package does not ship one and does not collect a new credential in a form. Copy `config/wake.env.example` outside the checkout, set `WHATSAPP_WAKE_CONFIG` to that file, and fill the URL and credential there. `python3 -m wake status` reports whether a value is present.

Disconnect without printing those values: `python3 -m wake stop`, unset `WHATSAPP_WAKE_CONFIG`, and unload the unpacked extension. Local test files under `whatsapp-wake-test/` are gitignored. Delete that directory yourself if you want the local test store gone. Deleting it does not unlink WhatsApp.

The host reads an HTTP status from the webhook and, on the official transport, nothing else. It has no request path, field, or callback that carries an event id, a message id, a chat id, and a bot outcome back into this package. `response_blocker` therefore stays on `no-response-interface`, `transport-is-not-a-response`, `not-a-bot-response`, `local-test-fixture`, or `coverage-is-not-a-bot-response`. None of those means the bot finished.

Until such an interface exists and is tested, a correlated own-bot response remains unverified. Do not treat `public-package-ok` or an HTTP 2xx as that result.
