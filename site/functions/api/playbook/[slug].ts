import { verifyCookie, signCookie } from '../../_lib/cookie';
import { needsReverify } from '../../_lib/gate';
import { hasActiveSubscription } from '../../_lib/stripe';

function readCookie(request: Request, name: string): string | null {
  const header = request.headers.get('Cookie') || '';
  for (const part of header.split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return v.join('=');
  }
  return null;
}
function setCookie(value: string): string {
  return `mmwai_sub=${value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`;
}

// `verify` is injected in tests; production uses hasActiveSubscription.
export async function handle(
  request: Request, env: any, now: number,
  verify: (email: string, env: any) => Promise<boolean> = hasActiveSubscription,
): Promise<Response> {
  const raw = readCookie(request, 'mmwai_sub');
  if (!raw) return new Response('unauthorized', { status: 401 });
  const claim = await verifyCookie(raw, env.COOKIE_SECRET);
  if (!claim) return new Response('unauthorized', { status: 401 });

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (needsReverify(claim, now)) {
    if (!(await verify(claim.email, env))) return new Response('unauthorized', { status: 401 });
    const refreshed = await signCookie({ email: claim.email, verified_at: now }, env.COOKIE_SECRET);
    headers['Set-Cookie'] = setCookie(refreshed);
  }

  const slug = new URL(request.url).pathname.split('/').pop()!;
  const body = await env.PLAYBOOKS.get(slug);
  if (!body) return new Response('not found', { status: 404 });
  return new Response(body, { status: 200, headers });
}

export const onRequestGet = (ctx: any) => handle(ctx.request, ctx.env, Math.floor(Date.now() / 1000));
