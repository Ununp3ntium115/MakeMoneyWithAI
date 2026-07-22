import { signCookie, verifyCookie } from '../_lib/cookie';
import { retrieveCheckoutEmail } from '../_lib/stripe';

function setCookie(value: string): string {
  return `mmwai_sub=${value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`;
}
export async function handleVerify(
  request: Request, env: any, now: number,
  getEmail: typeof retrieveCheckoutEmail = retrieveCheckoutEmail,
): Promise<Response> {
  const url = new URL(request.url);

  // Magic-link login token (from /api/login), valid 15 minutes.
  const token = url.searchParams.get('token');
  if (token) {
    const claim = await verifyCookie(token, env.COOKIE_SECRET);
    if (!claim || now - claim.verified_at > 900) return Response.redirect(`${env.SITE_URL}/account`, 302);
    const cookie = await signCookie({ email: claim.email, verified_at: now }, env.COOKIE_SECRET);
    return new Response(null, { status: 302, headers: { Location: `${env.SITE_URL}/projects`, 'Set-Cookie': setCookie(cookie) } });
  }

  // Stripe Checkout completion.
  const sessionId = url.searchParams.get('session_id');
  if (!sessionId) return new Response('missing session', { status: 400 });
  let email: string | null = null;
  try { email = await getEmail(sessionId, env); } catch { return new Response('verify failed', { status: 503 }); }
  if (!email) return Response.redirect(`${env.SITE_URL}/pricing`, 302);
  const cookie = await signCookie({ email, verified_at: now }, env.COOKIE_SECRET);
  return new Response(null, { status: 302, headers: { Location: `${env.SITE_URL}/projects`, 'Set-Cookie': setCookie(cookie) } });
}
export const onRequestGet = (ctx: any) => handleVerify(ctx.request, ctx.env, Math.floor(Date.now() / 1000));
