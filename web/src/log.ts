const ALLOWED = new Set([
  "disposition",
  "reason",
  "count",
  "state",
  "duplicate",
  "incomplete",
  "handler",
  "kind",
  "outbox"
]);

export function safeLine(name: string, fields: Record<string, string> = {}): string {
  const parts = [`name=${clip(name)}`];
  for (const [key, value] of Object.entries(fields)) {
    if (!ALLOWED.has(key)) continue;
    parts.push(`${key}=${clip(value)}`);
  }
  return parts.join(" ");
}

function clip(value: string): string {
  const flat = value.replaceAll("\n", " ").replaceAll("\r", " ");
  return flat.length <= 120 ? flat : flat.slice(0, 120);
}

export class FilteringLog {
  readonly lines: string[] = [];

  event(name: string, fields: Record<string, string> = {}): void {
    this.lines.push(safeLine(name, fields));
  }
}
