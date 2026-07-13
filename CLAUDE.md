# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**Chloride Exide KE — Battery Finder**: A production web app that recommends the correct car battery for Kenyan vehicles. It uses a cleaned CRSP/NTS dataset, a 3-layer rule-based matching engine, and is geo-restricted to Kenya, Uganda and Tanzania.

## Commands

### Backend
All backend code lives in `backend/` (commands below run from there):
```bash
docker compose up -d      # local Postgres 15, matches RDS (run from repo root)
cd backend
pip install -r requirements.txt
alembic upgrade head
python scripts/create_admin.py --username admin --password <password>
uvicorn app:app --reload          # dev server at http://localhost:8000
uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"   # production — required behind the ALB, see README "Running the App"
```

### Frontend (Bun)
```bash
cd frontend
bun install
bun run dev       # http://localhost:5173, proxies /api to :8000
bun run lint
bun run build
bun run preview
```

### Data Pipelines

CRSP pipeline runs in two stages (triggered via admin UI at /admin/data-pipeline). Run from `backend/`:
```bash
python pipelines/dataprep.py            # Stage 1: CRSP Excel → battery_lookup_dataset.csv (clean + dedupe)
python pipelines/enrich_years.py        # Stage 2: multi-source year enrichment → vehicle_years_staging (review before commit)
python pipelines/dial_battery_clean.py  # Dial-A-Battery data → dial_battery_inference table
```

Enrichment sources (fueleconomy.gov CSV, NHTSA VPIC, CarAPI, Wikipedia, Wikidata) are cached in
`cache/year_cache.json` and `cache/fueleconomy_vehicles.csv`. The admin UI shows dataset age and
surfaces a refresh button when the cache is >330 days old.

### CI/CD (Jenkinsfile)
Stages: Checkout → Setup Python → Setup Node.js & Bun → Lint Frontend → Build Frontend → Test Python (pytest) → Archive Artifacts

## Architecture

### Matching Engine (`backend/matcher.py`)
Three layers applied in order, returning at first match:
1. **Exact** — make + fuzzy model (≥90 score) + exact year → confidence 100%
2. **Soft** — make + fuzzy model (≥60 score) + year within ±3 years → confidence 60–89%
3. **Fallback** — engine CC + fuel type → Ah bracket → confidence 30–59%

Pre-match steps: resolve international model names to JDM equivalents via `model_aliases`, infer stop-start requirement from make+year, determine NS/JIS vs DIN standard from vehicle origin region.

All vehicle/battery/alias data is loaded at startup into an LRU cache and held in memory for fast matching.

### Backend (`backend/app.py` + `backend/admin_router.py`)
- `app.py` — public API routes, auth middleware, static file serving (serves built frontend), lifespan events, read-counter middleware (flushes to `admin_stats` every 60 s)
- `admin_router.py` — all `/api/admin/*` routes: batteries CRUD, audit log, sessions, stats, data pipeline trigger
- `admin_auth.py` — bcrypt (cost 12) + HttpOnly/Secure/SameSite=Strict session cookies (8-hour TTL)
- Test users use bcrypt + bearer tokens in localStorage (24-hour TTL)

Rate limits (slowapi): recommend 10/min, feedback 5/min, makes/models/years 20/min, auth endpoints 5/min.

### Database (PostgreSQL + SQLAlchemy 2.0 + Alembic)
Key tables:
- `vehicle_years` — per-make/model/year rows with engine CC + fuel; source for matcher
- `battery_specs` — battery catalogue with soft-delete (`deleted_at`); source for matcher
- `model_aliases` — international → JDM model name mappings
- `battery_audit_log` — immutable change history (old/new values as JSON)
- `user_feedback` — user feedback with satisfaction, accuracy rating, match metadata, IP

Migrations live in `backend/alembic/versions/`. Always run `alembic upgrade head` (from `backend/`) after pulling.

### Frontend (`frontend/src/`)
React 19 + TypeScript + Vite + Tailwind CSS v4. Key areas:
- `components/VehicleFinderForm.tsx` — main search form AND result card; the battery recommendation result is rendered as an inline sub-component inside this file (look for `className="result-card"`), **not** in `ResultCard.tsx`. Uses **inline `style={{}}` props throughout** — always extend with inline styles, not Tailwind utility classes.
- `components/ResultCard.tsx` — legacy/unused component; do not edit for live UI changes
- `lib/api.ts` / `lib/adminApi.ts` — typed fetch wrappers for public and admin APIs
- `lib/TestUserContext.tsx` — React context for test-user session
- `pages/admin/` — admin dashboard pages (Batteries, Audit, Sessions, Feedback, DataPipeline)

In dev, Vite proxies `/api/*` to `localhost:8000`. In production, FastAPI serves the built `frontend/dist/` as static files.

## Environment Variables

```env
DATABASE_URL=postgresql://batteryfinder:batteryfinder@127.0.0.1:5434/batteryfinderdev
ADMIN_COOKIE_SECURE=false   # set false for local HTTP dev; true in production (HTTPS)
```

`.env` lives at the repo root (loaded via `python-dotenv` in `backend/db.py`, found by walking up from wherever the process is started). Never commit `.env`.

## Key Patterns

- All backend code, scripts, pipelines, and their supporting data/cache/upload directories live under `backend/`; run backend commands with `backend/` as the working directory.
- **Upload pipeline** (`backend/upload_pipeline.py`): handles Excel battery data cleanup, validation, and upsert — used by the admin DataPipeline page
- **Accuracy scripts** live in `backend/scripts/` and are standalone — not part of the app runtime
- **Enrichment caches** (`backend/cache/year_cache.json`, `backend/cache/enrichment_cache.json`) speed up re-runs of the data pipelines; safe to delete to force a full re-fetch
- **Source data files** live in `backend/data/` (e.g. `backend/data/Dial-A-Battery Data - 2023-2026.xlsx`)
- **Assets** (logos, diagrams) live in `assets/` at the repo root
- The `battery_specs` table uses soft-delete; always filter `deleted_at IS NULL` when querying active batteries

## Local Postgres & Secrets

- **Local Postgres**: `docker-compose.yml` at the repo root runs a `postgres:15` service (pinned to match the RDS engine version — see README Production Architecture) with a named volume, wired to the existing `DATABASE_URL` convention in `.env`. This is the **primary** local Postgres — dev data was migrated in from a prior native install via `pg_dump`/`psql`. `docker compose up -d` gives a reproducible local Postgres that matches prod; `alembic upgrade head` runs against it unchanged. Published on host port **5434**, not 5432 — a native Postgres install commonly already owns 5432 on the host, and on Windows Docker Desktop would otherwise bind the container's side on IPv6 instead of erroring, silently splitting `localhost:5432` across two different databases (see the comment in `docker-compose.yml`).
- **Secret handling**: production credentials come from AWS SSM Parameter Store / Secrets Manager, injected by ECS as real environment variables at task runtime (see README Production Architecture) — `backend/db.py` never talks to AWS directly. `load_dotenv(override=False)` in `db.py` ensures those injected env vars always win over anything in a `.env` file, so a stray `.env` baked into a production image can never clobber a real secret; `.env` remains purely a local-dev convenience. The expected variables are documented in README.md's Environment Variables section (there is no `.env.example` file — it was removed; create `.env` at the repo root directly from that table).

## COMPLETED (landed 2026-07-08, verified 2026-07-13) — Revert-Bug Fix + Security Hardening

The revert-endpoint FK-violation fix, rate-limiter proxy-trust-boundary fix, admin login lockout (`failed_login_attempts`/`locked_until` on `AdminUser`, migration `20260708_e3f4a5b6c7d8`), explicit `CORSMiddleware` (`ALLOWED_ORIGINS` env var), security headers middleware (CSP/HSTS/X-Frame-Options/etc.), and the CRSP-upload size cap are all implemented and merged to `main` (commits `76a13f9`, `c5633e0`, `d30b88e`, `cc5a52a`, `4c91c70`, `f08147e`). README's Security section documents the AWS-layer controls (CloudFront, WAF, ALB, SSM), and the geo-restriction scope already covers Kenya + Uganda + Tanzania (CloudFront allowlist change was made outside this repo; doc copy here and in README reflects it). CSRF was explicitly declined (HttpOnly/Secure/SameSite=Strict cookies are sufficient) — see README's Security section for that reasoning.

## PENDING PLAN (added 2026-07-05) — Matcher per-make cache (`backend/matcher.py`)

**Problem:** `recommend()` (`matcher.py:783-793`, itself `@lru_cache(maxsize=512)`) filters `df[df["make_n"] == make_n]` from scratch on every cache-miss call (`matcher.py:815`, `897`, `975`) — a full pandas scan of the entire `vehicle_years` table, even though that table only changes when a pipeline commits. Worse, inside `_fuzzy_model_score_for_year()` (`matcher.py:64-150`), every candidate trim considered by the fuzzy scorers (up to ~80 per scorer call, in `_pick_best`'s loop at `matcher.py:98-127`) does *another* fresh pandas filter (`cand_df[cand_df["year"] == year]` / the ±3-year window) just to check what years that one trim was sold in.

**Fix:** add a small `@lru_cache`'d helper in `matcher.py`, keyed by `make_n`, that precomputes once per make: the filtered DataFrame slice, the unique `model_choices` list, and a `dict[model_n → sorted years]`. Use dict/array lookups instead of repeated pandas boolean masking in both the outer `recommend()` filtering and the inner per-candidate year checks.

**Invalidation is free** — `admin_router.py` already calls `matcher._vehicles.cache_clear()` whenever `vehicle_years` changes (e.g. `admin_router.py:639`); just add `matcher.<new_helper>.cache_clear()` alongside it (same pattern already used for `_batteries`, `_model_aliases`, `_inference`, `recommend`).

## PENDING PLAN (added 2026-07-05) — No automated backend test suite

**Problem:** `Jenkinsfile`'s CI pipeline has a "Test Python (pytest)" stage, but a repo-wide search for `test_*.py` under `backend/` finds no actual pytest test files — only `backend/scripts/test_failure_modes.py`, which per this file's existing "Accuracy scripts" note is a standalone script, not part of the app runtime or a pytest suite. The CI stage is almost certainly collecting zero tests today (passes trivially, proves nothing).

**Why this matters concretely:** during this session, two real production bugs were found in `admin_router.py` purely by manual code reading — the revert-endpoint FK-violation bug (missing `db.flush()` before a child row referenced a not-yet-persisted parent id) and the cancel-loses-partial-results bug in the expansion pipeline. Both are exactly the class of bug a basic test suite (unit tests around `matcher.py`'s fuzzy-matching/scoring logic, integration tests around `admin_router.py`'s pipeline run/pause/resume/cancel and CRUD routes against a real test Postgres) would have caught mechanically instead of requiring a manual read-through.

**Fix:** stand up an actual `backend/tests/` pytest suite (using the existing local Docker Postgres — `docker-compose.yml` — as the test DB, consistent with how this repo already treats that as the source of truth for schema behavior). Prioritize: (1) `matcher.py`'s three-layer matching + fuzzy scoring/tie-break logic (pure functions, easy to unit test with small fixture DataFrames), (2) the pipeline run/pause/resume/cancel lifecycle in `admin_router.py` (integration-style, since that's where both real bugs lived), (3) CRUD routes' edge cases (409 on duplicate, 404 on missing, partial-update `exclude_unset` behavior).

**Not urgent to decide now:** whether to also add a CI gate that fails the build if test count is 0 (to prevent this silent-no-op-stage problem from recurring) — worth doing once real tests exist.

## DONE (2026-07-13) — Public, unauthenticated health/readiness endpoint

`GET /health` now exists in `backend/app.py`, unauthenticated, rate-limited at 60/min, returning only `{"status": "ok"/"down"}` after a real `SELECT 1` — the rich diagnostics stay behind the admin-gated `GET /api/admin/health`. Also exempted from the maintenance-mode middleware's 503 override. **Still needs verification against the actual ALB target-group health-check path** (AWS console/IaC, outside this repo) — point it at `/health` if it isn't already.

## PENDING PLAN (added 2026-07-05) — Aggregate connection-pool usage across all ECS tasks

**Problem:** the "Database Health" card on the admin dashboard (`frontend/src/pages/admin/AdminDashboard.tsx:265-298`, fed by `GET /api/admin/health`, `admin_router.py:246-283`) shows `engine.pool.checkedout()` / `engine.pool.size()` — but that's a Python in-process object. With production running 2+ ECS Fargate tasks behind the ALB, each task has its own separate SQLAlchemy `engine` and therefore its own separate pool; whichever task happens to answer a given `/api/admin/health` request only knows about *its own* connections, not the combined total across all tasks actually open against RDS. So today's card under-reports true load on the database — e.g. 3 tasks each showing "6/25 (24%)" looks fine individually, but the real total hitting RDS is 18 connections, and there's no way to see that combined number from the current UI.

**Fix — query Postgres itself for ground truth, not each task's self-reported count:** rather than trying to have every task report its pool stats somewhere and sum them (which needs a coordination layer), query Postgres's own system view directly — `SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()` — from within the existing `/api/admin/health` handler. This returns the actual total number of open connections to this database from every source (every task, migrations, psql, anything), independent of which task happens to serve the request. Compare it against the database's real `max_connections` (queryable via `SHOW max_connections` or `SELECT setting FROM pg_settings WHERE name = 'max_connections'`) to get a true usage percentage, and keep the existing per-task `pool_size`/`pool_checked_out` numbers alongside it as a secondary "this task's share" stat rather than replacing them.

**Why this approach over Redis-based aggregation:** ElastiCache Redis is provisioned but unused elsewhere in this app (see the earlier "no automated test suite" / cache-usage findings this session) and could technically work as a shared counter, but it adds a coordination dependency (every task must remember to report in) for a number Postgres already tracks natively and exposes for free via `pg_stat_activity` — simpler and can't drift out of sync with reality.

**Frontend change:** update `HealthCard` (`AdminDashboard.tsx:266-298`) to show both numbers — the new cluster-wide total (`pg_stat_activity` count / `max_connections`) as the primary bar, and the existing per-task pool stat as a smaller secondary line (e.g. "this instance: 6/25").

## Anti-Scraping Hardening for Public API Endpoints

**Problem:** nothing app-level deters someone from scripting `/api/makes` → `/api/models/{make}` → `/api/years` → `/api/recommend` to enumerate and rebuild the entire CRSP-derived vehicle→battery matching dataset. The only defense today is a per-IP `slowapi` rate limit, and `slowapi`'s default in-memory storage means each of the 2+ Fargate tasks behind the ALB keeps its own separate counter, so per-IP limits are effectively multiplied by however many tasks a scraper's requests land on (README documents this honestly).

**Done (2026-07-13):** the 429 handler for rate-limit violations was fully written but never registered — exceeding a limit returned a raw unhandled-exception 500 instead of a clean 429. Fixed by adding `@app.exception_handler(RateLimitExceeded)` above `rate_limit_handler` in `app.py` (commit `56e4f25`, direct to `main` — small isolated fix, same treatment as the revert-bug fix). This covers both `Limiter` instances (`app.py`, `admin_router.py`) since it's one shared exception class.

**Declined (2026-07-13) — Redis-backed storage + daily caps:** wiring both `Limiter` instances to the provisioned-but-unused ElastiCache Redis (`storage_uri=REDIS_URL`) and adding daily caps on top of the per-minute limits was designed but explicitly rejected as overengineering for this app's threat model — a niche regional lookup tool isn't a high-value target for a resourced attacker, and per-task in-memory daily caps would themselves be leaky (multiplied across tasks, reset on every ECS deploy), so building the daily-cap tier without Redis wasn't worth doing either. Per-minute limits remain per-task/in-memory as they are today. Revisit only if real scraping activity is observed.

**Explicitly deferred (considered, not building now):** a per-browser-session budget independent of IP (server-issued cookie + DB-backed daily counter, mirroring `ApiUsageQuota`'s shape) was designed in detail but declined as disproportionate for the same reason — no in-app defense fully stops a determined scraper anyway (that's what AWS WAF, already in production, is for).

**Worth reconsidering — reCAPTCHA (flagged as a good potential addition, not decided):** unlike a visible CAPTCHA (which breaks the app's frictionless no-login search flow and was rightly declined), invisible reCAPTCHA v3 — scored quietly in the background, no user-facing challenge — would raise the bar significantly beyond Phase 1: a scraper would need to either pay a CAPTCHA-solving service or run full human-mimicking browser automation, not just rotate IPs. Scoped narrowly to `POST /api/recommend` only (the endpoint that actually returns the valuable data), not the lightweight dropdown-population endpoints. The real cost: it's a third-party (Google) dependency that sends visitor behavioral/IP data off our infrastructure, which directly contradicts the current Privacy Policy's explicit claim — *"This application does not integrate any third-party advertising networks, social media tracking pixels, or external analytics platforms. All data remains within Chloride Exide Kenya's own infrastructure"* (`frontend/src/components/PrivacyModal.tsx:82`). Adding it would require rewriting that section, not just appending a bullet. Worth a real decision (not a default) before scoping further — leaning toward yes given how much it raises the bar, but needs the privacy-copy rewrite accounted for as part of the same piece of work.
