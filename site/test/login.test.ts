import { describe, it, expect, vi } from 'vitest';
import { handleLogin } from '../functions/api/login';

const ENV = { COOKIE_SECRET: 'sec', SITE_URL: 'https://x', STRIPE_SECRET_KEY: 'sk', RESEND_API_KEY: 're' };

describe('login', () => {
  it('200s generically and does not email a non-subscriber', async () => {
    const send = vi.fn();
    const req = new Request('https://x/api/login', { method: 'POST', body: JSON.stringify({ email: 'no@b.com' }) });
    const res = await handleLogin(req, ENV as any, 1000, async () => false, send);
    expect(res.status).toBe(200);
    expect(send).not.toHaveBeenCalled();
  });
  it('emails a subscriber a link', async () => {
    const send = vi.fn();
    const req = new Request('https://x/api/login', { method: 'POST', body: JSON.stringify({ email: 'yes@b.com' }) });
    const res = await handleLogin(req, ENV as any, 1000, async () => true, send);
    expect(res.status).toBe(200);
    expect(send).toHaveBeenCalledOnce();
    expect(send.mock.calls[0][1]).toContain('/api/verify?token=');
  });
  it('does not enumerate on a bad email', async () => {
    const send = vi.fn();
    const req = new Request('https://x/api/login', { method: 'POST', body: JSON.stringify({ email: 'notanemail' }) });
    const res = await handleLogin(req, ENV as any, 1000, async () => true, send);
    expect(res.status).toBe(200);
    expect(send).not.toHaveBeenCalled();
  });
});
