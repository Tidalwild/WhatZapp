# Web adapter

Status: **not WhatsApp-compatible**. Live `web.whatsapp.com` was not opened, logged in, or read in this run. The prior note that an accessibility snapshot once showed a sender, text, and time is background only. It is not a saved DOM fixture and it is not a selector contract.

## Why this shape

Android already fails closed unless a notification carries a shortcut id or exactly one counterparty person key. WhatsApp Web does not give this adapter either of those. A display name is not a stable remote id. The narrow substitute is a local pilot binding: the person looks at the chat that is already open and explicitly binds that visible header, together with the label they use for themselves. The binding id is random and local. `verifiedRemoteRecipient` stays false.

The shipped extension is Manifest V3. It asks for `storage`, `nativeMessaging`, and `https://web.whatsapp.com/*` only. It does not ask for tabs, history, cookies, debugger, webRequest, scripting, or all sites. The test build is a different manifest that matches only `http://127.0.0.1:8766/*`, so the browser tests cannot reach WhatsApp.

The content script reads the rendered accessibility tree of the single visible `main` region: one heading, an optional status, and direct rows of a list. It uses visible text. It does not read `datetime`, `data-*`, cookies, page storage, or the composer. It does not evaluate page JavaScript, touch `window.Store`, intercept the network, or scroll. Collection is off until the person turns it on for the bound chat. Export to the local mock is a second switch and is also off by default. Stop turns both off.

The `MutationObserver` in the content script is a page-change signal. It is not a FreeDesktop notification. Two visible rows that share a sender and a clock fail closed, including when the text differs, and they do not become a draft. `chrome.notifications` is not requested and could not hear another site's notifications even if it were. There is no private Chrome hook. A Linux session observer sees a desktop notification only when the browser actually emits one. The helper box did not see one from WhatsApp Web. A settled mutation can feed the native host described in `docs/INTEGRATION.md`. The fixture list reader understands `data-bridge-list`. The live list reader understands one reported shape: a visible `grid` outside `main`, a `row` with no accessible name, and a `generic` descendant whose accessible name is exactly the bound token. A longer `gridcell` name is not a label and is not kept. No unread node was reported, so that path leaves `unread` null. Native UI reads with older or locale clocks stay fail-closed.

Sending to WhatsApp has no implementation. There is no click handler and no Enter handler aimed at a composer. A draft stays in the extension popup. Confirming it returns `NOT_SENT_SENDING_DISABLED`.

A reply grant can be stored for the open binding and revoked. It is off by default, and the contact scope defaults to nobody. Stop clears the grant. Turning it on requires that binding's header to be inside the configured scope. The stored value is that binding's `localScopeId`. Rebinding clears it. The live assessment passes `verifiedRemoteRecipient` only when `enroll-identity` has accepted a digest for that same binding and the scope still includes it. A display-name binding does not. The reader direction is unknown, so the gate returns `DIRECTION_UNPROVEN` and `STABLE_ID_NOT_DIRECTION` and does not deliver. A synthetic sender label is not direction proof either. An unread hint is not send authority. Inbound text is ignored by the gate. Actions other than a conversational reply are rejected. `decideReply` can return `HELD_NOT_DELIVERED` with transport `none` only for a test that sets `allowFixtureProof` and supplies a fixture provenance the extension does not accept from the page. That result is not a WhatsApp send.

`commitDelivery` is the delivery adapter. A live call has no enrolled evidence id, no compared contact identity, no outgoing comparison, and an actuator that is not wired. It returns `EVIDENCE_NOT_MEASURED` before it writes an exactly-once row and before it asks the actuator to run. The extension reads composer emptiness from the reported textbox and checks an already-open contact drawer for the exact Traditional Chinese labels `手機`, `電話`, and `電話號碼` (phone). English phone labels are not accepted. A missing label, a label whose value is not compared, and a composer that was not observed stay blocked. A message row is excluded as outgoing when it contains `aria-label="已讀"` (Traditional Chinese for read) and an image role whose accessible name contains `read`. A later row that quotes that outgoing text, with `quoted-message`, a button named with the text, and a four-letter `引用` control (Traditional Chinese for quote), is `quote-structure`. A button named `Quoted message` is also quote structure. `Read`, `Sent`, and `Pending` are not. Quote structure is not incoming: an outgoing reply can quote the same text before a read receipt, and pending, sent, unread, or missing status does not prove otherwise. Rows that do not quote a known outgoing message stay unproven. `tail-in` and a missing status are not incoming proof. `LIVE_EVIDENCE_IDS` is empty, and `LIVE_SEND_ARMED` stays false, so `deliveryEnabled` stays false. A disabled grant is `GRANT_OFF` and is not also `BINDING_MISMATCH`. A fixture can persist one attempt and accept one matching receipt; `delivered` stays false and `live` stays false. A row left `persisted` or `uncertain` is not attempted again. The page message `deliver-reply` cannot supply direction or identity proof. `enroll-identity` accepts a local SHA-256 digest of an E.164 number and requires the ordinary number-resolution UI to have opened the bound header. The extension does not receive the number. A display name, `localScopeId`, and unlabeled drawer text are rejected. Equal contact and profile digests are stored as `self-chat` and do not verify a remote recipient or relax the read-status exclusion. `deliveryEnabled` stays false while incoming direction is unproven. The quote-structure limit is in `docs/DIRECTION.md`. Direction limits are in `docs/DIRECTION.md`.

## Probe contract

This is the contract the synthetic fixture implements. It is labeled in the page as a test layout, not as WhatsApp markup.

- Exactly one visible `main`, and exactly one visible `h1` inside it. Anything else is `unrecognized` and stores nothing.
- A visible status whose text says the view is loading produces `LOAD_EMPTY` or `RELOAD_EMPTY`. Rows behind that status are ignored.
- A row is a direct `listitem` with three visible element children. The third child's rendered text must be a clock (`09:00` or `9:00 AM`). The `datetime` attribute is ignored.
- A one-line chip such as "Today" is a separator. A row whose body repeats the header is a header echo. Neither is stored.
- A row that looks like a message but has no clock, or an empty body, rejects the whole snapshot.
- Direction is `in` only when the sender text equals the bound header, and `out` only when it equals the self label. Any other sender rejects the snapshot. Groups and forwarded names therefore store nothing.
- Two rows with the same sender, text, and clock in one snapshot are `AMBIGUOUS_REPEAT`. Neither is stored, and no id is invented.

The first settled snapshot after collection starts is a baseline. It is not new traffic. A later snapshot may add only a tail that overlaps the previous window. An empty read, a loading read, or a window that does not overlap records an incomplete gap and does not become history. `historyComplete` is always false. The adapter does not open other chats and does not scroll for older rows.

## What was reused from Android

The web engine is a TypeScript reimplementation of the tested intent, not a compile of the Kotlin module. The Android APK and the 40 JVM tests are unchanged by this work.

| Rule | Android | Web |
| --- | --- | --- |
| Identity | Shortcut id, or one person key/URI on a direct chat | Local binding of the visible header. Not a remote id |
| Display name | Label only | Continuity check against the bound label. Mismatch stops the read |
| First window | May store text after allowlist | Baseline only. Nothing from it is new |
| Overlap | Fresh suffix can be stored | Same, and only for the bound chat |
| No overlap | Stores the rows and records a gap | Records `NO_OVERLAP` and stores nothing |
| Identical same clock | Both kept inside one notification | Rejected as ambiguous |
| Same text, different time | Two messages | Two messages, once each is past the baseline |
| Empty snapshot | Does not invent a gap by itself | `LOAD_EMPTY` or `RELOAD_EMPTY` |
| Export | Loopback HTTP, secret in Keystore | In-extension mock. No socket. Secret stays in `chrome.storage.local` |
| Handler | `local-mock-handler` | Local placeholder. No model is called |
| Send | Constants false, invoker not called | No composer write. Confirm cannot send |
| Logs | Allowlisted keys, no message text | Same |
| History | Always incomplete | Always incomplete |

Inbound text is untrusted data. It cannot change onboarding, collection, export, or the binding. The mock draft body is a fixed placeholder that does not copy the message. Logs drop message text, labels, and the HMAC secret.

## How to run

```bash
cd web
npm install
npm test
npx playwright install chromium
npm run test:browser
npm run zip
```

`npm test` is the unit suite. `npm run test:browser` loads the test-manifest extension in Playwright's Chromium and drives the local fixture. Branded Google Chrome on this machine ignores `--load-extension`; the tests use Playwright Chromium for that reason. The zip is the production manifest.

The fixture page is not served as a product. Browser tests start it on `127.0.0.1:8766` and stop it afterward.

## Open-chat label

Read open chat returns a label only when both reported names are visible and agree. The header is a visible button whose accessible name is exactly `聯絡資料 ` plus the token, even when the button's rendered text is not that full string. The composer is a visible textbox whose accessible name, placeholder, or entire text is exactly `輸入要傳送去「` plus that same token plus ` 」嘅訊息`. Those two names are the Traditional Chinese accessible names from one observed build. English is accepted only as a composer named `Type a message to ` plus the token, confirmed by a `span[dir="auto"]` inside `header` with that same token. That English pair is a public-source pattern, fixture-tested here, and not a live observation by this project. A green fixture run is not an end-to-end proof. A name may come from the control, a descendant, or an `aria-labelledby` target. A longer lookalike is not a name. A visible word that merely repeats a label is not the header, whether or not it sits inside the chat grid. The self label is the exact sender text on your own messages, not the business profile name. If that sender text is absent, strict message binding stays closed. Bind metadata scope is the supported path: it stores the open-chat token only, leaves direction unproven, and does not keep message text. Metadata collection does not run the message-layout probe, so a page that lacks that synthetic layout is not an unrecognized-layout failure. The local host handshake does not post a wake while unread is unknown. A numbered badge posts `unread-indicator-hint` only after a stored baseline, and only when that count rises. An empty-text dot is `UNREAD_DOT` and does not post. The page bridge is open only after hello is acknowledged. The popup line `This sample posted` describes the latest sample. An earlier HTTP ack stays on `Last event` and is not a chat receipt.

## Still pending

A person can load the unpacked production extension themselves. The open-chat message probe still expects the synthetic `main` contract, so automatic collection stores no rows from a real conversation. Version 0.2.14 reads the bound chat on request from `msg-container` rows inside the `conversation-panel-wrapper` that contains the proven header and composer, keyed by the outer `conv-msg-*` `data-id`. Direction stays unknown. The occurrence count is the distinct id count. A missing wrapper id is unkeyed and is not added to that count. It does not use the synthetic `main` contract, does not post message text, and does not treat a pane top or the phone-history control as the full chat. The chat-list path can see the reported grid while the bound chat is not the open chat. A numbered badge on that row can post a hint after a baseline. Do not treat a green fixture run as a live WhatsApp read or wake. See `docs/READ.md`.

## Locale support

This section is the selector mapping. It is not the product language. English names below are public-source patterns, fixture-tested in this repository, and not a live English WhatsApp observation by this project. Traditional Chinese names are from one prior live build. Both remain accepted. A mixed page fails closed.

| Use | English, public source, fixture-tested, not live-verified here | Traditional Chinese, one prior live observation |
| --- | --- | --- |
| Direct composer | `Type a message to ` plus the token | `輸入要傳送去「` plus the token plus ` 」嘅訊息` |
| Header | `span[dir="auto"]` inside `header`, exact token | button `聯絡資料 ` plus the token |
| Direct drawer | `Contact info` | `聯絡人資料` |
| Group drawer | `Group info` | `群組資料` |
| Unread dot | `unread` | `未讀` |
| Unread count | not accepted | `1個未讀訊息` |
| Quote | `Quoted message` | `引用` |
| Read receipt | not accepted | `已讀` |
| Phone labels | not accepted | `手機`, `電話`, `電話號碼` |
| Older messages on the phone | not accepted | `點擊此處從手機取得較舊的訊息。` |
