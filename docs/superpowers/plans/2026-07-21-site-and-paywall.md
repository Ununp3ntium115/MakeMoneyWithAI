# Site + Paywall Implementation Plan (Plan B of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Astro static site and the Cloudflare Pages Functions that gate full playbooks behind a Stripe-verified signed cookie, consuming `site/src/data/previews.json` (Plan A) and the `PLAYBOOKS` KV namespace (Plan A).

**Architecture:** Static Astro site bakes public previews into HTML at build time. Full playbook bodies never enter the bundle — they live in KV and are served by a Pages Function that checks a signed cookie proving an active Stripe subscription. No user database; Stripe is the source of truth. Pure logic (cookie sign/verify, gating decision) is unit-tested with vitest; Stripe/Resend/KV are mocked.

**Tech Stack:** Astro 4 (static output), Cloudflare Pages + Pages Functions (Workers runtime, Web Crypto), Stripe REST API via `fetch` (no SDK), Resend REST API via `fetch`, vitest.

## Global Constraints

- Working directory: `/Users/brodynielsen/MakeMoneyWithAI/MakeMoneyWithAI`. Site lives in `site/`; run `pnpm` commands from `site/`.
- Node 20+ / pnpm. Astro output mode `static`.
- Pages Functions run in the Workers runtime: use Web Crypto (`crypto.subtle`), `fetch`, and `env` bindings — NOT Node APIs. No `require`, no `process.env` (use the `env` param).
- Bindings available to functions (configured in Pages dashboard, Task 8): KV binding `PLAYBOOKS`; secrets `STRIPE_SECRET_KEY`, `STRIPE_PRICE_MONTHLY`, `STRIPE_PRICE_YEARLY`, `RESEND_API_KEY`, `COOKIE_SECRET`, `SITE_URL`.
- Cookie name `mmwai_sub`; HMAC-SHA256; payload `{email, verified_at}` (epoch seconds); `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000` (30 days).
- Live subscription re-verification cadence: if `verified_at` is older than 24h, re-check Stripe on the next gated request and refresh the cookie.
- Prices are placeholders — real amounts set in the Stripe dashboard; code only references price IDs from env.
- Full playbook bodies must never be written into `site/` build output or committed. Only `previews.json` is committed.

---

### Task 1: Astro project scaffold + base layout

**Files:**
- Create: `site/package.json`, `site/astro.config.mjs`, `site/tsconfig.json`, `site/.gitignore`
- Create: `site/src/layouts/Base.astro`
- Create: `site/src/data/previews.json` (seed with `[]` if Plan A hasn't produced one yet)

**Interfaces:**
- Produces: a buildable Astro site (`pnpm build` → `site/dist/`); `Base.astro` layout accepting a `title` prop and a `<slot />`.

- [ ] **Step 1: Scaffold**

```bash
cd site
cat > package.json <<'JSON'
{
  "name": "makemoneywithai-site",
  "type": "module",
  "private": true,
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "wrangler pages dev ./dist",
    "test": "vitest run"
  },
  "dependencies": { "astro": "^4.15.0" },
  "devDependencies": { "vitest": "^2.0.0", "wrangler": "^3.78.0" }
}
JSON
cat > astro.config.mjs <<'JS'
import { defineConfig } from 'astro/config';
export default defineConfig({ output: 'static' });
JS
printf '{\n  "extends": "astro/tsconfigs/strict"\n}\n' > tsconfig.json
printf 'node_modules/\ndist/\n.astro/\n' > .gitignore
mkdir -p src/layouts src/data src/pages/projects
[ -f src/data/previews.json ] || printf '[]\n' > src/data/previews.json
pnpm install
```

- [ ] **Step 2: Base layout**

Create `site/src/layouts/Base.astro`:

```astro
---
const { title } = Astro.props;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <header><a href="/">Make Money With AI</a> · <a href="/projects">Projects</a> · <a href="/pricing">Pricing</a> · <a href="/account">Account</a></header>
    <main><slot /></main>
  </body>
</html>
```

Create `site/public/styles.css` with minimal readable styling (system font stack, max-width 720px main, dark-friendly). Content is not load-bearing for tests — keep it simple.

- [ ] **Step 3: Build smoke test**

Run: `cd site && pnpm build`
Expected: `dist/` created, exit 0.

- [ ] **Step 4: Commit**

```bash
git add site/ && git commit -m "Scaffold Astro site with base layout"
```

---

### Task 2: Cookie signing library (pure, TDD)

**Files:**
- Create: `site/functions/_lib/cookie.ts`
- Create: `site/test/cookie.test.ts`
- Modify: `site/package.json` (add vitest config via `vitest.config.ts`)
- Create: `site/vitest.config.ts`

**Interfaces:**
- Produces: `signCookie(payload: {email: string, verified_at: number}, secret: string): Promise<string>`; `verifyCookie(value: string, secret: string): Promise<{email: string, verified_at: number} | null>` (null on tamper/parse failure).

- [ ] **Step 1: vitest config**

Create `site/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { environment: 'node' } });
```

- [ ] **Step 2: Write failing tests**

Create `site/test/cookie.test.ts`:

```ts
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
```

- [ ] **Step 3: Run — expect fail**

Run: `cd site && pnpm test`
Expected: FAIL — cannot resolve `../functions/_lib/cookie`.

- [ ] **Step 4: Implement**

Create `site/functions/_lib/cookie.ts`:

```ts
export interface SubClaim { email: string; verified_at: number }

function b64urlEncode(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function b64urlToBytes(str: string): Uint8Array {
  const pad = str.length % 4 ? '='.repeat(4 - (str.length % 4)) : '';
  const bin = atob(str.replace(/-/g, '+').replace(/_/g, '/') + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
async function hmac(data: string, secret: string): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  return new Uint8Array(sig);
}
function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export async function signCookie(payload: SubClaim, secret: string): Promise<string> {
  const body = b64urlEncode(new TextEncoder().encode(JSON.stringify(payload)));
  const sig = b64urlEncode(await hmac(body, secret));
  return `${body}.${sig}`;
}

export async function verifyCookie(value: string, secret: string): Promise<SubClaim | null> {
  const parts = value.split('.');
  if (parts.length !== 2) return null;
  const [body, sig] = parts;
  try {
    const expected = await hmac(body, secret);
    if (!timingSafeEqual(b64urlToBytes(sig), expected)) return null;
    const claim = JSON.parse(new TextDecoder().decode(b64urlToBytes(body)));
    if (typeof claim?.email !== 'string' || typeof claim?.verified_at !== 'number') return null;
    return claim;
  } catch {
    return null;
  }
}
```

- [ ] **Step 5: Run — expect pass**

Run: `cd site && pnpm test`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add site/functions/_lib/cookie.ts site/test/cookie.test.ts site/vitest.config.ts site/package.json
git commit -m "Add HMAC-signed subscription cookie library"
```

---

### Task 3: Stripe + gating helpers (pure decision logic, TDD)

**Files:**
- Create: `site/functions/_lib/stripe.ts`
- Create: `site/functions/_lib/gate.ts`
- Create: `site/test/gate.test.ts`

**Interfaces:**
- Consumes: `SubClaim` (Task 2)
- Produces:
  - `hasActiveSubscription(email: string, env: StripeEnv): Promise<boolean>` — queries Stripe by email; true if any subscription is `active` or `trialing`. (`StripeEnv = { STRIPE_SECRET_KEY: string }`)
  - `needsReverify(claim: SubClaim, now: number): boolean` — true when `now - claim.verified_at > 86400`.
  - `createCheckoutSession(email: string | null, priceId: string, env): Promise<{url: string}>`
  - `retrieveCheckoutEmail(sessionId: string, env): Promise<string | null>` — confirms a completed session, returns customer email.

- [ ] **Step 1: Write failing tests for the pure part**

Create `site/test/gate.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { needsReverify } from '../functions/_lib/gate';

describe('needsReverify', () => {
  it('is false within 24h', () => {
    expect(needsReverify({ email: 'a@b.com', verified_at: 1000 }, 1000 + 86399)).toBe(false);
  });
  it('is true after 24h', () => {
    expect(needsReverify({ email: 'a@b.com', verified_at: 1000 }, 1000 + 86401)).toBe(true);
  });
});
```

- [ ] **Step 2: Run — expect fail**

Run: `cd site && pnpm test`
Expected: FAIL — cannot resolve `gate`.

- [ ] **Step 3: Implement gate + stripe**

Create `site/functions/_lib/gate.ts`:

```ts
import type { SubClaim } from './cookie';

export function needsReverify(claim: SubClaim, now: number): boolean {
  return now - claim.verified_at > 86400;
}
```

Create `site/functions/_lib/stripe.ts`:

```ts
const STRIPE = 'https://api.stripe.com/v1';

function form(params: Record<string, string>): string {
  return new URLSearchParams(params).toString();
}
async function stripeGet(path: string, key: string): Promise<any> {
  const res = await fetch(`${STRIPE}${path}`, {
    headers: { Authorization: `Bearer ${key}` },
  });
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
```

- [ ] **Step 4: Run — expect pass**

Run: `cd site && pnpm test`
Expected: 6 passed (4 cookie + 2 gate).

- [ ] **Step 5: Commit**

```bash
git add site/functions/_lib/stripe.ts site/functions/_lib/gate.ts site/test/gate.test.ts
git commit -m "Add Stripe REST helpers and reverify gating logic"
```

---

### Task 4: Public pages (index, projects list, project detail with preview)

**Files:**
- Create: `site/src/pages/index.astro`, `site/src/pages/projects/index.astro`, `site/src/pages/projects/[slug].astro`

**Interfaces:**
- Consumes: `site/src/data/previews.json` (array of `{slug, summary, who_its_for, first_business_model}`)
- Produces: static pages; `[slug].astro` renders the public preview and a `<div id="full-playbook" data-slug={slug}>` placeholder plus `/scripts/unlock.js` that fetches `/api/playbook/<slug>`.

- [ ] **Step 1: Projects list**

Create `site/src/pages/projects/index.astro`:

```astro
---
import Base from '../../layouts/Base.astro';
import previews from '../../data/previews.json';
---
<Base title="Projects — Make Money With AI">
  <h1>Projects</h1>
  <ul>
    {previews.map((p) => (
      <li><a href={`/projects/${p.slug}`}>{p.slug.replace('__', '/')}</a> — {p.summary}</li>
    ))}
  </ul>
</Base>
```

- [ ] **Step 2: Project detail with `getStaticPaths`**

Create `site/src/pages/projects/[slug].astro`:

```astro
---
import Base from '../../layouts/Base.astro';
import previews from '../../data/previews.json';
export function getStaticPaths() {
  return previews.map((p) => ({ params: { slug: p.slug }, props: { preview: p } }));
}
const { preview } = Astro.props;
---
<Base title={`${preview.slug.replace('__', '/')} — Make Money With AI`}>
  <h1>{preview.slug.replace('__', '/')}</h1>
  <p>{preview.summary}</p>
  <p><strong>Who it's for:</strong> {preview.who_its_for}</p>
  <h2>{preview.first_business_model.name}</h2>
  <p>{preview.first_business_model.description}</p>
  <hr />
  <section id="full-playbook" data-slug={preview.slug}>
    <p><a href="/pricing">Subscribe</a> to unlock the full playbook: all business models, step-by-step, costs, and risks.</p>
  </section>
  <script src="/scripts/unlock.js" is:inline></script>
</Base>
```

- [ ] **Step 3: Unlock script**

Create `site/public/scripts/unlock.js`:

```js
(async () => {
  const el = document.getElementById('full-playbook');
  if (!el) return;
  const res = await fetch(`/api/playbook/${el.dataset.slug}`);
  if (res.status !== 200) return; // keep the subscribe prompt
  const pb = await res.json();
  el.innerHTML = `<h2>Full playbook</h2>` +
    pb.business_models.map((b) => `<h3>${b.name} (${b.difficulty})</h3><p>${b.description}</p><p>Cost: ${b.startup_cost} · Potential: ${b.revenue_potential}</p>`).join('') +
    `<h3>Getting started</h3><ol>${pb.getting_started_steps.map((s) => `<li>${s}</li>`).join('')}</ol>` +
    `<p><strong>Cost:</strong> ${pb.cost_estimate}</p>` +
    `<h3>Risks</h3><ul>${pb.risks.map((r) => `<li>${r}</li>`).join('')}</ul>`;
})();
```

- [ ] **Step 4: Home page**

Create `site/src/pages/index.astro` — hero + link to `/projects` and `/pricing`, short pitch. Import `previews` and show a count (`{previews.length} projects`).

- [ ] **Step 5: Build check**

Run: `cd site && pnpm build`
Expected: exit 0; `dist/projects/index.html` exists (if previews.json non-empty, per-slug pages too).

- [ ] **Step 6: Commit**

```bash
git add site/src/pages/ site/public/scripts/unlock.js
git commit -m "Add public pages: home, projects list, project detail with preview"
```

---

### Task 5: Gated playbook function (the paywall core, TDD)

**Files:**
- Create: `site/functions/api/playbook/[slug].ts`
- Create: `site/test/playbook.test.ts`

**Interfaces:**
- Consumes: `verifyCookie`, `signCookie` (Task 2); `hasActiveSubscription`, `needsReverify` (Task 3); KV binding `env.PLAYBOOKS`.
- Produces: `onRequestGet(context)` — 200 + playbook JSON if the cookie proves an active sub (re-verifying past 24h and refreshing the cookie); 401 otherwise. Exported `handle(request, env, now)` for testing.

- [ ] **Step 1: Write failing tests**

Create `site/test/playbook.test.ts`:

```ts
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
```

- [ ] **Step 2: Run — expect fail**

Run: `cd site && pnpm test`
Expected: FAIL — cannot resolve `[slug]`.

- [ ] **Step 3: Implement**

Create `site/functions/api/playbook/[slug].ts`:

```ts
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
```

- [ ] **Step 4: Run — expect pass**

Run: `cd site && pnpm test`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add site/functions/api/playbook/ site/test/playbook.test.ts
git commit -m "Add gated playbook function with 24h Stripe re-verification"
```

---

### Task 6: Checkout + verify functions

**Files:**
- Create: `site/functions/api/checkout.ts`, `site/functions/api/verify.ts`, `site/functions/api/session.ts`
- Create: `site/test/checkout.test.ts`

**Interfaces:**
- Consumes: `createCheckoutSession`, `retrieveCheckoutEmail` (Task 3); `signCookie`, `verifyCookie` (Task 2).
- Produces:
  - `POST /api/checkout {plan: 'monthly'|'yearly', email?}` → `{url}` (302-able) using the matching price env.
  - `GET /api/verify?session_id=…` → confirms the session, sets the cookie, 302 → `/projects`.
  - `GET /api/session` → `{subscribed: boolean}` from the cookie (no Stripe call).

- [ ] **Step 1: Write failing tests** (checkout URL selection + verify sets cookie)

Create `site/test/checkout.test.ts`:

```ts
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
});

describe('verify', () => {
  it('sets a cookie and redirects on a paid session', async () => {
    const req = new Request('https://x/api/verify?session_id=cs_1');
    const res = await handleVerify(req, { COOKIE_SECRET: 'sec' } as any, 1000, async () => 'a@b.com');
    expect(res.status).toBe(302);
    expect(res.headers.get('Set-Cookie')).toContain('mmwai_sub=');
  });

  it('does not set a cookie on an unpaid session', async () => {
    const req = new Request('https://x/api/verify?session_id=cs_1');
    const res = await handleVerify(req, { COOKIE_SECRET: 'sec' } as any, 1000, async () => null);
    expect(res.headers.get('Set-Cookie')).toBeNull();
  });
});
```

- [ ] **Step 2: Run — expect fail.** Run: `cd site && pnpm test` → cannot resolve modules.

- [ ] **Step 3: Implement**

Create `site/functions/api/checkout.ts`:

```ts
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
```

Create `site/functions/api/verify.ts`:

```ts
import { signCookie } from '../_lib/cookie';
import { retrieveCheckoutEmail } from '../_lib/stripe';

function setCookie(value: string): string {
  return `mmwai_sub=${value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`;
}
export async function handleVerify(
  request: Request, env: any, now: number,
  getEmail: typeof retrieveCheckoutEmail = retrieveCheckoutEmail,
): Promise<Response> {
  const sessionId = new URL(request.url).searchParams.get('session_id');
  if (!sessionId) return new Response('missing session', { status: 400 });
  let email: string | null = null;
  try { email = await getEmail(sessionId, env); } catch { return new Response('verify failed', { status: 503 }); }
  if (!email) return Response.redirect(`${env.SITE_URL}/pricing`, 302);
  const cookie = await signCookie({ email, verified_at: now }, env.COOKIE_SECRET);
  return new Response(null, { status: 302, headers: { Location: `${env.SITE_URL}/projects`, 'Set-Cookie': setCookie(cookie) } });
}
export const onRequestGet = (ctx: any) => handleVerify(ctx.request, ctx.env, Math.floor(Date.now() / 1000));
```

Create `site/functions/api/session.ts`:

```ts
import { verifyCookie } from '../_lib/cookie';
export const onRequestGet = async (ctx: any) => {
  const header = ctx.request.headers.get('Cookie') || '';
  const raw = header.split(';').map((p: string) => p.trim()).find((p: string) => p.startsWith('mmwai_sub='));
  const claim = raw ? await verifyCookie(raw.slice('mmwai_sub='.length), ctx.env.COOKIE_SECRET) : null;
  return new Response(JSON.stringify({ subscribed: !!claim }), { headers: { 'Content-Type': 'application/json' } });
};
```

- [ ] **Step 4: Run — expect pass.** Run: `cd site && pnpm test` → 13 passed.

- [ ] **Step 5: Commit**

```bash
git add site/functions/api/checkout.ts site/functions/api/verify.ts site/functions/api/session.ts site/test/checkout.test.ts
git commit -m "Add checkout, verify, and session functions"
```

---

### Task 7: Login (magic link) + pricing/account pages

**Files:**
- Create: `site/functions/_lib/resend.ts`, `site/functions/api/login.ts`
- Create: `site/test/login.test.ts`
- Create: `site/src/pages/pricing.astro`, `site/src/pages/account.astro`

**Interfaces:**
- Consumes: `hasActiveSubscription` (Task 3); `signCookie` (Task 2).
- Produces:
  - `sendMagicLink(email, link, env): Promise<void>` (Resend REST).
  - `POST /api/login {email}` → 200 generic message always (no account enumeration); if an active sub exists, emails a 15-min HMAC token link to `/api/verify?token=…`.
  - `verify.ts` extended to accept `?token=` (short-lived login token) in addition to `?session_id=`.

- [ ] **Step 1: Write failing test** (login always 200; email sent only when subscribed)

Create `site/test/login.test.ts`:

```ts
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
});
```

- [ ] **Step 2: Run — expect fail.**

- [ ] **Step 3: Implement** `resend.ts`, `login.ts`, and extend `verify.ts` to handle `?token=` (reuse `signCookie`/`verifyCookie` with a `{email, verified_at}` claim whose `verified_at` doubles as issue time; reject tokens older than 900s). Login token link: `${SITE_URL}/api/verify?token=<signed>`.

```ts
// site/functions/_lib/resend.ts
export async function sendMagicLink(email: string, link: string, env: { RESEND_API_KEY: string }): Promise<void> {
  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: 'MakeMoneyWithAI <login@makemoneywithai.dev>', to: [email],
      subject: 'Your login link', html: `<p><a href="${link}">Sign in</a> (valid 15 minutes).</p>`,
    }),
  });
  if (!res.ok) throw new Error(`Resend -> ${res.status}`);
}
```

```ts
// site/functions/api/login.ts
import { signCookie } from '../_lib/cookie';
import { hasActiveSubscription } from '../_lib/stripe';
import { sendMagicLink } from '../_lib/resend';

export async function handleLogin(
  request: Request, env: any, now: number,
  isSub = hasActiveSubscription, send = sendMagicLink,
): Promise<Response> {
  const { email } = await request.json().catch(() => ({}));
  const generic = new Response(JSON.stringify({ ok: true, message: 'If that email has an active subscription, a login link is on its way.' }), { headers: { 'Content-Type': 'application/json' } });
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
```

Extend `verify.ts` `handleVerify` start:

```ts
  const token = new URL(request.url).searchParams.get('token');
  if (token) {
    const claim = await verifyCookie(token, env.COOKIE_SECRET); // reuse import
    if (!claim || now - claim.verified_at > 900) return Response.redirect(`${env.SITE_URL}/account`, 302);
    const cookie = await signCookie({ email: claim.email, verified_at: now }, env.COOKIE_SECRET);
    return new Response(null, { status: 302, headers: { Location: `${env.SITE_URL}/projects`, 'Set-Cookie': setCookie(cookie) } });
  }
```

(Add `import { verifyCookie } from '../_lib/cookie';` to verify.ts.)

- [ ] **Step 4: Pricing + account pages.** `pricing.astro`: two buttons posting to `/api/checkout` with `{plan}`, then `window.location = url`. `account.astro`: email input posting to `/api/login`, plus a "you're subscribed" state driven by `GET /api/session`.

- [ ] **Step 5: Run — expect pass.** Run: `cd site && pnpm test` → 15 passed. Then `pnpm build` → exit 0.

- [ ] **Step 6: Commit**

```bash
git add site/functions/_lib/resend.ts site/functions/api/login.ts site/functions/api/verify.ts site/test/login.test.ts site/src/pages/pricing.astro site/src/pages/account.astro
git commit -m "Add magic-link login and pricing/account pages"
```

---

### Task 8: Cloudflare Pages deploy + live payment smoke test

**Blocked on user-supplied Cloudflare + Stripe + Resend accounts.** If credentials are unavailable, stop — Tasks 1-7 are complete and fully unit-tested without them.

**Files:**
- Create: `site/wrangler.toml` (KV binding declaration for local `wrangler pages dev`)
- Modify: `CLAUDE.md` (document site build/test/deploy commands)

- [ ] **Step 1: Bind + secrets.** In the Cloudflare Pages project (created from this repo, build command `cd site && pnpm build`, output `site/dist`): add KV binding `PLAYBOOKS` → the namespace from Plan A Task 6; add the function secrets (`STRIPE_SECRET_KEY`, `STRIPE_PRICE_MONTHLY`, `STRIPE_PRICE_YEARLY`, `RESEND_API_KEY`, `COOKIE_SECRET` = 32+ random bytes, `SITE_URL` = the pages.dev URL).
- [ ] **Step 2: First deploy** via `wrangler pages deploy site/dist` (or Git-connected auto-deploy).
- [ ] **Step 3: Live smoke** — visit `/projects`, confirm a preview shows and the full body is gated; run Stripe test-mode checkout (card `4242 4242 4242 4242`), confirm redirect sets the cookie and the full playbook renders; from an incognito window, use `/account` → magic link → unlock.
- [ ] **Step 4: Document** the commands in `CLAUDE.md`, commit.

---

## Plan Self-Review (completed)

- **Spec coverage:** static previews public + full bodies KV-only (Tasks 4, 5); Stripe-as-DB, no user store (Tasks 3, 5, 6); signed cookie + 24h reverify (Tasks 2, 5); magic-link re-login, no enumeration (Task 7); pricing from env (Tasks 3, 6); 503-on-dependency-failure (Tasks 5, 6, 7). CI/Threads are Plan C.
- **Placeholders:** none — every function has complete code; pages whose exact markup isn't test-load-bearing (home, pricing, account styling) have explicit content requirements.
- **Type consistency:** `SubClaim`, `signCookie`/`verifyCookie`, `hasActiveSubscription`, `needsReverify`, `createCheckoutSession`/`retrieveCheckoutEmail`, `handle`/`handleCheckout`/`handleVerify`/`handleLogin` signatures match across tasks and tests.
