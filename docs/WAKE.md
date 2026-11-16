# Wake host

The native host name is `com.draft_bridge.wake`. The extension sends a sanitized chat-list signal. The host does not read message text into the webhook.

## Wires

Leave `WHATSAPP_WAKE_WIRE` unset until you choose one. Any other value stays on v1.

`whatsapp-wake-test-v1` posts when the numbered unread badge on the single configured allowlist label rises after a baseline. `conversationScope` is that label. The count stays in the local list file. The envelope has no message body. This wire names one label. It is not the all-contact path.

`whatsapp-wake-test-v2` is optional. Its exact keys are `field`, `eventId`, `source`, `observedAt`, `testOnly`, and `chatRef`. `chatRef` is `ref-` plus 16 lowercase hex digits. It has no name, count, phone, or `conversationScope`. The default host holds these hints. A local session for a ref expires 600 seconds after the last valid hint. `permit-open` queues an open only for a v2 item whose stored reason is the local test receipt `acked`. Transport-only and legacy 409 receipts do not queue one.

`whatsapp-wake-test-v3` is the targetless list wake. Its exact keys are `field`, `eventId`, `source`, `observedAt`, and `testOnly`. `source` is `list-change`. It has no chat, name, count, phone, or scope. Set `WHATSAPP_WAKE_WIRE=list` to post it. The same wire also posts one event when a new tail appears in an open direct-contact pane, because the unread badge does not move while that chat is open. The composer going empty does not identify an own reply, so that sample still posts one hint when the tail grew. A rebuilt tail, a context change, and a group drawer do not post. One posted v3 item keeps the worker. A later generation is stored once and is not posted. Transport acceptance does not end the worker and does not cover the id. A repeated generation does not mint another id. The hint is not incoming proof.

A 2xx is `transport-accepted`. The body is not read. It is not a chat receipt, not a model reply, and not exactly-once. Pending, queued, and in-flight work is not coverage. `python3 -m wake setup-check` prints these limits and does not call the webhook. See `docs/FOUNDATION.md`. The official path does not store a mock draft for that acknowledgement. HTTP 409 is the legacy stop, labeled `legacy-409`. `WHATSAPP_WAKE_TRANSPORT=test-receipt` is only for the local `wake/routine.py` test server, which keeps the labelled `local-mock-handler` fixture. Leave the transport unset for a real webhook.

## Contact surface

`群組資料` (Traditional Chinese for group details), or `group-info-header` / `group-info-drawer-body` inside `chat-info-drawer`, is a group. The result is `GROUP_CLOSE`: the official close control is used and messages are not collected. `聯絡人資料` (Traditional Chinese for contact details) without those markers is `DIRECT_CONTEXT`. Identity stays `ambiguous`. A mutual-groups section inside contact info does not make the chat a group. The exact English headings `Contact info` and `Group info` are also accepted. They are public-source strings, fixture-tested here, and not a live observation by this project. A group composer `Type a message to group ` blocks a direct classification. `Profile details` can open the drawer and does not by itself make the chat a direct contact. This classification is not a send and not an exact recipient.

## Configuration

`config/wake.env.example` has transmission off and empty URL and Authorization fields. Copy it outside the repository and point `WHATSAPP_WAKE_CONFIG` at the copy. `python3 -m wake status` does not print the values.

Contact scope for replies is `config/scope.example.json`. The default mode is `off`. Copy it to an untracked `config/scope.json` only on the machine that should use it. Groups stay excluded unless `groups` is `include`. This version still closes a group drawer and does not collect it. Setting `groups` to `include` changes the scope predicate only. It does not start group reads or group sends.
