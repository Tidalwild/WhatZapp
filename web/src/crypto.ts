export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return hex(new Uint8Array(digest));
}

export async function hmacHex(secretHex: string, material: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    bytesFromHex(secretHex),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signed = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(material));
  return hex(new Uint8Array(signed));
}

export function randomSecretHex(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return hex(bytes);
}

export function hex(bytes: Uint8Array): string {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function bytesFromHex(value: string): Uint8Array {
  if (!/^[0-9a-f]+$/i.test(value) || value.length % 2 !== 0) {
    throw new Error("secret");
  }
  const out = new Uint8Array(value.length / 2);
  for (let i = 0; i < out.length; i += 1) {
    out[i] = Number.parseInt(value.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}
