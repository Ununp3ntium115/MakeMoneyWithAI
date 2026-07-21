# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A curated list generator: `fetch_projects.py` searches GitHub for popular AI repos (topics `ai`, `ai-agent`, `llm`; ≥10k stars; pushed within the last year), asks OpenAI (default `gpt-5-mini`, overridable via the `OPENAI_MODEL` env var — empty counts as unset; CI supplies it from the `vars.OPENAI_MODEL` repo variable) to write a one-sentence monetization-focused description for each *new* repo, and regenerates `README.md` — the product of this repo — plus `repos.csv`.

## Commands

```bash
pip install requests                 # only dependency

export GITHUB_TOKEN=...              # required (GitHub search API)
export OPENAI_API_KEY=...            # required (description generation)

python fetch_projects.py             # full run: fetch, describe new repos, rewrite CSV + README
python fetch_projects.py 20          # limit to first 20 fetched repos (cheap test run)
```

There are no tests and no linter. `.env`, `.venv/`, `venv/` are gitignored.

## Architecture

The data flow is a pipeline with `repos.csv` as the persistent store:

1. **Fetch**: GitHub search per topic (paginated, 50×10 pages), plus explicit repos from `extra-repos.txt` (always included, fetched individually).
2. **Enrich**: for each repo whose GitHub `id` is **not already in `repos.csv`**, call OpenAI to generate a `business_model` sentence. Existing rows keep their cached description — OpenAI is never re-called for known repos. On API failure it falls back to the plain GitHub description.
3. **Persist**: rewrite `repos.csv` (all repos, sorted by stars, exclusions applied).
4. **Render**: regenerate `README.md` entirely from `repos.csv`.

Consequences:

- **Never hand-edit `README.md`** — it is overwritten on every run. To fix a description, edit the `business_model` column in `repos.csv`; to remove a repo, add it to `excluded-repos.txt`.
- `excluded-repos.txt` supports two line formats: `owner/repo` (exact full-name match) or a bare name (matches any repo with that name, case-insensitive). Exclusions are applied at fetch, CSV-write, and README-render stages, so adding an exclusion takes effect on the next run without touching the CSV.
- Archived repos are skipped during fetch.

## CI

`.github/workflows/fetch-ai-projects.yml` runs the script on every push and daily at midnight UTC, then commits `README.md` + `repos.csv` as `github-actions[bot]` if they changed. `OPENAI_API_KEY` must exist as a repo secret; `GITHUB_TOKEN` is the built-in Actions token.
