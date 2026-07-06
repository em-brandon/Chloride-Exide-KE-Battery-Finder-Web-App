# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**Chloride Exide KE — Battery Finder**: A production web app that recommends the correct car battery for Kenyan vehicles. It uses a cleaned CRSP/NTS dataset, a 3-layer rule-based matching engine, and is geo-restricted to Kenya.

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
uvicorn app:app --host 0.0.0.0 --port 8000   # production
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

## PENDING PLAN (approved, not yet executed as of 2026-07-05) — Revert-Bug Fix + Security Hardening

This is a full implementation plan awaiting execution. Pick this up and carry it out when asked to continue this work.

### Context

Two independent items:

1. **A known pre-existing bug**, flagged (but explicitly left unfixed) during the earlier vehicle-expansion work: `POST /api/admin/pipeline/crsp/versions/{id}/revert` throws a 500 `IntegrityError` (FK violation on `vehicle_years_changelog_version_id_fkey`). The user now wants it fixed, committed **directly to `main`** (small, isolated, low-risk fix — explicit exception to the usual feature-branch rule).

2. A **security hardening pass**, prompted by the user browsing the app and asking about CORS, load balancers, and defenses against IP-rotation attacks bypassing the existing slowapi rate limiting (excluding AWS-managed security services like WAF/Shield — the ask is for what we control in application code/config). Two background investigation agents audited the current state; the user confirmed:
   - **Production topology is CloudFront → ALB+WAF → ECS Fargate (2+ tasks)** — README.md is the accurate doc; `AWS-MIGRATION-PLAN.md`'s single-EC2-no-LB description is stale/aspirational and out of scope to reconcile here.
   - This hardening work goes on a **feature branch** (higher blast radius than the isolated bug fix — touches CORS/middleware/auth across the whole app).
   - Plan is based on the completed static code audit; live curl/browser verification happens after implementation, not before.

A significant finding from the audit, given the confirmed ALB+Fargate topology: **the rate limiter is currently broken in production, not just theoretically weak.** `Limiter(key_func=get_remote_address)` (`backend/app.py:137`, `backend/admin_router.py:74`) reads `request.client.host` — the raw TCP peer. Behind an ALB, that's the ALB's own IP for every single request (Fargate tasks never see the real client IP on the socket; it only arrives via the `X-Forwarded-For` header). So today, every user of the app **shares one single rate-limit bucket** — e.g. all users combined are capped at 5 login attempts/minute, and the "10/min per user" recommend-endpoint limit is actually "10/min total, all users." This is the most urgent item, more severe than the IP-rotation concern (which only matters *after* this is fixed).

### Design decisions

- **Revert-bug fix**: mirror the exact pattern already used by the sibling route `commit_crsp_staging` (`backend/admin_router.py:3369-3384`) — construct the `VehicleYearVersion` row, `db.add()`, then `db.flush()` **before** the loop that adds `VehicleYearChangelog` rows referencing `version_id`, instead of after. Compute `reverted = len(entries)` up front (it's an unconditional per-entry increment, so this is equivalent to counting after the loop). One isolated commit, directly to `main`.

- **Fix the rate-limiter trust boundary first** (not the IP-rotation defense — that only makes sense once per-user attribution actually works). Two parts, both needed together:
  1. Run uvicorn with `--proxy-headers --forwarded-allow-ips="*"` (or the ALB's known CIDR if we want to be strict) in the production start command — this makes uvicorn's built-in `ProxyHeadersMiddleware` rewrite `request.client.host` from `X-Forwarded-For` automatically. Update the production run command in README.md/CLAUDE.md.
  2. No code change needed in `get_remote_address` itself once `request.client.host` is corrected by (1) — slowapi's default key func already just reads that field. Confirm this is genuinely sufficient rather than writing a custom key func (simpler, less to maintain, standard FastAPI/uvicorn pattern).

- **IP-rotation defense-in-depth (excluding AWS WAF)**: since per-IP limiting alone is fundamentally gameable by anyone with a proxy/botnet, add a second, IP-independent layer for the highest-value target (admin login): track failed attempts **by username** in the DB (not in-memory — with 2+ Fargate tasks behind the ALB, in-memory counters would be inconsistent per-task, same class of bug as the pipeline-state issue below). Add `failed_login_attempts` and `locked_until` columns to `AdminUser` (`backend/models.py:163-181`) via migration; lock the account for a short cooldown (e.g. 15 min) after N (e.g. 8) consecutive failures, reset on success. This is a targeted, low-complexity addition — not a general CAPTCHA/behavioral-analysis system, which would be disproportionate for a single-admin-team internal dashboard.

- **CORS**: there is currently no `CORSMiddleware` at all (`backend/app.py` — confirmed absent). Since CloudFront/ALB serves the SPA and API same-origin today, add an explicit `CORSMiddleware` anyway (defense-in-depth + makes the trust boundary explicit rather than implicit-by-topology), with `allow_origins` read from an env var (new `ALLOWED_ORIGINS`, defaulting to the production domain) rather than `"*"`, `allow_credentials=True` (cookies are used), methods/headers restricted to what the app actually uses.

- **Security headers**: add a small middleware in `app.py` (after the existing `GZipMiddleware` registration at `app.py:127`) setting `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` (minimal, deny geolocation/camera/mic/etc.), `Strict-Transport-Security` (only added when `ADMIN_COOKIE_SECURE`/HTTPS is true, reusing the existing `_IS_SECURE` pattern from `admin_auth.py` so local HTTP dev isn't broken), and a pragmatic `Content-Security-Policy` (`default-src 'self'`, plus whatever `img-src`/`connect-src` the built SPA actually needs — verify against the built `frontend/dist` output rather than guessing, since Tailwind v4 output and any data-URI images affect this).

- **CSRF**: not adding a custom token/double-submit scheme. Admin cookies are already `HttpOnly` + `Secure` + `SameSite=Strict` (`admin_auth.py:151-161`), which is the standard, sufficient CSRF defense against cross-site requests in all modern browsers for this app's threat model. Building additional CSRF machinery here would be complexity without meaningful benefit — call this out explicitly in the PR description as a considered-and-declined item, not a gap.

- **Upload size cap**: `POST /api/admin/pipeline/crsp/upload` (`admin_router.py:2772-2784`) has no size limit, unlike the battery upload endpoint which caps at 10MB (`admin_router.py:487-491`). Add the same cap, mirroring that existing pattern exactly.

- **Load balancer**: already exists (ALB, per the confirmed topology) — no infrastructure work needed here. The actionable item *is* the proxy-trust-boundary fix above, since that's what makes the existing ALB actually work correctly with the app's rate limiting/logging.

- **Flagged but explicitly out of scope** (to note in the plan/PR, not fix now, same treatment as the revert bug got last time): the in-memory pipeline-state dicts (`_pipeline_state`, `_crsp_state`, `_expansion_state` in `admin_router.py`) are a real correctness bug under the confirmed multi-task Fargate topology — status polling for a running pipeline can hit a different task than the one running the job and return stale/wrong state. This is a reliability bug, not a security one, and fixing it (would need Redis or a DB-backed job-state table) is a larger, separate effort. Will mention it to the user after this plan lands.

### Implementation

#### Phase 1 — Revert-bug fix (commit directly to `main`)

- `backend/admin_router.py`: in `revert_crsp_version` (~line 3514-3605), move the `VehicleYearVersion(...)` construction + `db.add()` + `db.flush()` to before the `for entry in entries:` loop; compute `reverted = len(entries)` up front; remove the now-redundant post-loop `db.add(VehicleYearVersion(...))` block.
- Verify: exercise the revert endpoint against a real version in local Postgres, confirm no 500 and that `vehicle_years_changelog` rows + the new version row both land correctly.
- Single commit, directly to `main`.

#### Phase 2 — Security hardening (new branch `fix/security-hardening`)

1. Rate-limiter trust boundary: update production uvicorn start command (README.md, CLAUDE.md if it documents the command) to add `--proxy-headers --forwarded-allow-ips=...`; verify locally by simulating an `X-Forwarded-For` header and confirming `request.client.host` reflects it.
2. `AdminUser` migration: add `failed_login_attempts` (int, default 0) and `locked_until` (nullable timestamptz) columns; update `login()` (`admin_router.py:145-163`) to check/increment/reset these; return 429 with a clear message when locked.
3. `CORSMiddleware` in `app.py`, origins from new `ALLOWED_ORIGINS` env var, document it in README's Environment Variables table.
4. Security headers middleware in `app.py`.
5. Upload size cap on the CRSP upload route, mirroring the battery upload's existing 10MB check.
6. Update README as needed for the new `ALLOWED_ORIGINS` var and the proxy-headers flag.

Commit each of the 6 items separately on the feature branch, verifying each before moving to the next (matches the granular-commit convention already used in this repo's recent PRs).

#### Phase 3 — README Security section: document the AWS security layers (doc-only, no code)

README.md's `## Security` section (README.md:1055-1064) currently only lists **application-level** controls (bcrypt, session cookies, slowapi, Pydantic validation) plus one throwaway line — "Geographic access restricted to Kenya (enforced at CDN + WAF layer in production)" — that gestures at the AWS layer without explaining it. Meanwhile the `## Production Architecture` diagram right below it (README.md:1068-1100) already names the actual AWS security-relevant services (CloudFront geo-restriction, ALB + AWS WAF for rate limiting/bot filtering, SSM Parameter Store/Secrets Manager for secrets injection) but the Security section never cross-references or explains *what each one is doing for security*, only the architecture shape.

Task: expand the README Security section to explicitly explain, in plain terms, each AWS technology's security role — not just name-drop the diagram:

- **CloudFront + Route 53**: enforces the Kenya-only geo-restriction at the edge, before traffic ever reaches the app.
- **AWS WAF (on the ALB)**: rate limiting and bot/exploit filtering at the network edge, ahead of and complementary to the app's own `slowapi` limits (once the Phase 2 proxy-header fix lands, call out that app-level limiting is now per-real-client-IP, working *with* WAF rather than being silently defeated by the ALB masking client IPs).
- **ALB (TLS termination)**: HTTPS termination point; backend traffic to Fargate is internal.
- **SSM Parameter Store / Secrets Manager**: how production secrets (DB credentials, API keys) are injected as real env vars at ECS task runtime, never baked into the image or `.env` (cross-reference the existing `load_dotenv(override=False)` explanation under "Local Postgres & Secrets" in this file).
- **RDS + ElastiCache network isolation**: presumably in private subnets/security groups reachable only from ECS tasks — verify this is actually true (check Terraform/CDK/infra-as-code if any exists in the repo, or ask the user) before asserting it in the README; don't write it up from assumption alone.

This is purely a documentation task (edit README.md only) and can be done independently of Phases 1-2, though it reads better done *after* Phase 2 since it should reflect the corrected rate-limiting story.

#### Phase 4 — Geo-restriction scope change: Kenya → Kenya + Uganda + Tanzania

**Requirement (added 2026-07-05):** the geo-block should now allow Kenya, Uganda, and Tanzania, not Kenya only.

**Key fact already discovered:** there is no geo-restriction code in this repo — `backend/app.py` has no country/IP-geolocation check anywhere (confirmed by grep). The block is enforced entirely at the AWS edge (CloudFront geo-restriction allowlist, per README's Production Architecture diagram, README.md:1068-1100). **The actual technical change is an AWS/CloudFront console or IaC config change outside this repo** — add Uganda (UG) and Tanzania (TZ) to CloudFront's geo-restriction allowlist alongside Kenya (KE). Nothing to do in `backend/` or `frontend/` for the block itself.

**What genuinely needs updating in this repo — doc/copy consistency only:**

- Already correct (found while investigating, no change needed): README.md:7 — the intro paragraph already says "geo-restricted to Kenya, Uganda and Tanzania" (pre-existing inconsistency the rest of the repo hadn't caught up to).
- Needs updating: `CLAUDE.md:7` — "geo-restricted to Kenya" → "geo-restricted to Kenya, Uganda and Tanzania".
- Needs updating: `README.md:1064` — Security section bullet "Geographic access restricted to Kenya" → all three countries.
- Needs updating: `README.md:1071` — Production Architecture diagram label "Users (Kenya only — geo-restricted)" → all three countries.
- Needs updating: `README.md:282` — dev note "blocks non-Kenyan IPs... non-KE IP" → mention UG/TZ too.
- Needs updating: Phase 3's new README Security-section prose above (once written) should say "Kenya, Uganda, Tanzania" for the CloudFront bullet, not just Kenya.

**Flag for the user before touching — do not silently change these:**

- `backend/scripts/cleanup_non_kenya_makes.py` filters vehicle makes based on **Kenya-specific** Dial-A-Battery sales data (57,816 Kenyan orders). Expanding *who can reach the app* doesn't change what vehicle/battery data is accurate — Uganda/Tanzania vehicle-make popularity may differ from Kenya's. Leave this script and its data as-is unless the user confirms the underlying CRSP/battery dataset itself should also expand beyond the Kenyan market — that's a data/product scope question, not a copy-cleanup one.
- Frontend legal copy (`TermsGate.tsx`, `CopyrightModal.tsx`, `PrivacyModal.tsx`) states the governing law is "Republic of Kenya," jurisdiction is "Kenyan courts," and cites the **Kenya Data Protection Act, 2019** — these are statements about the corporate entity (Chloride Exide (Kenya) Limited) and its legal jurisdiction, not about who can access the site. Do not change these just because more countries can now reach the app; that would need actual legal review (Uganda/Tanzania have their own data protection laws — Uganda's DPA 2019, Tanzania's Personal Data Protection Act 2022 — that may need separate compliance language if the product is genuinely expanding markets, not just IP access). Surface this as an open question rather than assuming either way.
- `FaqModal.tsx` copy describing the vehicle database as reflecting "the Kenyan market" / "used in Kenya" — same product-scope question as the cleanup script: is this now a genuine multi-country product, or just a wider allowlist while the product/data story stays Kenya-focused? Ask before rewriting user-facing FAQ claims.

### Verification

1. Revert endpoint: create a test CRSP version change, call revert, confirm 200 + correct DB state (no orphaned changelog rows, `committed_count` accurate).
2. Rate limiting: with `--proxy-headers` configured, send requests with different `X-Forwarded-For` values and confirm they're tracked as separate buckets (not all lumped under the ALB's IP).
3. Login lockout: fail login 8x for one username, confirm 429/lockout message, confirm a *different* username is unaffected, confirm it clears after the cooldown or on next success.
4. CORS: `curl -H "Origin: https://evil.example" ...` against `/api/*` and confirm the response does NOT include an `Access-Control-Allow-Origin` header for that origin; confirm the real frontend origin still works.
5. Security headers: `curl -I` the app and confirm CSP/X-Frame-Options/etc. are present; load the actual built SPA in a browser and confirm nothing is broken by the CSP (check browser console for CSP violations).
6. Upload cap: attempt an oversized CRSP upload, confirm a clean 4xx instead of an uncapped disk write.

## PENDING PLAN (added 2026-07-05) — Matcher per-make cache (`backend/matcher.py`)

**Problem:** `recommend()` (`matcher.py:783-793`, itself `@lru_cache(maxsize=512)`) filters `df[df["make_n"] == make_n]` from scratch on every cache-miss call (`matcher.py:815`, `897`, `975`) — a full pandas scan of the entire `vehicle_years` table, even though that table only changes when a pipeline commits. Worse, inside `_fuzzy_model_score_for_year()` (`matcher.py:64-150`), every candidate trim considered by the fuzzy scorers (up to ~80 per scorer call, in `_pick_best`'s loop at `matcher.py:98-127`) does *another* fresh pandas filter (`cand_df[cand_df["year"] == year]` / the ±3-year window) just to check what years that one trim was sold in.

**Fix:** add a small `@lru_cache`'d helper in `matcher.py`, keyed by `make_n`, that precomputes once per make: the filtered DataFrame slice, the unique `model_choices` list, and a `dict[model_n → sorted years]`. Use dict/array lookups instead of repeated pandas boolean masking in both the outer `recommend()` filtering and the inner per-candidate year checks.

**Invalidation is free** — `admin_router.py` already calls `matcher._vehicles.cache_clear()` whenever `vehicle_years` changes (e.g. `admin_router.py:639`); just add `matcher.<new_helper>.cache_clear()` alongside it (same pattern already used for `_batteries`, `_model_aliases`, `_inference`, `recommend`).

## PENDING PLAN (added 2026-07-05) — No automated backend test suite

**Problem:** `Jenkinsfile`'s CI pipeline has a "Test Python (pytest)" stage, but a repo-wide search for `test_*.py` under `backend/` finds no actual pytest test files — only `backend/scripts/test_failure_modes.py`, which per this file's existing "Accuracy scripts" note is a standalone script, not part of the app runtime or a pytest suite. The CI stage is almost certainly collecting zero tests today (passes trivially, proves nothing).

**Why this matters concretely:** during this session, two real production bugs were found in `admin_router.py` purely by manual code reading — the revert-endpoint FK-violation bug (missing `db.flush()` before a child row referenced a not-yet-persisted parent id) and the cancel-loses-partial-results bug in the expansion pipeline. Both are exactly the class of bug a basic test suite (unit tests around `matcher.py`'s fuzzy-matching/scoring logic, integration tests around `admin_router.py`'s pipeline run/pause/resume/cancel and CRUD routes against a real test Postgres) would have caught mechanically instead of requiring a manual read-through.

**Fix:** stand up an actual `backend/tests/` pytest suite (using the existing local Docker Postgres — `docker-compose.yml` — as the test DB, consistent with how this repo already treats that as the source of truth for schema behavior). Prioritize: (1) `matcher.py`'s three-layer matching + fuzzy scoring/tie-break logic (pure functions, easy to unit test with small fixture DataFrames), (2) the pipeline run/pause/resume/cancel lifecycle in `admin_router.py` (integration-style, since that's where both real bugs lived), (3) CRUD routes' edge cases (409 on duplicate, 404 on missing, partial-update `exclude_unset` behavior).

**Not urgent to decide now:** whether to also add a CI gate that fails the build if test count is 0 (to prevent this silent-no-op-stage problem from recurring) — worth doing once real tests exist.

## PENDING PLAN (added 2026-07-05) — Public, unauthenticated health/readiness endpoint

**Problem:** the only health-check route in the app is `GET /api/admin/health` (`admin_router.py:246-247`), gated behind `Depends(require_admin)`. There is no public `/health` (or similar) route in `backend/app.py` at all (confirmed by grep). If ECS/ALB's target-group health check is configured to hit any API path expecting a 200, hitting an admin-gated route would always return 401 — the load balancer would conclude the task is unhealthy and pull it out of rotation (or keep recycling tasks) even when the app is running fine. **This needs to be verified against the actual ALB target-group health-check path configuration (not in this repo — ask the user or check the AWS console/IaC) before assuming it's actually broken in production; today it might simply be pointed at `/` (which the static-file mount would serve as a 200) rather than at anything under `/api/`.**

**Fix (once confirmed necessary):** add a lightweight `GET /health` (or `/healthz`) route in `backend/app.py`, no auth required, that returns 200 with a minimal payload — optionally checking DB connectivity (reusing the same pattern as `admin_router.py:246-283`'s `engine.connect()` + `SELECT 1` check) so a genuinely broken DB connection still fails the check, but without requiring admin credentials. Point the ALB target group at this new path once it exists.

**Safety constraints for this route (since it's the one unauthenticated door touching the DB):**

- **Minimal response body only** — return just `{"status": "ok"}` / `{"status": "down"}`, never the rich diagnostics (`latency_ms`, `pool_size`, `pool_checked_out`, `pool_usage_pct`) that `/api/admin/health` returns. Anonymous callers shouldn't get a free window into live DB load/timing; keep the detailed numbers exclusively behind the admin-gated route as today.
- **Rate-limit it like every other route in this app** — this app rate-limits everything (10/min recommend, 5/min feedback, etc., per this file's Architecture section), so the one public route that touches the database shouldn't be the sole exception. Add a generous `slowapi` limit (e.g. 60/min — comfortably above what a legitimate load balancer check needs) rather than leaving it unlimited.

**Don't forget:** once implemented, update the README `## Performance` section (README.md:970 onward, the "LRU In-memory matcher cache" subsection at README.md:976-978) to document this new per-make cache layer alongside the existing ones — that section is where this class of optimization is expected to be documented.

**Simple version of the problem (for context/copy reuse):** today, every search re-reads the *entire* vehicle-years phone book to find "all the Toyotas," even though the Toyota section hasn't moved since last time; the fix is to write that section down once (as an in-memory dict) and only redo it when the underlying data actually changes.

## PENDING PLAN (added 2026-07-05) — Aggregate connection-pool usage across all ECS tasks

**Problem:** the "Database Health" card on the admin dashboard (`frontend/src/pages/admin/AdminDashboard.tsx:265-298`, fed by `GET /api/admin/health`, `admin_router.py:246-283`) shows `engine.pool.checkedout()` / `engine.pool.size()` — but that's a Python in-process object. With production running 2+ ECS Fargate tasks behind the ALB, each task has its own separate SQLAlchemy `engine` and therefore its own separate pool; whichever task happens to answer a given `/api/admin/health` request only knows about *its own* connections, not the combined total across all tasks actually open against RDS. So today's card under-reports true load on the database — e.g. 3 tasks each showing "6/25 (24%)" looks fine individually, but the real total hitting RDS is 18 connections, and there's no way to see that combined number from the current UI.

**Fix — query Postgres itself for ground truth, not each task's self-reported count:** rather than trying to have every task report its pool stats somewhere and sum them (which needs a coordination layer), query Postgres's own system view directly — `SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()` — from within the existing `/api/admin/health` handler. This returns the actual total number of open connections to this database from every source (every task, migrations, psql, anything), independent of which task happens to serve the request. Compare it against the database's real `max_connections` (queryable via `SHOW max_connections` or `SELECT setting FROM pg_settings WHERE name = 'max_connections'`) to get a true usage percentage, and keep the existing per-task `pool_size`/`pool_checked_out` numbers alongside it as a secondary "this task's share" stat rather than replacing them.

**Why this approach over Redis-based aggregation:** ElastiCache Redis is provisioned but unused elsewhere in this app (see the earlier "no automated test suite" / cache-usage findings this session) and could technically work as a shared counter, but it adds a coordination dependency (every task must remember to report in) for a number Postgres already tracks natively and exposes for free via `pg_stat_activity` — simpler and can't drift out of sync with reality.

**Frontend change:** update `HealthCard` (`AdminDashboard.tsx:266-298`) to show both numbers — the new cluster-wide total (`pg_stat_activity` count / `max_connections`) as the primary bar, and the existing per-task pool stat as a smaller secondary line (e.g. "this instance: 6/25").
