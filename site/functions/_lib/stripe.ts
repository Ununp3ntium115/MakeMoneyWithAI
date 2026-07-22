const STRIPE = 'https://api.stripe.com/v1';

function form(params: Record<string, string>): string {
  return new URLSearchParams(params).toString();
}
async function stripeGet(path: string, key: string): Promise<any> {
  const res = await fetch(`${STRIPE}${path}`, { headers: { Authorization: `Bearer ${key}` } });
  if (!res.ok) throw new Error(`Stripe GET ${path} -> ${res.status}`);
  return res.json();
}
async function stripePost(path: string, key: string, body: Record<string, string>): Promise<any> {
  const res = await fetch(`${STRIPE}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form(body),
  });
  if (!res.ok) throw new Error(`Stripe POST ${path} -> ${res.status}`);
  return res.json();
}

export async function hasActiveSubscription(email: string, env: { STRIPE_SECRET_KEY: string }): Promise<boolean> {
  const q = encodeURIComponent(`email:'${email.replace(/'/g, '')}'`);
  const customers = await stripeGet(`/customers/search?query=${q}`, env.STRIPE_SECRET_KEY);
  for (const c of customers.data ?? []) {
    const subs = await stripeGet(`/subscriptions?customer=${c.id}&status=all&limit=10`, env.STRIPE_SECRET_KEY);
    if ((subs.data ?? []).some((s: any) => s.status === 'active' || s.status === 'trialing')) return true;
  }
  return false;
}

export async function createCheckoutSession(
  email: string | null, priceId: string,
  env: { STRIPE_SECRET_KEY: string; SITE_URL: string },
): Promise<{ url: string }> {
  const body: Record<string, string> = {
    mode: 'subscription',
    'line_items[0][price]': priceId,
    'line_items[0][quantity]': '1',
    success_url: `${env.SITE_URL}/api/verify?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${env.SITE_URL}/pricing`,
  };
  if (email) body.customer_email = email;
  const session = await stripePost('/checkout/sessions', env.STRIPE_SECRET_KEY, body);
  return { url: session.url };
}

export async function retrieveCheckoutEmail(
  sessionId: string, env: { STRIPE_SECRET_KEY: string },
): Promise<string | null> {
  const s = await stripeGet(`/checkout/sessions/${sessionId}`, env.STRIPE_SECRET_KEY);
  if (s.status !== 'complete' && s.payment_status !== 'paid') return null;
  return s.customer_details?.email ?? s.customer_email ?? null;
}
