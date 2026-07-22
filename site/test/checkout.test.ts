import { describe, it, expect, vi } from 'vitest';
import { handleCheckout } from '../functions/api/checkout';
import { handleVerify } from '../functions/api/verify';

describe('checkout', () => {
  it('picks the yearly price', async () => {
    const create = vi.fn(async () => ({ url: 'https://stripe/session' }));
    const req = new Request('https://x/api/checkout', {
      method: 'POST', body: JSON.stringify({ plan: 'yearly' }),
    });
    const res = await handleCheckout(req, { STRIPE_PRICE_YEARLY: 'price_year', STRIPE_PRICE_MONTHLY: 'price_month' } as any, create);
    expect(create).toHaveBeenCalledWith(null, 'price_year', expect.anything());
    expect((await res.json()).url).toBe('https://stripe/session');
  });

  it('picks the monthly price by default', async () => {
    const create = vi.fn(async () => ({ url: 'https://stripe/m' }));
    const req = new Request('https://x/api/checkout', { method: 'POST', body: JSON.stringify({ plan: 'monthly' }) });
    await handleCheckout(req, { STRIPE_PRICE_YEARLY: 'price_year', STRIPE_PRICE_MONTHLY: 'price_month' } as any, create);
    expect(create).toHaveBeenCalledWith(null, 'price_month', expect.anything());
  });
});

describe('verify', () => {
  it('sets a cookie and redirects on a paid session', async () => {
    const req = new Request('https://x/api/verify?session_id=cs_1');
    const res = await handleVerify(req, { COOKIE_SECRET: 'sec', SITE_URL: 'https://x' } as any, 1000, async () => 'a@b.com');
    expect(res.status).toBe(302);
    expect(res.headers.get('Set-Cookie')).toContain('mmwai_sub=');
  });

  it('does not set a cookie on an unpaid session', async () => {
    const req = new Request('https://x/api/verify?session_id=cs_1');
    const res = await handleVerify(req, { COOKIE_SECRET: 'sec', SITE_URL: 'https://x' } as any, 1000, async () => null);
    expect(res.headers.get('Set-Cookie')).toBeNull();
  });
});
