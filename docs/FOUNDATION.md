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
| Filesystem host install | `scripts/install-wake-bridge.sh` and `python3 -m wake install-check` | `install-proven: files` is the copied host and its version pair. It does not load a browser. |
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

`result: public-package-ok` means those file checks agree. It also prints `install-evidence: tree-only` and `install-proven: no`. A clean tree with no credential is not a completed installation, not a linked browser, and not a response from your routine.

## Filesystem install

`scripts/install-wake-bridge.sh --extension-id ID` copies this host into the home given by `--home`, or `$HOME` when that flag is omitted. `ID` is the extension id Chromium shows after you load `web/dist` unpacked. This package does not ship an extension id, a bot account, or a routine template.

The copy keeps its own Python package. Repeating the command replaces that copy and the native-host manifests. It does not read or delete the credential file, the store, or any other file. `scripts/install-wake-bridge.sh --uninstall` removes the copied host and a native-host manifest only when that manifest still points at this host. The credential file, the store, and unknown files stay.

`python3 -m wake install-check --home DIR` reads the copy. `install-proven: files` means the stamped host version, the copied extension manifest version, and an import of that copy agree. It also prints `browser-loaded: no`, `template-installed: no`, and `whatsapp-session: not-run`. `python3 -m wake setup-check` stays the tree check and does not become true because a home directory passed this file check.

Loading the unpacked extension and signing in to WhatsApp are still done in your browser. This sandbox cannot do that step. A draft your own routine types there is later live evidence. This package still does not record it, and it still does not name a path or a callback for it.

## Three results that are not the same

- **Correlation only.** An outbox row with reason `transport-accepted` is local status that an HTTP post was accepted. `python3 -m wake doctor` prints `correlation: local-transport`. That is not a draft.
- **Bot response.** Your own routine receives the wake and can read the visible chat and draft in the composer. See `docs/GROK.md`. This package does not currently record that draft. `bot-response: unproven` and `response-recorder: not-in-this-package` mean the recorder is unfinished. They do not mean your routine is unable to draft.
- **Approved delivery.** Sending is a later gate. `approved-delivery: disabled` while `LIVE_SEND_ARMED` is false. A draft is not a send, and an HTTP 2xx is not delivery.

No new credential form and no stand-in response endpoint are added here. A routine that already drafts outside this repository is not a recorder in this package. Where a later integration could observe that draft is unresolved. This tree does not name a file or callback for it.

## Doctor, recovery, and rollback

`python3 -m wake doctor` reads host and store files. It prints `browser-integration: not-wired` and `page-observed: no`. It does not accept a fresh flag, a hello of `READY`, or a stored sample time as a live page, so it does not report `browser: ready`. A sample time is `stale` when the host process is not live, `invalid` when it is in the future, and `not-a-page-proof` even when the host process is live. The command does not call the webhook or print the URL, the credential, the allowlist label, a chat header, or the sample time.

`python3 -m wake recover` uses that same store. Below the attempt cap, an in-flight row becomes retryable only after the existing backoff, and it is not covered. At the cap it is rejected and is not posted again. An acknowledged row is left in place, including its dedup indexes. The command does not rewrite the store while that host process is live. `--logged-out` and `--identity mismatch` only remove the binding; they are an operator request, not an observed page. `scope.json` is unchanged.

`connection_status(..., live_page=True)` is a unit model of a page this package does not observe. Doctor and recover do not call it that way.

`python3 -m wake rollback` prints the version pair and the runtime filenames still present. It does not delete them. `python3 -m wake rollback --drop-local-state` deletes only those known runtime names in the store. It skips symbolic links, leaves `scope.json` and any other file, and does not unlink WhatsApp. Reload the unpacked extension from this same checkout when the loaded extension version differs. That is a local pair check, not a published release.
