# Direction limits

The reader publishes `unknown` for live rows. A sender label, an occurrence id, alignment, `tail-in`, `tail-out`, and a missing status are not incoming or outgoing proof.

A rendered row is excluded as outgoing when it has `aria-label="已讀"` (Traditional Chinese for read) and an image role whose accessible name contains `read`. That pair was observed on one outgoing row in one Traditional Chinese build. An English `Read`, `Sent`, or `Pending` label is not accepted by that rule. A button named `Quoted message` is the public-source English form of the quote control and is still quote structure, not incoming. It is not a general direction rule and it may not survive a locale or version change.

A later row is `quote-structure` when it quotes the own text of an earlier excluded row: a `quoted-message` subtree with that exact text, a button named with that text, and either a button `aria-label` of four letters that contains `引用` (Traditional Chinese for quote) or the exact public-source label `Quoted message`. That records a quote. It does not say who sent the later row. An outgoing reply can quote the same text before a read receipt. Pending, sent, unread, and missing status do not make it incoming.

Rows that do not quote a known outgoing message stay unproven. The exclusion count is the rows still mounted when it runs. It is not a status on the keyed history. `LIVE_EVIDENCE_IDS` is empty. `LIVE_SEND_ARMED` stays false.

Enrollment accepts a SHA-256 hex digest of an E.164 number plus proof that the ordinary new-chat or send-by-phone control opened the bound header. Do not send the number into the extension. A matching profile digest is `self-chat` and does not verify a remote recipient. A display name and `localScopeId` are not identity.
