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
# Set ADMIN_BOOTSTRAP_TOKEN in .env, start the app, then visit /admin/setup to
# create the first admin (no CLI script — see README "Create First Admin User")
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
- `components/VehicleFinderForm.tsx` — main search form AND result card; the battery recommendation result is rendered as an inline sub-component inside this file (look for `className="result-card"`). Uses **inline `style={{}}` props throughout** — always extend with inline styles, not Tailwind utility classes.
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

## DONE (2026-07-13) — Matcher per-make cache (`backend/matcher.py`)

`matcher._make_index()` precomputes, once per make (`@lru_cache(maxsize=128)`), the make-scoped row slice and a `model_n → sorted years` map, replacing the repeated `df[df["make_n"] == make_n]` full-table pandas scans in `recommend()` and the per-candidate pandas year-filtering inside `_fuzzy_model_score_for_year()`'s `_pick_best` loop and the JDM-alias resolution loop. Cleared alongside `_vehicles()` in the admin `/cache/refresh` action. Verified behavior-preserving via a differential test against the pre-refactor version across 17 synthetic cases.

## DONE (2026-07-13) — No automated backend test suite

`backend/tests/` now has a real pytest suite (conftest.py wires a minimal FastAPI app around `admin_router`'s routes against the real local Docker Postgres, each test wrapped in a rolled-back transaction): unit tests for `matcher.py`'s normalisation/Ah/tech rules/matching layers, integration tests for battery CRUD edge cases, CRSP staging pipeline commit/discard/revert lifecycle, and the health endpoints. Jenkinsfile now actually runs and reports on it (`--junitxml`) instead of silently swallowing failures. Writing these tests caught and fixed two real bugs: a soft-deleted `battery_code` reuse 500 (`admin_router.py`), and a `VehicleYearStaging.is_valid`/`conflict` model/schema type mismatch that made `GET /pipeline/crsp/staging?filter=conflicts|new` 500 in production.

## DONE (2026-07-13) — Public, unauthenticated health/readiness endpoint

`GET /health` now exists in `backend/app.py`, unauthenticated, rate-limited at 60/min, returning only `{"status": "ok"/"down"}` after a real `SELECT 1` — the rich diagnostics stay behind the admin-gated `GET /api/admin/health`. Also exempted from the maintenance-mode middleware's 503 override. **Still needs verification against the actual ALB target-group health-check path** (AWS console/IaC, outside this repo) — point it at `/health` if it isn't already.

## DONE (2026-07-13) — Aggregate connection-pool usage across all ECS tasks

`GET /api/admin/health` now also queries `pg_stat_activity`/`pg_settings` directly for the cluster-wide connection count and `max_connections`, independent of which ECS task answers the request — ground truth from Postgres itself rather than each task's own in-process `engine.pool` (which only ever knew its own share). The admin dashboard's `HealthCard` shows the cluster-wide number as the primary bar and the existing per-task pool stat as a secondary "this instance" line underneath.

## Anti-Scraping Hardening for Public API Endpoints

**Problem:** nothing app-level deters someone from scripting `/api/makes` → `/api/models/{make}` → `/api/years` → `/api/recommend` to enumerate and rebuild the entire CRSP-derived vehicle→battery matching dataset. The only defense today is a per-IP `slowapi` rate limit, and `slowapi`'s default in-memory storage means each of the 2+ Fargate tasks behind the ALB keeps its own separate counter, so per-IP limits are effectively multiplied by however many tasks a scraper's requests land on (README documents this honestly).

**Done (2026-07-13):** the 429 handler for rate-limit violations was fully written but never registered — exceeding a limit returned a raw unhandled-exception 500 instead of a clean 429. Fixed by adding `@app.exception_handler(RateLimitExceeded)` above `rate_limit_handler` in `app.py` (commit `56e4f25`, direct to `main` — small isolated fix, same treatment as the revert-bug fix). This covers both `Limiter` instances (`app.py`, `admin_router.py`) since it's one shared exception class.

**Declined (2026-07-13), REOPENED (2026-07-15) — Redis-backed storage + daily caps:** wiring both `Limiter` instances to the provisioned-but-unused ElastiCache Redis (`storage_uri=REDIS_URL`) and adding daily caps on top of the per-minute limits was originally rejected as overengineering, reasoning that "a niche regional lookup tool isn't a high-value target for a resourced attacker." **That framing was wrong and is retracted.** The actual risk isn't a resourced/anonymous internet-wide attacker — it's a local competitor in the Kenya/Uganda/Tanzania battery retail market with an ordinary reason to script `/api/makes` → `/api/models/{make}` → `/api/years` → `/api/recommend` and rebuild this CRSP-derived vehicle→battery matching dataset for their own use, shortcutting the actual data-cleaning work this project represents. That doesn't take a sophisticated adversary, just a local business with a developer, so "not worth a resourced attacker's time" was never the right bar. The technical objection to daily caps (leaky without Redis — multiplied across tasks, reset on every deploy) is also gone now that Redis is already provisioned and just needs to be wired up. **Action:** build Redis-backed daily/cumulative per-IP caps on top of the existing per-minute limits, using the already-provisioned ElastiCache instance (`storage_uri=REDIS_URL` on both `Limiter`s, plus a separate daily counter with a 24h TTL). Not yet implemented — this entry records the decision reversal, not completed work.

**Also worth building — enumeration-pattern detection:** a per-minute or even per-day rate limit only catches *speed*, not *breadth*. A scraper pacing itself under any per-minute cap can still walk the entire make→model→year→recommend tree over hours or days without ever tripping a speed-based limit. Redis makes it cheap to track distinct make/model combinations queried per IP in a rolling window and flag/throttle IPs that look like systematic dataset enumeration rather than a real shopper looking up one vehicle — a different signal than anything WAF or per-minute `slowapi` limits provide today. Not yet designed in detail; flagged as the next thing to scope once the Redis wiring above lands.

**Explicitly deferred (considered, not building now):** a per-browser-session budget independent of IP (server-issued cookie + DB-backed daily counter, mirroring `ApiUsageQuota`'s shape) was designed in detail but declined as disproportionate — this one's reasoning (WAF already exists as the outer layer) still holds and is unaffected by the reopening above; revisit only alongside the Redis-backed IP daily cap if that turns out to be insufficient.

**Recommended — reCAPTCHA (elevated 2026-07-15 from "worth reconsidering" to recommended, still not implemented):** unlike a visible CAPTCHA (which breaks the app's frictionless no-login search flow and was rightly declined), invisible reCAPTCHA v3 — scored quietly in the background, no user-facing challenge — would raise the bar significantly beyond the per-IP measures above: a scraper would need to either pay a CAPTCHA-solving service or run full human-mimicking browser automation, not just rotate IPs or pace requests. Scoped narrowly to `POST /api/recommend` only (the endpoint that actually returns the valuable data), not the lightweight dropdown-population endpoints. The real cost: it's a third-party (Google) dependency that sends visitor behavioral/IP data off our infrastructure, which directly contradicts the current Privacy Policy's explicit claim — *"This application does not integrate any third-party advertising networks, social media tracking pixels, or external analytics platforms. All data remains within Chloride Exide Kenya's own infrastructure"* (`frontend/src/components/PrivacyModal.tsx:82`). Implementing this requires rewriting that section as part of the same piece of work, not just appending a bullet. Given the revised risk assessment above (a real, regionally-motivated competitor, not a hypothetical resourced attacker), this now leans firmly toward yes — treat as the second priority after the Redis-backed daily caps, not an optional nice-to-have.

## DONE (2026-07-20, branch `fix/spa-fallback-path-traversal`) — Path traversal in SPA fallback route (arbitrary file read, unauthenticated)

**Found via:** a routine "can an attacker view our backend code" question prompted inspection of `backend/app.py`'s catch-all SPA route.

`spa_fallback()` (`backend/app.py`, the `@app.get("/{full_path:path}")` handler) joined the untrusted `full_path` URL segment directly onto `_frontend_dir` with `os.path.join()` and served whatever existed there, with no check that the result stayed inside `_frontend_dir` — unlike the `static/` branch a few lines above it in the same function, which already did the normalize-and-contain check correctly. A literal `../` in a URL gets collapsed client-side before the request is sent, but URL-encoding the slashes (`%2f`) survives, since Starlette does not decode-and-normalize `..` segments before dispatching to the handler.

**Confirmed live, not just by inspection:** ran the dev server locally and requested `GET /..%2f..%2fbackend%2fapp.py` and `GET /..%2f..%2f.env` — both returned HTTP 200 with the real file contents, including `.env`'s `DATABASE_URL`, `TAVILY_API_KEY`, and `BRAVE_SEARCH_API_KEY`. Fully unauthenticated — no admin session or any credential needed. Test server was killed and the scratch files holding the captured secrets were deleted immediately after confirming.

**Fix:** `file_path` is now `os.path.normpath()`'d after the join, checked with `.startswith(frontend_root)` (root suffixed with `os.sep` to close the sibling-directory edge case, e.g. `frontend/dist` vs `frontend/dist-evil`) before being trusted — the same pattern the `static/` branch already used, now applied consistently to both branches. Re-verified against a live server post-fix: both traversal payloads now fall through to `index.html` as intended, and normal requests (root page, real static assets) are unaffected.

**Also checked while in there (broader sweep, all clean, see below for the one exception):** every other `os.path.join()` call in `backend/` involving external input; SQL construction across `app.py`/`admin_router.py`/pipelines (f-strings only splice in hardcoded table/column names, all values go through bind params); `eval`/`exec`/`subprocess`/`os.system`/`pickle` (none present anywhere in the codebase); auth coverage on all 84 `admin_router.py` routes (scripted check — every route requires `require_admin` except `/login`/`/logout`, which correctly must be public); CORS config (explicit `ALLOWED_ORIGINS` allowlist, no wildcard); debug-mode traceback leakage (`FastAPI()` not instantiated with `debug=True`, so unhandled exceptions return a generic 500, not a stack trace).

**Not fixed, flagged as a lower-severity follow-up:** `admin_router.py`'s `/pipeline/crsp/validate` endpoint and one edit endpoint (~line 3009, 3089) accept an arbitrary `file_path` string in the request body and `pd.read_excel()` it directly, with no check that it resolves inside the CRSP uploads directory. Same "trust a path from the request" shape as the bug above, but admin-only (`require_admin`) and constrained to `.xlsx`/`.xls` suffixes, so severity is much lower — an already-trusted admin, not an anonymous caller. Worth the same normalize+contain treatment eventually, not urgent.

## DONE (2026-07-21, branch `feature/admin-account-self-service`) — Admin account bootstrap, forgot/reset password, Admin Users management page; `create_admin.py` removed

**Why:** the only way to create an admin account was the standalone `scripts/create_admin.py` CLI, requiring direct server/DB access for every admin change — no forgot-password flow existed at all, and no way to see who has admin access from the UI.

**First-admin bootstrap:** `GET /api/admin/bootstrap/status` + `POST /api/admin/bootstrap` (new public `/admin/setup` page) replace the CLI for the very first admin. Gated by both an empty `admin_users` table (checked first, so a populated table is never usable as a token-guessing oracle) and a shared-secret `ADMIN_BOOTSTRAP_TOKEN` env var (SSM in production) — once any admin exists the endpoint permanently 403s regardless of token. Every admin after the first is created from the dashboard (`POST /api/admin/users`, `require_admin`-gated) — no token needed there, since being logged in is the gate.

**Found and fixed a real race condition while writing the concurrency test:** "check `admin_users` count, then insert" is not atomic under Postgres's default READ COMMITTED isolation. 8 concurrent bootstrap requests with distinct usernames produced 3 successful admin creations, not 1 — concurrent transactions can all observe `count()==0` before any of them commits, and since the usernames differ the unique constraint doesn't catch it. Fixed with `pg_advisory_xact_lock` in `bootstrap()` serializing all bootstrap attempts against each other.

**Forgot/reset password — both mechanisms built, per explicit decision:** (a) an admin-generated reset link (`POST /api/admin/users/{id}/reset-link`, an already-logged-in admin generates a link for a locked-out colleague and shares it manually — no email infra needed, works today) and (b) real email delivery via a new `backend/email_utils.py` wrapping AWS SES (`SES_FROM_EMAIL`/`SES_REGION` env vars, `boto3` added to requirements.txt). SES needs domain verification done in AWS outside this repo before it can actually send in production — `send_reset_email()` no-ops with a logged warning until `SES_FROM_EMAIL` is set, so mechanism (a) keeps working regardless. Reset tokens are SHA-256 hashed (not bcrypt — high-entropy CSPRNG tokens don't need bcrypt's slow-by-design property; documented inline so it doesn't get "fixed" into bcrypt later), single-use, overwrite-on-reissue, and a successful reset invalidates every existing session for that admin (`invalidate_all_sessions`).

**Admin Users management page** (`/admin/users`, new sidebar entry): list all admins, add/delete, generate a reset link, self-only email editing (an admin editing *another* admin's email would let them redirect that admin's password-reset destination — a real privilege-escalation path, so `PATCH /api/admin/users/{id}` 403s unless `id == self`). Delete blocks self-delete and blocks deleting the last remaining admin (the latter is fully subsumed by the former in practice — if you're the only admin, you're the only session that could attempt it — kept anyway as cheap defense-in-depth).

**Audit trail:** new `admin_account_audit_log` table (mirrors `BatteryAuditLog`'s precedent) logs bootstrap/create/delete/reset-link-generated/password-reset, with `actor_username`/`target_username` stored as snapshots (not just FKs) so entries stay readable after either account is deleted — surfaced as an Activity section on the Admin Users page.

**Verification:** 22 new backend pytest tests (`test_admin_account_management.py`, full suite 84/84 green) plus manual end-to-end runs against real dev servers through the actual Vite proxy (not just type-check/build) for both the public auth pages and the full Admin Users CRUD flow, confirming the dev DB was left clean afterward each time.

`scripts/create_admin.py` deleted; README/CLAUDE.md/AWS-MIGRATION-PLAN.md/TECHNICAL_DOCUMENTATION.md updated to match.

## DONE (landed 2026-07-21, PR #128 `feature/least-privilege-public-db-role`) — Least-privilege public DB role

Public/unauthenticated traffic used to share the same full-privilege Postgres role as admin routes and pipelines — enforced only by application-code discipline, not by the database itself. Fixed with two Postgres roles / two SQLAlchemy engines: `db.py` now exposes `public_engine`/`PublicSessionLocal` (bound to a new restricted `batteryfinder_public` role, created by migration `20260721_c4d5e6f7a8b9` with exactly the grants scoped to matcher's 7 read sources + `app_settings`/`test_users`, and `INSERT`/narrow `UPDATE` on `search_events`/`user_feedback`/`test_users`/`test_user_sessions`/`admin_stats`) alongside the existing full-privilege `engine`/`SessionLocal`. `matcher.py`'s data loaders, and every public-route write site in `app.py` (read-counter flush/reset, search-event logging, feedback submission, test-user register/login) plus `app_state.py`'s maintenance-mode read, now go through the restricted role; `admin_router.py`/`admin_auth.py`/pipelines/scripts are untouched. `tests/conftest.py` has a `public_db_session` fixture so tests exercising these paths stay inside the rolled-back test transaction instead of leaking rows through the separate role's connection. **Still open:** the production-side piece (new SSM parameter + ECS task-definition env var for `PUBLIC_DATABASE_URL`) — same situation as the CloudFront geo-restriction precedent, needs coordination outside this repo.

## DONE (landed 2026-07-21/22, PR #129 `fix/web-validate-staging-and-quota-race`) — N+1 query patterns + quota race condition

All three N+1 findings from the original audit are fixed, plus a bonus: a genuine quota check-then-act race condition found while working the fix.

- **Quota N+1 (was 10,000+ DB round-trips per pipeline run):** `web_battery_validate.py` gained an in-memory quota cache, wired into both Phase 1 (web-search) and Phase 2 (carquery) quota checks, with a final flush in `main()` — the same `rows_buffer`/`_flush_rows` pattern the file already used elsewhere, now applied to quota bookkeeping too.
- **`admin_router.py` staging endpoints:** `_populate_staging()`, `staging_pre_commit()`, and `commit_staging()` all got the bulk-load-existing-keys treatment (mirroring `commit_crsp_staging()`'s pre-existing pattern); `web_battery_validation_changelog` inserts got batched in `commit_staging()`, and `revert_version()` was updated to reuse that same batched-changelog helper.
- **`revert_crsp_version()`:** fixed with a bulk `tuple_()`-keyed `IN` query replacing the one-SELECT-per-changelog-row loop.
- **Bonus fix:** the quota check-then-act race (concurrent transactions could all observe quota not yet exhausted before any of them committed) fixed with an atomic reserve.

Regression tests added (`test_web_validate_staging_and_quota.py`, staging lifecycle + quota race). **Still open, lower priority (as originally scoped):** batching `enrich_years.py`'s `write_to_staging()` and `web_battery_validate.py`'s `_upsert_rows()` per-row INSERT/UPSERT calls into single multi-row statements — capped blast radius (chunks of ≤50), not yet scoped in detail.

## DONE (2026-07-28, branch `fix/web-validate-region-resolution`) — Web Validation region-resolution bug (DIN/NS mix-up) + on-demand admin backup feature

**Bug fix:** `_resolve_battery_code()` (`backend/pipelines/web_battery_validate.py`) no longer trusts `parsed.get("region")` (a scraped "NS"/"DIN" keyword hit) — it always uses `_make_region(make_n)`, the vehicle's own known region, matching what `recommend()` already independently recomputes at request time. `parsed["region"]` was confirmed unused anywhere else (grep), so `_parse_snippets()`'s return shape is untouched.

**Admin panel backup feature (built in full, per explicit decision — not deferred to the local-script-only stopgap):** new `/admin/backups` page + `POST/GET /api/admin/backup`, `GET /api/admin/backup/log`, `GET /api/admin/backup/{filename}/download` routes, backed by `backend/db_backup.py` (mirrors `db-backup-script/backup-db.ps1`'s `docker exec pg_dump`/retention steps as a callable Python module) and a new `admin_backup_log` audit table (migration `20260728_4b7e9c2a1f83`). Download uses the same normalize-and-contain path-traversal guard as the SPA fallback fix. **Local Docker only** — no RDS-compatible path yet for production (would need a direct `pg_dump`/`psql` connection or an RDS snapshot API call), same open item the original plan flagged.

**Data cleanup, run against the local dev DB:** queried both directions of the mismatch — 490 NS-region-make rows in `web_battery_validation` held a DIN-coded `battery_code` (Chery Tiggo, Daihatsu Hijet Caddie/Truck, Toyota Harrier/Hilux, etc. — grew from the original ~391 as more pipeline runs happened between 2026-07-18 and 2026-07-28); the symmetric DIN-make/NS-coded case came back **clean (0 rows)**, so the bug was one-directional in practice. `backend/scripts/fix_web_validate_region_mismatch.py` (dry-run by default, `--execute` to apply) took a real backup first (`batteryfinderdev_20260728_080950.dump`, logged to `admin_backup_log`), then re-resolved all 490 rows' `battery_code` using their existing `ah`/`technology` through the now-fixed `_resolve_battery_code()`. Verified 0 mismatches remain in either direction post-fix.

**Tests:** `test_web_validate_region_resolution.py` (3 tests, both directions + region-absent case) and `test_admin_backup.py` (7 tests: success/failure audit logging, list/log ordering, download's traversal rejection + valid-file streaming, require_admin gating). Full backend suite green apart from the same 18 pre-existing `test_admin_account_management.py` bootstrap/reset-password failures that already fail on `main` (caused by the shared local dev DB no longer having an empty `admin_users` table — unrelated to this work).

## PLAN (scoped 2026-08-03, not yet implemented) — Year-data remediation + Japanese Wikipedia parser

**Trigger:** client review of the exported "Web Validated Fitments" / "OEM Fitment Guide" spreadsheet flagged (a) implausible year ranges (a Land Cruiser 200-series listed from 1951), (b) the `technology` column disagreeing with the recommended battery, (c) missing makes (Mercedes).

**MEASUREMENT CAVEAT — the local dev DB was 4 migrations behind when these numbers were taken.** DB was at `a3b4c5d6e7f8` (20260718); repo head is `20260728_4b7e9c2a1f83`. Consequences: `admin_backup_log` absent, `oem_fitment` empty, `vehicle_years_exide` empty (it became a *view* in `20260722_3278f8c1b881`), and the DIN/NS `battery_code` cleanup from commit `9bd9069` had **not** been applied to this DB. **Run `alembic upgrade head` and re-measure before acting on any figure below.** The `vehicle_years` findings are unaffected by those migrations; the `web_battery_validation` ones are suspect.

### Findings — year data quality (`vehicle_years`, 58,079 rows / 3,069 variants / 46 makes)

- **1,065 variants (35%) across 35 makes start implausibly early** (`min(year) < 1990`), producing **12,987 phantom year rows** (22% of the table). A further 119 variants start post-1990 but span >25 years; 337 span 16-25 years. Only 1,548 look plausible — and "plausible" only means *not obviously wrong*, since provenance is missing (below).
- **Split by severity** (this drives the repair strategy):
  - **673 (63%) extend to 2020+** — correct years present, phantom early years attached. *Over-inclusion; fixable by clipping to a credible nameplate envelope, no per-trim research needed.*
  - **237 (22%) end before 2000** — range sits entirely in the wrong era, correct years absent. *Needs real research; collapses to 72 nameplates across 21 makes (Isuzu 47, Toyota 32, Mazda 31, Fuso 19, Nissan 19).*
  - 155 (15%) partial.
- **The 1,065 collapse to 179 nameplates** (552 for the whole table). Year ranges are a property of the generation, not the trim, so all repair work should be keyed on nameplate, not variant — a 17x reduction.
- **Provenance is absent:** `vehicle_years.source` is NULL on 56,880 of 58,079 rows (98%), all written in one bulk load on 2026-06-01. Only 720 rows are tagged `fueleconomy`, 479 `Wikipedia`. **This is why the 1984 cluster could not be attributed to a source** — do not assert a cause for it without re-running with provenance recorded.

### Root causes in `backend/pipelines/enrich_years.py`

1. **`MATCH_SCORE_THRESHOLD = 45` (line 46) is far too permissive for `token_set_ratio`.** Verified live against the real `fueleconomy_vehicles` table: CRSP `RENAULT LUTECIA GT LINE` → truncated to `LUTECIA GT` → matched EPA's **`GTA` at 46.15**, accepted by 1.15 points, yielding 1987. EPA's Renault catalogue is 10 models, all 1984-87 American Renaults; no Lutecia exists in it. Stored value is 1984-2025 (42 rows).
   - **The threshold was deliberately lowered** because CRSP model strings carry full trim detail (`3 SERIES 320D X DRIVE M-SPORT HI-LINE PACKAGE`) while external DBs list plain names, so strict matching produced too many misses. It was compensating for a *normalisation* problem with the wrong lever.
2. **`extract_base_model()` (line 473) truncates to the first 2 tokens**, discarding the generation marker — `LAND CRUISER 250 VX` → `LAND CRUISER`.
3. **`get_years_from_wikidata()` (lines 335-338) applies no lower year bound**, while `_parse_wiki_years()` clamps at `1960` (line 196). Its SPARQL uses `FILTER(CONTAINS(...))` + `LIMIT 1`, returning the *nameplate* entity ("Toyota Land Cruiser", inception 1951) over the generation. **This is the 1951 Land Cruiser.**
4. **Open-ended spans default to `CURRENT_YEAR`** (lines 588/599/608/617) — 243 variants run to 2026 including discontinued models.
5. **Amplifier:** `list(range(yf, yt + 1))` expands a span into one row per year, so one bad lookup becomes dozens of rows.
6. **Structural:** fueleconomy.gov (US EPA) is tried *first* (line 566) but is US-market only — Renault left the US in 1987, Suzuki in 2013. For much of the Kenyan fleet the highest-priority source can only miss or mislead. `LAND CRUISER` scores 32 against `RAV4 EV`; no normalisation fixes a source that lacks the vehicle.

### Findings — `web_battery_validation` (22,875 rows, 29 makes, last run 2026-07-10) — RE-VERIFY POST-MIGRATION

- **`technology` disagrees with `battery_code` on ~40% of rows**: AGM 8,397/11,781 (71%), EFB 500/792 (63%), MF 58/10,302 (0.6%). The two are populated independently — `technology` from `_parse_snippets()` scanning search text, `battery_code` from catalogue resolution — with nothing reconciling them.
- **The matcher never reads that column.** `_web_validation()` selects it (`matcher.py:620`) but nothing consumes it; `recommend()` parses `battery_code` for Ah + tech (`matcher.py:1069`). The contradiction is a reporting artifact, not a recommendation defect. **Fix = populate the export from the resolved battery, or drop the column.**
- **17 of 46 makes have no coverage at all** (Mitsubishi 2,234 vehicle rows, Renault 1,713, Mercedes 1,515, Porsche 1,114, Lexus 654, Mini 506, Scania, Bentley, UD, Vauxhall, MAN, Tata, Rolls-Royce, Fuso, SAIC, Dongfeng). Coverage is built incrementally across runs (4 runs: 20 makes, then +17), so this is unfinished processing rather than a defect.
- **`MERCEDES` (1,515 rows) and `MERCEDES-BENZ` (12) are separate makes** in `vehicle_years` — make-normalisation bug.
- 391 DIN-coded `battery_code` rows on NS-region makes — **almost certainly stale**, see caveat above.

### THE PARSER TO BUILD — Japanese Wikipedia year enrichment

**Why:** solves the source-coverage problem that no threshold or normalisation change can. `ja.wikipedia.org` publishes a structured table *per generation* with exact production periods and manufacturer chassis codes. Free, unmetered, and reachable through the same MediaWiki API already wired up for English.

**Verified working (2026-08-03, live calls):**
- **Name resolution needs no translation.** `en.wikipedia` search → `prop=langlinks&lllang=ja` → `ja` title. 7/7 on our model names, including `Renault Lutecia` → en `Renault Clio` → `ルノー・クリオ` (en.wikipedia resolves the JDM badge itself).
- **Generation data is present and structured.** Section headings carry generation + chassis code + years — `初代 DW系（1996年 - 2002年）`, `2代目 DY系（2002年 - 2007年）`, `3代目 DE系（2007年 - 2014年）`, `4代目 DJ系（2014年 - 2019年）` (Mazda Demio). Infoboxes carry `販売期間` fields per generation (Daihatsu Hijet: 12).
- **Coverage sample: 12/12 affected nameplates resolved** with >=3 generation ranges each (Hijet 30, Land Cruiser 32, Crown 29, Bongo 23, Golf 23, Minicab 17, Sambar 11, Hiace 10, Delica 7, E-Class 7, Caravan 5, Dutro 3). **Includes European makes** — ja.wikipedia documents Golf and E-Class to the same standard.
- **Concrete win:** `DEMIO XD TOURING L PACKAGE` is stored as 2002-2022 (21 rows). `XD` is Mazda's diesel badge, introduced with the DJ generation → true range 2014-2019.

**What the parser must handle:**
1. `prop=wikitext`, **not `prop=extracts`** — the current code pulls only the lead paragraph, which is nameplate-level summary and is exactly why it returns 1951. Generation tables live further down the article.
2. Two extraction shapes, both needed — some articles have one and not the other. Isuzu Elf: 11 generation headings, 0 `販売期間`. Land Cruiser: 8 `販売期間`, 0 matching headings.
   - Generation headings: `初代`/`N代目` + optional chassis code + `（YYYY年 - YYYY年）`
   - Infobox `販売期間` fields, incl. multi-value forms (`トラック：1964年4月-1968年4月<br/>バン：...`)
3. Japanese date notation (`1996年8月`), en-dash/hyphen variants, open-ended (`1951年 -`), and the **imperial era calendar** (昭和/平成/令和) where used.
4. Chassis codes (`DW系`, `DY系`, `X57`, `ABA-RH5F1`) as generation identifiers.
5. **Trim → generation mapping is the unsolved part.** Hijet returns 30 ranges; nothing says which one `HIJET TRUCK` is. Proposed approach: search each generation's *section body* for the grade string (`XD`, `15S`) — same article, no extra source. Won't resolve everything; residue goes to the manual nameplate pass.
6. **Rate limiting is mandatory and its failure mode is dangerous.** A 0.35 s delay got 12 consecutive lookups throttled, returning HTML instead of JSON — which, with a bare `except`, looks identical to "no data". 1.0 s spacing worked cleanly (~30 min for a full 552-nameplate run at 3 calls each). **A throttled response must never be recorded as a miss** — that is precisely how bad data entered this table.

**Source priority after this lands:** ja.wikipedia (Japanese makes, free) → en.wikipedia with its bound fixed (Western makes, free) → Brave/DuckDuckGo for the residue → **drop Wikidata entirely** (it is the one actively producing bad values, and is superseded).

**Brave quota reality:** `api_usage_quota` shows brave at 5,652/6,000 used, `period_end = NULL` — a prepaid balance in `_ONE_TIME_QUOTA_PROVIDERS` that **never auto-resets**. 346 calls remain (2 spent testing on 2026-08-03). Query at nameplate level (179 affected / 552 total), never per-variant. DuckDuckGo is unmetered (`quota_limit = -1`, 58,452 calls in June) and should carry the bulk; `searxng` is configured and completely unused.

### Task list

1. `alembic upgrade head` on the local dev DB, then **re-measure every figure above**.
2. ~~Build the ja.wikipedia parser per the spec above; validate on a hand-labelled sample **before** any bulk run — an earlier attempt at stricter matching is what caused the coverage shortfall that led to threshold 45, so prove it delivers accuracy *and* coverage first.~~ **DONE 2026-08-05** — see below.
3. Fix the four `enrich_years.py` defects (threshold, truncation, Wikidata bound, open-ended end date). Raising the threshold alone converts false positives into misses — normalisation and source selection are the actual levers.
4. Re-run enrichment for **all 3,069 variants** into `vehicle_years_staging`, diff against live before commit. Re-running everything (not just the visibly broken 1,065) is what surfaces the tier-4 errors that look plausible but aren't.
5. Populate `vehicle_years.source` **and a match score** on every row going forward.
6. Add staging-gate validation: reject `year_from` below a floor, spans >25 years, and ranges whose start equals a source's dataset floor exactly. The staging review step exists but enforces nothing automatically.
7. Human-set ranges for the residue at **nameplate level**, prioritised by production `search_events` volume.
8. Fix the `web_battery_validation` export's `technology` column (populate from resolved battery, or remove).
9. Finish web-validation coverage for the 17 outstanding makes; fix the `MERCEDES`/`MERCEDES-BENZ` split.
10. Take a DB backup before any bulk mutation — `vehicle_years_changelog` / `vehicle_years_versions` / `revert_crsp_version()` give a rollback path, but back up regardless.

### Open decision

For nameplates no source resolves and nobody can date confidently: leave them without years (they disappear from the year dropdown — accurate, lower coverage) or assign a conservative recent window (findable, but a guess). Affects how much of the residue needs human attention. **Not yet decided.**

## DONE (2026-08-05, 9 commits on `main`) — Japanese Wikipedia year-enrichment parser (task list item 2) + wired into `enrich_years.py` (item 3's scope, minus the 4 pre-existing defects)

Built and live-verified against real ja.wikipedia data (not assumed from the single idealized heading example above — see corrections below), then wired directly into `enrich_years.py`'s source chain per an explicit decision to not defer that step. Commits: `0090a4b` (shared `pipelines/model_name_utils.py` extraction, prep to avoid a circular import), `ddd205a` (`mwparserfromhell` dependency), `4bbd34e`/`8962534`/`7bf36c6`/`7eb8672` (new `pipelines/ja_wikipedia_years.py`: fetch layer + title resolution, heading parsing, infobox parsing, trim matching + orchestrator + cache), `0d0d929` (30 unit tests), `4a0539f` (validation script), `d67c871` (wiring).

**Corrections to this PLAN section's own spec, found via live verification before writing any extraction regex:** the `初代`/`N代目` ordinal heading example above is not representative — **Toyota Land Cruiser's own headings have no ordinal at all** (`40系（1960年 - 1984年）`), and a parser requiring one would have missed most of the very page this source exists to fix. Land Cruiser's `70系` also has three separate comma-separated date ranges in one heading (production stopped and resumed twice) — handled as one generation whose `year_from` is the earliest start and `year_to` is `None` (still open) if the last cluster is. `mwparserfromhell` (not `regex`/plain string ops) is used specifically because real `販売期間` infobox values wrap nested templates (`{{Ublist|...}}` for multi-market variants, `{{dl2|...}}` for multi-trim variants with embedded `（発表:...）` announcement-date asides that must be stripped, not misread as a second production date) that a naive regex mis-extracts or silently returns nothing for.

**A second, structurally distinct infobox exists and had to be explicitly excluded:** `Infobox_自動車基本情報` (one per article, nameplate-level summary) vs. `Infobox_自動車のスペック表` (one per generation). The former's `販売期間` field on the real Land Cruiser page reads `[[1951年]] -` — **the exact same wrong nameplate-level span that caused the original bug, just via a different field.** Only the latter is trusted.

**Environment note:** `mwparserfromhell` has no prebuilt wheel for Python 3.14/Windows and needs MSVC Build Tools to compile from source, which weren't installed here; installing the full VC++ workload was attempted but the base Build Tools package alone didn't include it. Resolved via `mwparserfromhell`'s own documented pure-Python-tokenizer fallback (`WITH_EXTENSION=0 pip install mwparserfromhell`) instead — same library, verified working identically against real wikitext, no compiler needed. Future `pip install -r requirements.txt` runs on similar Windows-without-build-tools machines will need the same env var.

**Rate limiting/throttle contract implemented exactly as scoped above:** a `ThrottledError` is raised on any non-200/non-JSON/wrong-Content-Type response and propagated to every caller — never caught and silently treated as "no data" anywhere in the module or in `enrich_years.py`'s wiring. 1.0s minimum spacing enforced per request.

**Title resolution required more than the "langlink, no translation needed" claim above turned out to need:** blindly trusting the #1 en.wikipedia search hit (as a first implementation did) silently resolved wrong vehicles — `Mazda DEMIO` → Autozam (an unrelated defunct sub-brand), `Volkswagen GOLF` → the Atlas, `Daihatsu HIJET` → the company's own page beating the real model article. Root cause: `rapidfuzz.fuzz.token_set_ratio` is subset-tolerant (a bare "Toyota" scores 100 against "Toyota CROWN") and case-sensitive without an explicit processor. Fixed by scoring the top-3 candidates with `token_sort_ratio` + `processor=default_process` instead, rejecting anything below a 55 threshold rather than guessing, with a round-trip-scored ja.wikipedia-direct-search fallback when no en.wikipedia langlink clears the bar. Against the 12-nameplate sample below this resolves correctly with high confidence in most cases, one plausible alternate-naming case (Demio ↔ Mazda2, a real cross-wiki convergence), one clean fallback resolution, and one honest "unresolved" for Hino Dutro (no confident match) rather than a wrong guess.

**Trim → generation mapping — still the flagged "unsolved part" above, but now with a concrete safe fallback rather than nothing:** `match_trim_to_generation()` prefers an exact chassis-code/label match (catches cases like Crown's `クロスオーバー` where a broader generation's own prose also mentions the trim word, which a plain substring search alone falsely turned into "ambiguous"), then falls back to substring search, and returns no match with every candidate attached — never a guess — when neither tier is unambiguous. Feeding it a real trim token depends on `extract_base_model()`'s 2-token truncation (defect **2** in this PLAN's own root-cause list above, still open, task item 3) not having already swallowed the trim word into the "base model" before it reaches this source; `_derive_trim_hint()` recovers what it can from the untruncated original model string, which works for 3+-token model strings and is a no-op (safe, not wrong) otherwise.

**Live validation run (`scripts/validate_ja_wikipedia_years.py`, no trim hint, the 12 nameplates from this PLAN's coverage sample) — no wrong per-generation year data produced anywhere:** 10/12 nameplates returned clean, plausible, distinct generation lists (Land Cruiser correctly shows 1951 as one real, bounded generation — `BJ・FJ型`, 1951-1955 — among 12 total, not every query collapsing to 1951 as the original bug did); Hino Dutro is an honest unresolved title; Subaru Sambar resolves to the Subaru brand-disambiguation page and safely returns zero generations rather than fabricating data. Also observed: Volkswagen Golf's en.wikipedia presence is split across per-generation articles, so only one generation's data was found — a real resolution-precision limit, not fixed in this pass.

**Wired into `enrich_years.py`'s `lookup_years()`** between CarQuery and English Wikipedia (fueleconomy/CarAPI/CarQuery keep their existing position — unaffected by the bug this source fixes). Verified live end-to-end: the full cascade runs in order with no exceptions, contributes data when ja.wikipedia resolves unambiguously, falls through cleanly otherwise. Also added to `admin_router.py`'s `GET /pipeline/crsp/provider-health` probe list and the run-summary bookkeeping dicts.

**Not done in this pass (still open, per this PLAN's own task list above):** items 1, 3-10 — in particular, **Wikidata has not been removed from the chain** (item 3/"drop Wikidata entirely" in the Source priority note), the four `enrich_years.py` defects are unfixed, and no bulk 3,069-variant re-run or `vehicle_years`/`vehicle_years_staging` schema change (match-confidence column) has happened. `cache/ja_wikipedia_cache.json` is git-ignored-by-omission (not committed, unlike the sibling `cache/*.json` files) since it currently only holds this session's ad hoc validation-run data, not a real accumulated production cache.
