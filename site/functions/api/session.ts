import { verifyCookie } from '../_lib/cookie';
export const onRequestGet = async (ctx: any) => {
  const header = ctx.request.headers.get('Cookie') || '';
  const raw = header.split(';').map((p: string) => p.trim()).find((p: string) => p.startsWith('mmwai_sub='));
  const claim = raw ? await verifyCookie(raw.slice('mmwai_sub='.length), ctx.env.COOKIE_SECRET) : null;
  return new Response(JSON.stringify({ subscribed: !!claim }), { headers: { 'Content-Type': 'application/json' } });
};
