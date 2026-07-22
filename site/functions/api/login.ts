import { signCookie } from '../_lib/cookie';
import { hasActiveSubscription } from '../_lib/stripe';
import { sendMagicLink } from '../_lib/resend';

export async function handleLogin(
  request: Request, env: any, now: number,
  isSub = hasActiveSubscription, send = sendMagicLink,
): Promise<Response> {
  const { email } = await request.json().catch(() => ({}));
  const generic = new Response(
    JSON.stringify({ ok: true, message: 'If that email has an active subscription, a login link is on its way.' }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (typeof email !== 'string' || !email.includes('@')) return generic;
  try {
    if (await isSub(email, env)) {
      const token = await signCookie({ email, verified_at: now }, env.COOKIE_SECRET);
      await send(email, `${env.SITE_URL}/api/verify?token=${encodeURIComponent(token)}`, env);
    }
  } catch { /* fail closed: still return generic */ }
  return generic;
}
export const onRequestPost = (ctx: any) => handleLogin(ctx.request, ctx.env, Math.floor(Date.now() / 1000));
