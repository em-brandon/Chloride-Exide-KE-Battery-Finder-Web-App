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

## PLANNED FOR TOMORROW (found 2026-07-20) — Least-privilege public DB role (public traffic currently shares the full-privilege DB credential)

**Found via:** following up on "is the DB we're serving to users read-only?" — traced every DB write path in the app. Public/unauthenticated endpoints (`POST /api/recommend`, `POST /api/feedback`, `POST /api/auth/register`, `POST /api/auth/login`, plus the read-counter middleware that runs on every request) do write to the database (`search_events`, `user_feedback`, `test_users`, `test_user_sessions`, `admin_stats`) — and, more importantly, the fact that public traffic never touches admin-only tables (`battery_specs`, `vehicle_years`, etc.) is enforced *only* by application-code discipline, not by the database itself. `backend/db.py` has exactly one `engine`/`SessionLocal`, backed by one Postgres role, shared identically by public routes, admin routes, and pipelines — a bug in any public-facing code path has no DB-level guardrail stopping it from writing to the matching engine's source tables.

**Design — two Postgres roles / two SQLAlchemy engines:**
- Existing role (`batteryfinder`, unchanged) stays full-privilege, used by `admin_router.py`, `admin_auth.py`, pipelines, scripts.
- New restricted role (e.g. `batteryfinder_public`) used by public routes in `app.py` and all of `matcher.py`'s reads — matcher never writes, so it's safe to route through the restricted role everywhere, including when admin's `/cache/refresh` calls it.

**Grants for the new role** (traced every actual call site, not guessed):
- `SELECT` only: `vehicle_years`, `vehicle_years_exide`, `battery_specs`, `dial_battery_inference`, `oem_fitment`, `web_battery_validation`, `model_aliases` (matcher's 7 read sources), plus `app_settings` (maintenance-mode check, runs on every request) and `test_users` (login lookup).
- `INSERT` only: `search_events`, `user_feedback`, `test_users`, `test_user_sessions`, `admin_stats`.
- `UPDATE`, narrow: `test_user_sessions.last_seen_at` (session heartbeat), `admin_stats.stat_value` (read-counter increment/midnight reset).
- No `DELETE`, no DDL, nothing else.

**Code changes:**
- `db.py` — add `public_engine`/`PublicSessionLocal`, sourced from a new `PUBLIC_DATABASE_URL` env var.
- `matcher.py` — repoint its 7 `pd.read_sql(..., engine)` calls at the restricted engine.
- `app.py` — swap `SessionLocal()` → `PublicSessionLocal()` at every public-route write site: read-counter flush/reset, search-event logging, feedback submission, test-user register/login, the token→session heartbeat lookup, and `app_state.py`'s maintenance-mode read.
- `admin_router.py`, `admin_auth.py`, pipelines, scripts — untouched.
- New Alembic migration: `CREATE ROLE` (idempotent, via a `DO $$...$$` guard — Postgres has no `CREATE ROLE IF NOT EXISTS`) plus the grants above. Password read from an env var at migration time, never hardcoded in the migration file.

**Infrastructure implications (outside this repo, same situation as the CloudFront geo-restriction precedent):**
- Local dev: new `PUBLIC_DATABASE_URL` in `.env`.
- Production: new SSM parameter + new ECS task-definition env var injection — needs coordination outside this repo.
- Tests: `conftest.py` currently wraps each test in one rolled-back transaction bound to the single `engine`. A second engine/role won't automatically join that transaction — tests touching feedback/search-event/test-user paths need `conftest.py` updated (bind `PublicSessionLocal` to the same test connection) or they'll leak rows into the dev DB during test runs.

**Plan for tomorrow — new branch required:** implement the in-repo parts (migration, `db.py`, `matcher.py`, `app.py`, `conftest.py`); flag the production SSM/ECS piece as a follow-up the same way the CloudFront work was.

## PLANNED FOR TOMORROW (found 2026-07-18) — Web Validation region-resolution bug (DIN/NS mix-up)

**Found via:** comparing two admin search-log entries for the same vehicle side by side — `toyotta harrierr 2013` (typo) returned `Exact Match 100%` / 55Ah EFB, while the correctly-spelled `toyota harrier 2013` returned `Web-Validated Match 90%` / 65Ah — a lower confidence for the *correctly* spelled query. Traced end-to-end against the live dev DB (not guessed): the typo in the **make** field caused Layers 0a/0b to miss entirely (`_web_validation_lookup()`/`_inference_lookup()` filter make with plain `==`, zero fuzzy tolerance — the ≥75 `WRatio` make correction only exists inside Layer 1/2's own code path, which runs after), so the typo'd query fell through to Layer 1's dataset match (real make/model fuzzy correction, landed on `HARRIER` cleanly) and got a generic CC-bracket Ah estimate (`oem_fitment` has zero Harrier rows). The correctly-spelled query hit real data in `web_battery_validation` — `TOYOTA / HARRIER / 2013 → DIN 060MF L EXIDE AGM, 60Ah AGM` — genuine internet-sourced fitment info, **but Toyota is an NS/JIS-region make** (`matcher._NS_MAKES`), so `_select_batteries()` couldn't use a DIN-spec battery and substituted the nearest NS equivalent (65Ah `NS70MFL POWERLAST`) instead.

**Root cause:** `backend/pipelines/web_battery_validate.py`, `_resolve_battery_code()` (~line 512): `region = parsed.get("region") or _make_region(make_n)` — trusts a web-scraped "NS"/"DIN" keyword hit (`_parse_snippets()`'s `_NS_RE`/`_DIN_RE`, scanning raw search-result text) over the make's own known, authoritative region. This is pointless as well as wrong: `recommend()` at request time *always* independently recomputes `region = _make_region(make_n)` for Layer 0a and ignores whatever region the pipeline picked when it stored the row — so letting the noisy web-text signal override the make-based region at ingestion time can only ever pick a battery_code from the wrong region pool, for zero benefit, since it gets discarded and re-resolved at request time anyway. "DIN" is also a common Exide catalogue SKU/product-name prefix (see `battery_specs.model_key`, e.g. `DIN060`), not purely a physical-region marker, so it shows up in scraped listing text even for NS-market vehicles — biasing `_DIN_RE` toward false positives on exactly the makes (Toyota, Daihatsu, Honda, etc.) where it's wrong.

**Confirmed scope (queried live, not estimated):** 391 rows across NS-region makes in `web_battery_validation` have DIN-prefixed `battery_code` values. Verified affected beyond Harrier: Daihatsu Hijet Caddie/Truck (multiple years), and multiple Toyota Hilux trims (`HILUX 2 GD D/CAB...`, `HILUX D/C GD 6 COMFORT PLUS...`) — user independently spotted the Hilux rows during review.

**Plan for tomorrow — new branch required, not a same-day fix:**

1. New branch for this work (not `main` directly — this touches both pipeline code and live data).
2. **Provision a database backup procedure in the admin panel.** Backup/restore currently only exists as local PowerShell scripts (`db-backup-script/backup-db.ps1` / `restore-db.ps1`, see README's [Local Postgres Dev DB Backup](README.md#local-postgres-dev-db-backup-db-backup-script) section) — `docker exec pg_dump` against the local dev container, run manually from a terminal. Nothing triggers a backup from the admin UI, and the script as written wouldn't work against production RDS as-is (no `docker exec` there — would need a direct `pg_dump`/`psql` connection or an RDS snapshot API call instead). Needed as a general admin capability, and specifically as the safety net immediately before step 4 below — **take a backup right before mutating `web_battery_validation`**, whether or not the full admin-panel feature ships in the same pass as the rest of this work.
3. Code fix: `_resolve_battery_code()` always uses `_make_region(make_n)`; stop trusting `parsed["region"]` for battery selection (it's used nowhere else in the pipeline, confirmed by grep — safe to stop reading it here without touching `_parse_snippets()`'s return shape).
4. Database cleanup: re-resolve/re-process the ~391 already-wrong NS-make rows currently holding DIN-coded batteries (re-run affected `(make, model, year)` combos through the fixed `_resolve_battery_code()`, or a targeted SQL re-selection pass — decide approach tomorrow). **Take a backup (step 2) immediately before this runs.**
5. **Symmetric check, not yet done:** audit the reverse case — DIN-region makes (European/American, `matcher._DIN_MAKES`) that may have been incorrectly assigned NS-coded battery codes via the same `_NS_RE` false-positive path. Not yet queried; scope unknown until checked.
