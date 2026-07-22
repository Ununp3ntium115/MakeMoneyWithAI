import { describe, it, expect, vi } from 'vitest';
import { handle } from '../functions/api/playbook/[slug]';
import { signCookie } from '../functions/_lib/cookie';

const SECRET = 'sec';
const ENV = {
  COOKIE_SECRET: SECRET,
  STRIPE_SECRET_KEY: 'sk',
  PLAYBOOKS: { get: vi.fn(async () => JSON.stringify({ slug: 'a__b', business_models: [] })) },
};

function req(cookie?: string) {
  return new Request('https://x/api/playbook/a__b', {
    headers: cookie ? { Cookie: `mmwai_sub=${cookie}` } : {},
  });
}

describe('gated playbook', () => {
  it('401s with no cookie', async () => {
    const res = await handle(req(), { ...ENV } as any, 1000, () => Promise.resolve(true));
    expect(res.status).toBe(401);
  });

  it('200s with a fresh valid cookie without hitting Stripe', async () => {
    const cookie = await signCookie({ email: 'a@b.com', verified_at: 1000 }, SECRET);
    const stripe = vi.fn(() => Promise.resolve(true));
    const res = await handle(req(cookie), { ...ENV } as any, 1000 + 100, stripe);
    expect(res.status).toBe(200);
    expect(stripe).not.toHaveBeenCalled();
  });

  it('re-verifies past 24h and 401s if subscription is gone', async () => {
    const cookie = await signCookie({ email: 'a@b.com', verified_at: 1000 }, SECRET);
    const res = await handle(req(cookie), { ...ENV } as any, 1000 + 90000, () => Promise.resolve(false));
    expect(res.status).toBe(401);
  });

  it('re-verifies past 24h, 200s and refreshes cookie if still active', async () => {
    const cookie = await signCookie({ email: 'a@b.com', verified_at: 1000 }, SECRET);
    const res = await handle(req(cookie), { ...ENV } as any, 1000 + 90000, () => Promise.resolve(true));
    expect(res.status).toBe(200);
    expect(res.headers.get('Set-Cookie')).toContain('mmwai_sub=');
  });
});
