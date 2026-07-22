import { describe, it, expect } from 'vitest';
import { signCookie, verifyCookie } from '../functions/_lib/cookie';

const SECRET = 'test-secret';
const PAYLOAD = { email: 'a@b.com', verified_at: 1_700_000_000 };

describe('cookie', () => {
  it('round-trips a signed payload', async () => {
    const token = await signCookie(PAYLOAD, SECRET);
    expect(await verifyCookie(token, SECRET)).toEqual(PAYLOAD);
  });

  it('rejects a tampered payload', async () => {
    const token = await signCookie(PAYLOAD, SECRET);
    const tampered = token.slice(0, -2) + (token.endsWith('a') ? 'b' : 'a');
    expect(await verifyCookie(tampered, SECRET)).toBeNull();
  });

  it('rejects a wrong secret', async () => {
    const token = await signCookie(PAYLOAD, SECRET);
    expect(await verifyCookie(token, 'other-secret')).toBeNull();
  });

  it('rejects garbage', async () => {
    expect(await verifyCookie('not-a-token', SECRET)).toBeNull();
  });
});
