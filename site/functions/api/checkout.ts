import { createCheckoutSession } from '../_lib/stripe';

export async function handleCheckout(
  request: Request, env: any,
  create: typeof createCheckoutSession = createCheckoutSession,
): Promise<Response> {
  const { plan, email } = await request.json().catch(() => ({}));
  const priceId = plan === 'yearly' ? env.STRIPE_PRICE_YEARLY : env.STRIPE_PRICE_MONTHLY;
  if (!priceId) return new Response('bad plan', { status: 400 });
  try {
    const { url } = await create(email ?? null, priceId, env);
    return new Response(JSON.stringify({ url }), { headers: { 'Content-Type': 'application/json' } });
  } catch {
    return new Response('checkout unavailable', { status: 503 });
  }
}
export const onRequestPost = (ctx: any) => handleCheckout(ctx.request, ctx.env);
