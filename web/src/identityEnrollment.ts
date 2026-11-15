// Identity enrollment for one bound direct chat.
// The local runtime compares a normalized E.164 number and supplies only its
// SHA-256 hex digest. This module never accepts a raw number, a display name,
// a localScopeId, or unlabeled drawer text. A matching profile digest is the
// same account, not a remote recipient. Incoming direction is a separate proof.

import { contactInScope, type ContactScope, DEFAULT_SCOPE } from "./contactScope.js";

export type IdentityStatus = "unenrolled" | "self-chat" | "enrolled";

export type IdentityEnrollment = {
  status: IdentityStatus;
  contactDigest: string;
  profileDigest: string;
  localScopeId: string;
  headerToken: string;
  openedByNumber: boolean;
  enrolledAtMillis: number;
};

export type IdentityClaim = {
  contactDigest: string;
  profileDigest: string;
  openedHeader: string;
  openedByNumber: boolean;
};

const DIGEST = /^[a-f0-9]{64}$/;

export function emptyIdentity(): IdentityEnrollment {
  return {
    status: "unenrolled",
    contactDigest: "",
    profileDigest: "",
    localScopeId: "",
    headerToken: "",
    openedByNumber: false,
    enrolledAtMillis: 0
  };
}

export function decideIdentity(
  claim: IdentityClaim,
  binding: { visibleHeader: string; localScopeId: string } | null,
  now: number,
  scope: ContactScope = DEFAULT_SCOPE
): { enrollment: IdentityEnrollment; reason: string } {
  if (!binding || binding.localScopeId === "") return { enrollment: emptyIdentity(), reason: "NOT_BOUND" };
  const header = binding.visibleHeader.trim();
  if (header === "" || claim.openedHeader.trim() !== header) {
    return { enrollment: emptyIdentity(), reason: "WRONG_CHAT" };
  }
  const contactDigest = claim.contactDigest.trim();
  const profileDigest = claim.profileDigest.trim();
  if (!DIGEST.test(contactDigest)) return { enrollment: emptyIdentity(), reason: "DIGEST_UNUSABLE" };
  if (profileDigest !== "" && !DIGEST.test(profileDigest)) return { enrollment: emptyIdentity(), reason: "PROFILE_UNUSABLE" };
  if (claim.openedByNumber !== true) return { enrollment: emptyIdentity(), reason: "SESSION_UNPROVEN" };
  if (!contactInScope(scope, { label: header, kind: "direct" })) {
    return { enrollment: emptyIdentity(), reason: scope.mode === "off" ? "SCOPE_OFF" : "SCOPE_EXCLUDED" };
  }
  const sameAccount = profileDigest !== "" && profileDigest === contactDigest;
  const enrollment: IdentityEnrollment = {
    status: sameAccount ? "self-chat" : "enrolled",
    contactDigest,
    profileDigest,
    localScopeId: binding.localScopeId,
    headerToken: header,
    openedByNumber: true,
    enrolledAtMillis: now
  };
  return { enrollment, reason: sameAccount ? "SELF_CHAT" : "IDENTITY_ENROLLED" };
}

export function remoteIdentityReady(
  enrollment: IdentityEnrollment | null | undefined,
  binding: { visibleHeader: string; localScopeId: string } | null,
  scope: ContactScope = DEFAULT_SCOPE
): boolean {
  if (!enrollment || !binding) return false;
  const header = binding.visibleHeader.trim();
  return (
    enrollment.status === "enrolled" &&
    enrollment.openedByNumber === true &&
    enrollment.headerToken === header &&
    header !== "" &&
    contactInScope(scope, { label: header, kind: "direct" }) &&
    enrollment.localScopeId !== "" &&
    enrollment.localScopeId === binding.localScopeId &&
    DIGEST.test(enrollment.contactDigest) &&
    enrollment.profileDigest !== enrollment.contactDigest
  );
}

export function normalizeIdentity(enrollment: IdentityEnrollment | null | undefined, binding: { visibleHeader: string; localScopeId: string } | null): IdentityEnrollment {
  const header = binding?.visibleHeader.trim() ?? "";
  if (!enrollment || !binding || header === "" || binding.localScopeId === "") return emptyIdentity();
  if (enrollment.localScopeId !== binding.localScopeId || enrollment.headerToken !== header) return emptyIdentity();
  if (!DIGEST.test(enrollment.contactDigest) || enrollment.openedByNumber !== true) return emptyIdentity();
  if (enrollment.profileDigest !== "" && !DIGEST.test(enrollment.profileDigest)) return emptyIdentity();
  if (enrollment.profileDigest !== "" && enrollment.profileDigest === enrollment.contactDigest) {
    return { ...enrollment, status: "self-chat", headerToken: header };
  }
  if (enrollment.status !== "enrolled") return emptyIdentity();
  return { ...enrollment, status: "enrolled", headerToken: header };
}
