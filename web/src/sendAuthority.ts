// Approval binds a digest, a scope, and an event. It does not send.
// LIVE_SEND_ARMED stays false in replyDelivery.ts. A match returns
// SEND_DISARMED. An ambiguous phase blocks a replacement approval.

import { sha256Hex } from "./crypto.js";

export const APPROVAL_TTL_MS = 15 * 60 * 1000;

export type ApprovalPhase = "none" | "approved" | "ambiguous" | "failed";

export type Approval = {
  phase: ApprovalPhase;
  digest: string;
  scopeId: string;
  event: string;
  approvedAtMillis: number;
  expiresAtMillis: number;
  paused: boolean;
};

const DIGEST = /^[0-9a-f]{64}$/;
const SCOPE = /^[A-Za-z0-9._:-]{1,80}$/;
const EVENT = /^evt-[0-9a-f]{32}$/;

export function emptyApproval(): Approval {
  return { phase: "none", digest: "", scopeId: "", event: "", approvedAtMillis: 0, expiresAtMillis: 0, paused: false };
}

export function normalizeApproval(value: Partial<Approval> | null | undefined): Approval {
  if (value == null || value.phase === "none" || value.phase == null) return emptyApproval();
  if (value.phase !== "approved" && value.phase !== "ambiguous" && value.phase !== "failed") return emptyApproval();
  if (!DIGEST.test(value.digest ?? "") || !SCOPE.test(value.scopeId ?? "") || !EVENT.test(value.event ?? "")) {
    return emptyApproval();
  }
  if (typeof value.expiresAtMillis !== "number" || typeof value.approvedAtMillis !== "number") return emptyApproval();
  return {
    phase: value.phase,
    digest: value.digest ?? "",
    scopeId: value.scopeId ?? "",
    event: value.event ?? "",
    approvedAtMillis: value.approvedAtMillis,
    expiresAtMillis: value.expiresAtMillis,
    paused: value.paused === true
  };
}

export function decideAuthority(approval: Approval, now: number, digest: string, scopeId: string, event: string): string {
  if (approval.phase === "none") return "AWAITING";
  if (approval.phase === "ambiguous") return "AMBIGUOUS_HOLD";
  if (approval.phase !== "approved") return "AWAITING";
  if (approval.paused) return "PAUSED";
  if (now >= approval.expiresAtMillis) return "EXPIRED";
  if (digest !== approval.digest) return "DIGEST_MISMATCH";
  if (scopeId !== approval.scopeId) return "SCOPE_MISMATCH";
  if (event !== approval.event) return "EVENT_MISMATCH";
  return "SEND_DISARMED";
}

export async function digestText(text: string): Promise<string> {
  return sha256Hex(text);
}
