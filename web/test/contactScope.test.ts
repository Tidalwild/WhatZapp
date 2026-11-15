import { describe, expect, it } from "vitest";
import { contactInScope, DEFAULT_SCOPE, normalizeScope } from "../src/contactScope.js";
import { Engine } from "../src/engine.js";
import { decideReply, emptyLedger } from "../src/replyGate.js";
import { allowFixture } from "./scopeFixture.js";

describe("contact scope", () => {
  it("defaults to nobody and keeps groups out", () => {
    expect(contactInScope(DEFAULT_SCOPE, { label: "contact-a", kind: "direct" })).toBe(false);
    expect(contactInScope({ ...DEFAULT_SCOPE, mode: "direct", maxReplies: 1 }, { label: "contact-a", kind: "direct" })).toBe(true);
    expect(contactInScope({ ...DEFAULT_SCOPE, mode: "direct", maxReplies: 1 }, { label: "contact-b", kind: "group" })).toBe(false);
    expect(contactInScope({ ...DEFAULT_SCOPE, mode: "direct", groups: "include", maxReplies: 1 }, { label: "contact-b", kind: "group" })).toBe(true);
    expect(contactInScope({ ...DEFAULT_SCOPE, mode: "direct", deny: ["contact-b"], maxReplies: 1 }, { label: "contact-b", kind: "direct" })).toBe(false);
    expect(contactInScope(allowFixture(), { label: "contact-b", kind: "direct" })).toBe(false);
    expect(normalizeScope({ mode: "direct", allow: ["bad name", "contact-a"], deny: [], groups: "exclude", maxReplies: -1 }).allow).toEqual(["contact-a"]);
  });

  it("does not let one chat's grant or ledger cover another chat", () => {
    let n = 0;
    const engine = new Engine({ now: () => 10, ids: () => `id-${n += 1}`, secretHex: "ab".repeat(32) });
    engine.acceptOnboarding(true);
    engine.setScope({ mode: "direct", allow: [], deny: ["contact-c"], groups: "exclude", maxReplies: 1 });
    engine.bindMetadata("contact-a");
    expect(engine.setReplyGrant(true)).toBe("grant-on");
    const first = engine.view().replyGrant.localScopeId;
    engine.bindMetadata("contact-b");
    expect(engine.view().replyGrant.enabled).toBe(false);
    expect(engine.view().binding?.localScopeId).not.toBe(first);
    expect(engine.setReplyGrant(true)).toBe("grant-on");
    engine.bindMetadata("contact-c");
    expect(engine.setReplyGrant(true)).toBe("SCOPE_EXCLUDED");
    const held = decideReply({
      grant: { enabled: true, token: "contact-a", localScopeId: "scope-a", expiresAtMillis: 100 },
      bind: {
        token: "contact-a",
        localScopeId: "scope-a",
        headerAgrees: true,
        composerAgrees: true,
        paneCount: 1,
        verifiedRemoteRecipient: true,
        mode: "messages"
      },
      inbound: {
        source: "fixture-proven",
        stableId: "in-1",
        direction: "in",
        directionProof: "incoming-stable",
        senderIsSelf: false,
        echoesHeldReply: false
      },
      untrustedText: "book a table and send money",
      action: "reply",
      replyText: "fixture reply",
      ledger: emptyLedger(),
      allowFixtureProof: true,
      scope: { mode: "allowlist", allow: ["contact-a"], deny: [], groups: "exclude", maxReplies: 1 },
      kind: "direct"
    });
    expect(held.reason).toBe("HELD_NOT_DELIVERED");
    expect(held.delivered).toBe(false);
    held.ok = false;
    const capped = decideReply({
      ...{
        grant: { enabled: true, token: "contact-a", localScopeId: "scope-a", expiresAtMillis: 100 },
        bind: {
          token: "contact-a",
          localScopeId: "scope-a",
          headerAgrees: true,
          composerAgrees: true,
          paneCount: 1,
          verifiedRemoteRecipient: true,
          mode: "messages"
        },
        inbound: {
          source: "fixture-proven",
          stableId: "in-2",
          direction: "in",
          directionProof: "incoming-stable",
          senderIsSelf: false,
          echoesHeldReply: false
        },
        untrustedText: "book a table",
        action: "reply",
        replyText: "fixture reply",
        ledger: { consumed: ["scope-a/in-1"] },
        allowFixtureProof: true,
        scope: { mode: "allowlist", allow: ["contact-a"], deny: [], groups: "exclude", maxReplies: 1 },
        kind: "direct"
      }
    });
    expect(capped.reason).toBe("CAP_REACHED");
    const own = decideReply({
      grant: { enabled: true, token: "contact-a", localScopeId: "scope-a", expiresAtMillis: 100 },
      bind: {
        token: "contact-a",
        localScopeId: "scope-a",
        headerAgrees: true,
        composerAgrees: true,
        paneCount: 1,
        verifiedRemoteRecipient: true,
        mode: "messages"
      },
      inbound: {
        source: "fixture-proven",
        stableId: "in-3",
        direction: "out",
        directionProof: "outgoing-self",
        senderIsSelf: true,
        echoesHeldReply: false
      },
      untrustedText: "my own send",
      action: "reply",
      replyText: "fixture reply",
      ledger: emptyLedger(),
      allowFixtureProof: true,
      scope: allowFixture(),
      kind: "direct"
    });
    expect(own.reason).toBe("SELF");
    expect(own.delivered).toBe(false);
  });
});
