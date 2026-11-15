// Reply permission is a stored grant. It is not delivery.
// The 0.2.14 reader reports direction "unknown". A sender label and an
// occurrence id do not prove incoming or outgoing. A display name is not a
// unique recipient. This module never types into a composer and never calls
// WhatsApp. A hold is a contract result with transport "none".

import { contactInScope, type ContactKind, type ContactScope } from "./contactScope.js";

export const REPLY_TRANSPORT = "none" as const;

export type StandingGrant = {
  enabled: boolean;
  token: string;
  localScopeId: string;
  grantedAtMillis: number;
  expiresAtMillis: number;
};

export type ReplySource = "reader-0.2.14" | "synthetic-label" | "unread-hint" | "fixture-proven";

export type ReplyRequest = {
  grant: { enabled: boolean; token: string; localScopeId: string; expiresAtMillis?: number } | null;
  bind: {
    token: string;
    localScopeId: string;
    headerAgrees: boolean;
    composerAgrees: boolean;
    paneCount: number;
    verifiedRemoteRecipient: boolean;
    mode: string;
  };
  inbound: {
    source: ReplySource;
    stableId: string;
    direction: string;
    directionProof: string;
    senderIsSelf: boolean;
    echoesHeldReply: boolean;
  };
  untrustedText: string;
  action: string;
  replyText: string;
  ledger: { consumed: string[] };
  allowFixtureProof: boolean;
  scope: ContactScope;
  kind: ContactKind;
};

export type ReplyDecision = {
  ok: boolean;
  delivered: false;
  reason: string;
  blocked: string[];
  transport: "none";
  idempotencyKey: string;
};

export function emptyGrant(): StandingGrant {
  return { enabled: false, token: "", localScopeId: "", grantedAtMillis: 0, expiresAtMillis: 0 };
}

export function emptyLedger(): { consumed: string[] } {
  return { consumed: [] };
}

export function rememberHold(ledger: { consumed: string[] }, key: string): void {
  if (key === "" || ledger.consumed.includes(key)) return;
  ledger.consumed.push(key);
  if (ledger.consumed.length > 200) ledger.consumed.splice(0, ledger.consumed.length - 200);
}

export function decideReply(request: ReplyRequest): ReplyDecision {
  // Inbound text is untrusted data. It is not read and cannot authorize.
  const ignored = request.untrustedText;
  void ignored;

  const blocked: string[] = [];
  const block = (reason: string) => {
    if (!blocked.includes(reason)) blocked.push(reason);
  };
  const grant = request.grant;
  const bind = request.bind;
  const inbound = request.inbound;
  if (!grant?.enabled) block("GRANT_OFF");
  else if (grant.localScopeId === "" || bind.localScopeId === "" || grant.localScopeId !== bind.localScopeId) {
    block("BINDING_MISMATCH");
  }
  if (grant?.enabled && (grant.token === "" || grant.token !== bind.token)) block("WRONG_CHAT");
  if (grant?.enabled && !contactInScope(request.scope, { label: bind.token, kind: request.kind })) {
    block(request.scope.mode === "off" ? "SCOPE_OFF" : "SCOPE_EXCLUDED");
  }
  if (grant?.enabled && request.scope.maxReplies <= request.ledger.consumed.length) block("CAP_REACHED");
  if (grant?.enabled && (grant.expiresAtMillis ?? 0) <= 0) block("GRANT_EXPIRED");
  if (!bind.headerAgrees || !bind.composerAgrees) block("HEADER_AMBIGUOUS");
  if (bind.paneCount !== 1) block("PANE_AMBIGUOUS");
  if (bind.mode === "metadata") block("DIRECTION_UNPROVEN");
  if (!bind.verifiedRemoteRecipient) block("IDENTITY_UNPROVEN");

  const fixtureDirection =
    request.allowFixtureProof &&
    inbound.source === "fixture-proven" &&
    inbound.direction === "in" &&
    inbound.directionProof === "incoming-stable" &&
    !inbound.senderIsSelf;

  if (inbound.source === "unread-hint") block("UNREAD_HINT_NOT_AUTHORITY");
  else if (inbound.directionProof === "outgoing-status") {
    block("OUTGOING_EXCLUDED");
    block("DIRECTION_UNPROVEN");
  } else if (inbound.directionProof === "quote-structure") {
    block("QUOTE_NOT_DIRECTION");
    block("DIRECTION_UNPROVEN");
    if (inbound.source === "reader-0.2.14" || inbound.source === "synthetic-label") block("STABLE_ID_NOT_DIRECTION");
  } else if (inbound.senderIsSelf || inbound.direction === "out" || inbound.directionProof === "outgoing-self") {
    block("SELF");
  } else if (inbound.directionProof === "ambiguous") block("AMBIGUOUS");
  else if (!fixtureDirection) {
    block("DIRECTION_UNPROVEN");
    if (inbound.source === "reader-0.2.14" || inbound.source === "synthetic-label") block("STABLE_ID_NOT_DIRECTION");
  }

  const stableOk = /^[A-Za-z0-9._:-]{1,180}$/.test(inbound.stableId);
  if (inbound.source !== "unread-hint" && !stableOk && inbound.source !== "reader-0.2.14") block("STABLE_ID_MISSING");
  if (request.action !== "reply") block("ACTION_FORBIDDEN");
  const replyText = request.replyText.trim();
  if (request.action === "reply" && replyText === "") block("EMPTY_REPLY");
  if (request.replyText.length > 1000) block("REPLY_TOO_LONG");
  if (inbound.echoesHeldReply) block("REPLY_LOOP");

  const idempotencyKey = stableOk ? `${bind.localScopeId}/${inbound.stableId}` : "";
  if (idempotencyKey !== "" && request.ledger.consumed.includes(idempotencyKey)) block("DUPLICATE");

  if (blocked.length > 0) {
    return { ok: false, delivered: false, reason: blocked[0], blocked, transport: REPLY_TRANSPORT, idempotencyKey: "" };
  }
  return {
    ok: true,
    delivered: false,
    reason: "HELD_NOT_DELIVERED",
    blocked: [],
    transport: REPLY_TRANSPORT,
    idempotencyKey
  };
}
