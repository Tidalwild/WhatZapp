# Draft-only candidate

This page is the disposition of the 24-task plan for this checkout. It is not an owner go decision and it is not a published release. `candidate: draft-only` means the live send arm is off and a live WhatsApp session was not run.

Machine checks that this tree can run are named below. A green check is not a linked browser and not a routine draft.

| Task | Disposition | What was exercised |
| --- | --- | --- |
| WZ-01 | Implemented, tree-tested | `docs/FOUNDATION.md` and `python3 -m wake setup-check`. A live pilot comparison is not in this run. |
| WZ-02 | Implemented, tree-tested | User-owned webhook boundary. No maintainer bot. No paid Meta API. |
| WZ-03 | Implemented, tree-tested | `wake-evidence-1`. HTTP 2xx is transport only. Queued and in-flight are not covered. |
| WZ-04 | Implemented, tree-tested | One-to-one scope. No quality score and no latency target. |
| WZ-05 | Implemented, sandbox-tested | `scripts/install-wake-bridge.sh` and `python3 -m wake install-check` against a temporary home. Browser load of the unpacked extension is still a human step. |
| WZ-06 | Partial | The user gives this repository to their own bot. No new credential form. A correlated live routine response is unproven. |
| WZ-07 | Implemented, tree-tested | `python3 -m wake doctor` and `rollback`. Secrets are not printed. |
| WZ-08 | Implemented, tree-tested | `python3 -m wake recover`. Doctor does not report ready from disk. A live page was not observed. |
| WZ-09 | Implemented, tree-tested | Direction is not inferred from layout, ticks, clocks, unread marks, or quotes. |
| WZ-10 | Implemented, tree-tested | `wake/ledger.py` separates event ids from message keys. |
| WZ-11 | Implemented, tree-tested | A late unique id is not covered by an older sample or by HTTP 2xx. One worker. Follow-up cap leaves ids unresolved. |
| WZ-12 | Partial, tree-tested | The routine can read and draft in the page composer without a callback. This package does not record that draft. Occupied text is not authorship. `response-absence: not-inability`. |
| WZ-13 | Implemented, tree-tested | Context is off until an operator enables one chat. Other chats are dropped. Budget is 2000 characters. Revocation and expiry abstain. |
| WZ-14 | Implemented, tree-tested | `web/src/deltaRead.ts` keeps keys only, caps the cache, and drops it on a chat switch, stale order, or unproven identity. |
| WZ-15 | Implemented, tree-tested | Stage lines record receipt, queue, read, handoff, and composer. The result stage stays missing. Approval wait is separate. No target was invented. |
| WZ-16 | Implemented, tree-tested | Approval binds a digest, scope, and event. Ambiguous results are not retried. `LIVE_SEND_ARMED` stays false. This is not a send-enabled claim. |
| WZ-17 | Implemented, tree-tested | Existing wake and web suites plus `tests/wake/test_candidate.py` and `web/test/candidate.test.ts`. Not a live failure injection. |
| WZ-18 | Implemented, tree-tested | English is the default. Traditional Chinese labels are in `web/src/copy.ts` and `wake/evidence.py`. The popup language control defaults to English. |
| WZ-19 | Implemented, tree-tested | Chat and context text cannot change scope, approve a send, or add a wake field. Cross-chat facts are dropped. |
| WZ-20 | Implemented, tree-tested | `python3 scripts/privacy_scan.py` on the tracked tree and again on the candidate archive. |
| WZ-21 | Blocked for the live path | Clean-home install, upgrade, and uninstall can run in a temporary home. Linking WhatsApp and an own-bot draft were not run. |
| WZ-22 | Blocked | No live recording. A fixture run is not presented as that demo. |
| WZ-23 | Implemented | This page, `README.md`, `docs/FOUNDATION.md`, and `docs/GROK.md`. |
| WZ-24 | Draft-only candidate | `python3 scripts/package_candidate.py DEST` writes a tar and `SHA256SUMS`. Publication, owner go, and a send-enabled claim are not done. |

## Still unproven

- A person loading `web/dist` and signing in to WhatsApp Web.
- A wake delivered to a routine the person runs, and a draft that routine types.
- An approved send and an observed result. Sending stays off, so this candidate must not be called send-enabled.
