export interface SubClaim { email: string; verified_at: number }

function b64urlEncode(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function b64urlToBytes(str: string): Uint8Array {
  const pad = str.length % 4 ? '='.repeat(4 - (str.length % 4)) : '';
  const bin = atob(str.replace(/-/g, '+').replace(/_/g, '/') + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
async function hmac(data: string, secret: string): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  return new Uint8Array(sig);
}
function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export async function signCookie(payload: SubClaim, secret: string): Promise<string> {
  const body = b64urlEncode(new TextEncoder().encode(JSON.stringify(payload)));
  const sig = b64urlEncode(await hmac(body, secret));
  return `${body}.${sig}`;
}

export async function verifyCookie(value: string, secret: string): Promise<SubClaim | null> {
  const parts = value.split('.');
  if (parts.length !== 2) return null;
  const [body, sig] = parts;
  try {
    const expected = await hmac(body, secret);
    if (!timingSafeEqual(b64urlToBytes(sig), expected)) return null;
    const claim = JSON.parse(new TextDecoder().decode(b64urlToBytes(body)));
    if (typeof claim?.email !== 'string' || typeof claim?.verified_at !== 'number') return null;
    return claim;
  } catch {
    return null;
  }
}
