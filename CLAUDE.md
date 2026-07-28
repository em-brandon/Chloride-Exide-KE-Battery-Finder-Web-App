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
