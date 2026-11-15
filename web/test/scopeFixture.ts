import type { ContactScope } from "../src/contactScope.js";

export function allowFixture(extra: Partial<ContactScope> = {}): ContactScope {
  return {
    mode: "allowlist",
    allow: ["contact-a"],
    deny: [],
    groups: "exclude",
    maxReplies: 8,
    ...extra
  };
}
