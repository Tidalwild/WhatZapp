# Bound chat read

Version 0.2.14 reads the open bound chat on request. The numbered badge watcher is unchanged. Sending stays compiled off. The read does not post `whatsapp-wake-test-v1` and does not turn export on.

A manual count of a live chat is not a test of this reader. Fixture results are not a live proof.

## What it does

The open chat is accepted only when the header and the composer agree on the bound token. Traditional Chinese, from one live build: a button named `聯絡資料 ` plus the token, and a composer named `輸入要傳送去「` plus the token plus ` 」嘅訊息`. English, from public browser-automation sources and fixture-tested here, not from a live session in this project: a composer named `Type a message to ` plus the token, and a `span[dir="auto"]` inside `header` whose name is that token. A group composer `Type a message to group `, a nameless `Type a message`, a mixed-locale page, or any other wording fails closed.

The conversation panel is the one visible `conversation-panel-wrapper` that contains those two controls. A panel that merely sits between them is still accepted when it is the only one, which is the synthetic fixture shape. A panel inside `role="grid"` is the chat list and is not read. Two wrappers that both contain the same header and composer are refused. Rows come from `conversation-panel-messages` inside that panel. Each row is one `msg-container`. Its identity is the `data-id` on the nearest `conv-msg-*` ancestor that is still inside the panel. The reader does not climb past the panel, and it does not use a timestamp to decide identity. The id is not shown.

The same id is one occurrence across scroll windows, including when a later window drops ids in the middle. Those omitted ids stay in the result, and the coverage line says the render gap is yes. Two containers with the same time and the same text stay two occurrences when their wrapper ids differ. A window that puts two already seen ids in the opposite order keeps both once and marks order unproven. That order is document order of the ids. It is not a claim that the timestamps are chronological.

A container with no wrapper id inside the panel is counted as unkeyed. It is not added to the occurrence total. Date chips such as `星期一` (Monday) and `昨天` (yesterday), status marks, and media nodes are not extra rows. `星期一` matches the clock-or-weekday filter. `昨天` is dropped because it is not a message container, not because an English word "Yesterday" was observed. Selectable text is kept. A document thumb adds the placeholder `[document]`. Direction stays `unknown`. A selectable-text leaf whose text is exactly the bound token is a sender label, not incoming or outgoing. A stored reply grant does not change this read, and a row from this read is not permission to reply.

If the panel renders `點擊此處從手機取得較舊的訊息。` (Traditional Chinese for the control that loads older messages from the phone), the coverage line says phone history is yes. That control is not clicked. It means older messages are still on the phone. `historyComplete` stays false. An English wording of that control is not matched.

The read scrolls `conversation-panel-messages`, or the one overflow box inside it, upward up to 30 steps, and waits for a short quiet period before each sample. It does not search the header or the composer for a scroller, and it does not climb to an ancestor outside the messages area. If the header changes, scrolling stops and the sample from the other chat is discarded. Reaching the top of that box is not a claim that every older message was loaded.

## Install

This zip is 0.2.14. Replace the files in the same unpacked directory that already has the extension. That keeps the extension id. Then reload the extension and reload the WhatsApp tab once.

No new permission is requested. Leave the 0.2.10 native host, its wrapper, `wake.env`, the stored badge binding, and the dedup file in place. This read does not post to the host, so those pieces do not need to be reinstalled. Do not put a webhook URL or an authorization value in the repository.

## Live check

1. Open the chat yourself. This button does not click the chat list.
2. Read open chat. The label should be the bound header. Leave the self field blank. Metadata scope should already name that header.
3. Leave export off. Collection for the badge can stay as it already is. The read does not send message text to the host.
4. Choose Read bound chat. Scrolling the transcript can mark the chat read. It does not send a WhatsApp message.
5. Read the coverage line. Keyed is the distinct wrapper-id count. Occurrences is that same count. Unkeyed is separate and is not added in. A render gap means a window omitted ids that this read had already seen between two ids it still showed. Order proven means those ids stayed in document order. It does not mean the timestamps were sorted. Complete history stays false. Direction on each row stays unknown.
6. `HEADER_UNPROVEN` means the header button and the composer did not both match. The header line stays `(none)`. `PANE_UNPROVEN` means those two names matched and the panel or the messages area did not. The header line then stays the bound header, and no rows are kept.
7. A fixture pass is not a live WhatsApp read. This build scrolls the messages area. It still does not know whether an ancestor outside that area is the element WhatsApp actually scrolls.
