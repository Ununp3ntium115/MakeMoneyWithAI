# MakeMoneyWithAI SaaS — Design

Date: 2026-07-21
Status: Approved by user (architecture, content model, paywall, CI/scope sections each approved individually)

## What we're building

A freemium SaaS built on the existing curated-list pipeline. The public site lists 400+ high-star AI projects; each project gets an AI-generated **money-making playbook** (business models, setup steps, cost estimates, risks). The list and playbook **previews** are free and search-indexable; **full playbooks** require a Stripe subscription.

Decisions made during brainstorming:

| Question | Decision |
| --- | --- |
| Product shape | Full product/SaaS (not just a site or research tool) |
| Paid value | Money-making playbooks per project |
| Content production | AI pipeline generates playbooks for all repos; no human review gate |
| Paywall | Freemium previews — previews public/indexable, full content subscription-only |
| Stack | Mostly static + Stripe: Astro on Cloudflare Pages, Pages Functions, KV |
| Architecture | "Stripe-as-database": no user store; Stripe is the source of truth for who has access |

## Repo layout

All code lives in the existing fork `Ununp3ntium115/MakeMoneyWithAI` (diverges from upstream; upstream data changes can still be merged).

```text
MakeMoneyWithAI/
├── fetch_projects.py          # existing pipeline — unchanged role
├── generate_playbooks.py      # NEW: LLM → structured playbook JSON per repo
├── playbooks/                 # NEW: local working dir, GITIGNORED (see below)
├── site/                      # NEW: Astro project
│   ├── src/data/previews.json # committed: public preview content for all repos
│   ├── src/pages/             # /, /projects, /projects/[slug], /pricing, /account
│   ├── functions/api/         # Cloudflare Pages Functions (paywall endpoints)
│   └── public/
└── .github/workflows/
    └── fetch-ai-projects.yml  # extended: data → playbooks → KV → build → deploy
```

## Data flow

1. `fetch_projects.py` (existing, daily): refresh `repos.csv` + `README.md`.
2. `generate_playbooks.py` (new): for each repo in `repos.csv` whose slug is **not already a key in Cloudflare KV** (KV is the source of truth for what exists — the repo is public, so full bodies are never committed to git), call OpenAI (`OPENAI_MODEL`, default `gpt-5-mini`, empty-counts-as-unset), write `playbooks/<owner>__<name>.json` locally (gitignored), and extract its preview into `site/src/data/previews.json` (committed — previews are public content anyway). If the KV key listing fails, abort generation rather than regenerating blindly. Existing playbooks are never regenerated automatically (same caching philosophy as descriptions); a `--force <owner>/<name>` flag allows manual regeneration. KV data loss is recoverable by regenerating (single-digit dollars).
3. CI uploads each playbook's **full body** to Cloudflare KV (`wrangler kv bulk put`), keyed by slug.
4. Astro build bakes **previews only** into static HTML, plus `index.json` for client-side search/filter.
5. Deploy to Cloudflare Pages (site + functions in one artifact, served at `*.pages.dev`; custom domain can be attached later without changes).

## Playbook content model

Schema-validated JSON per repo:

```json
{
  "slug": "owner__name",
  "generated_at": "ISO-8601",
  "model": "model-id-used",
  "summary": "2-3 sentences, what it is and the monetization thesis",
  "who_its_for": "1-2 sentences",
  "business_models": [
    {
      "name": "",
      "description": "",
      "difficulty": "low|medium|high",
      "startup_cost": "e.g. $0-100/mo",
      "revenue_potential": "qualitative, e.g. side-income / full-business"
    }
  ],
  "getting_started_steps": ["3-7 concrete steps"],
  "cost_estimate": "running-cost summary",
  "risks": ["2-5 items"]
}
```

- **Preview** (public): `summary` + `who_its_for` + `business_models[0]`.
- **Full body** (gated): everything. Exists only in KV, never in the static bundle — cannot be scraped from site assets.
- Generation: one retry on schema-validation failure, then skip and log. Failure of one playbook never fails the run.
- Cost envelope: ~400 repos ≈ single-digit dollars one-time with gpt-4.1-mini; then only new repos (≈1/day).

## Paywall — Stripe as the database

No user table, no passwords. Stripe holds the only customer data.

- **Pricing**: one Stripe Product, two Prices — defaults $9/month, $69/year. Real amounts are set in the Stripe dashboard; the site reads price IDs from config (env), so changing price requires no code change.
- **Buy**: /pricing → `POST /api/checkout` creates a Stripe Checkout session → on success Stripe redirects to `/api/verify?session_id=…` → function confirms the session server-side with Stripe → sets a signed cookie → redirect to the playbook the user came from (or /projects).
- **Cookie**: HMAC-signed value `{email, verified_at}`, 30-day expiry, `HttpOnly`, `Secure`, `SameSite=Lax`. Secret is a Pages Function environment secret.
- **Re-login (new device)**: /account → `POST /api/login {email}` → function queries Stripe for an active subscription on that email → if found, sends a magic link via Resend (free tier) → link hits `/api/verify?token=…` (HMAC-signed, 15-minute expiry) → sets cookie. If not found, generic "no active subscription found" (no account enumeration detail).
- **Read**: project page JS calls `GET /api/playbook/<slug>` → function checks cookie; if `verified_at` older than 24h, re-verifies subscription live against Stripe and refreshes the cookie (catches cancellations within a day) → returns full playbook JSON from KV.
- **Status**: `GET /api/session` returns `{subscribed: bool}` for UI state.
- No Stripe webhooks in v1 — live verification makes them unnecessary.

## CI/CD

Extend `.github/workflows/fetch-ai-projects.yml`:

```text
refresh data (existing) → generate playbooks → commit data changes
(README.md, repos.csv, site/src/data/previews.json)
→ wrangler KV bulk upload → astro build → cloudflare/pages-action deploy
```

- New CI secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`. Existing: `OPENAI_API_KEY`; existing repo var: `OPENAI_MODEL`.
- Pages Function secrets (set via wrangler/dashboard, not CI): `STRIPE_SECRET_KEY`, `RESEND_API_KEY`, `COOKIE_SECRET`.
- Known constraint: the GitHub account currently has a billing lock blocking Actions. Until cleared, the same pipeline runs locally (documented in CLAUDE.md); the workflow is ready for when Actions unlock.

## Error handling

- Pipeline: playbook generation failures are per-repo (retry once, skip, log); the run and deploy continue.
- Functions: Stripe/Resend/KV failures return 503 with a friendly message; never expose stack traces; cookie parse failures are treated as logged-out, not errors.
- Build: Astro build fails hard on malformed playbook/preview data — a broken deploy is prevented, the previous deploy stays live (Pages keeps last good).

## Testing

- **Functions**: vitest — cookie sign/verify round-trip and tampering, gating logic (no cookie / expired / stale-reverify), checkout-verify flow with Stripe mocked, login flow with Stripe + Resend mocked.
- **Pipeline**: schema validation is the gate; a unit test runs `generate_playbooks.py` against a fixture repo with a mocked OpenAI response.
- **Site**: the Astro build over real data is the smoke test; CI fails on build failure.
- **Payments**: one manual end-to-end run in Stripe test mode (test card → cookie → gated content) before switching to live keys.

## Explicitly out of scope (v1)

Newsletter, personalized feeds, alerts/trend engine, metered free tier, admin UI, community features, affiliate tracking, custom domain, Stripe webhooks. All are additive later; the only stateful seam is the gate function, so none require rework of v1.
