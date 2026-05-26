# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**Chloride Exide KE — Battery Finder**: A production web app that recommends the correct car battery for Kenyan vehicles. It uses a cleaned CRSP/NTS dataset, a 3-layer rule-based matching engine, and is geo-restricted to Kenya.

## Commands

### Backend
```bash
pip install -r requirements.txt
alembic upgrade head
python create_admin.py --username admin --password <password>
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

### Data Pipelines (run in order when refreshing dataset)
```bash
python dataprep.py            # CRSP Excel → vehicles_raw table + CSV
python nts_dataprep.py        # NTS workbook → nts_vehicles_clean.csv
python enrich_years.py        # Enrich vehicles with production years (hits NHTSA, CarAPI, fueleconomy.gov, Wikidata)
python allocate_cc_fuel.py    # Enrich NTS vehicles with engine CC + fuel type
```

### CI/CD (Jenkinsfile)
Stages: Checkout → Setup Python → Setup Node.js & Bun → Lint Frontend → Build Frontend → Test Python (pytest) → Archive Artifacts

## Architecture

### Matching Engine (`matcher.py`)
Three layers applied in order, returning at first match:
1. **Exact** — make + fuzzy model (≥90 score) + exact year → confidence 100%
2. **Soft** — make + fuzzy model (≥60 score) + year within ±3 years → confidence 60–89%
3. **Fallback** — engine CC + fuel type → Ah bracket → confidence 30–59%

Pre-match steps: resolve international model names to JDM equivalents via `model_aliases`, infer stop-start requirement from make+year, determine NS/JIS vs DIN standard from vehicle origin region.

All vehicle/battery/alias data is loaded at startup into an LRU cache and held in memory for fast matching.

### Backend (`app.py` + `admin_router.py`)
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

Migrations live in `alembic/versions/`. Always run `alembic upgrade head` after pulling.

### Frontend (`frontend/src/`)
React 19 + TypeScript + Vite + Tailwind CSS v4. Key areas:
- `components/VehicleFinderForm.tsx` — main search form (Select vs Type input modes)
- `components/ResultCard.tsx` — battery recommendation display
- `lib/api.ts` / `lib/adminApi.ts` — typed fetch wrappers for public and admin APIs
- `lib/TestUserContext.tsx` — React context for test-user session
- `pages/admin/` — admin dashboard pages (Batteries, Audit, Sessions, Feedback, DataPipeline)

In dev, Vite proxies `/api/*` to `localhost:8000`. In production, FastAPI serves the built `frontend/dist/` as static files.

## Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost:5432/batteryfinderdev
ADMIN_COOKIE_SECURE=false   # set false for local HTTP dev; true in production (HTTPS)
```

Loaded via `python-dotenv` in `db.py`. Never commit `.env`.

## Key Patterns

- **Upload pipeline** (`upload_pipeline.py`): handles Excel battery data cleanup, validation, and upsert — used by the admin DataPipeline page
- **Accuracy scripts** live in `scripts/` and are standalone — not part of the app runtime
- **Enrichment caches** (`year_cache.json`, `enrichment_cache.json`) speed up re-runs of the data pipelines; safe to delete to force a full re-fetch
- The `battery_specs` table uses soft-delete; always filter `deleted_at IS NULL` when querying active batteries

THESE ARE YOUR TAKS:

You are to look through battery specs data 2023 to 2026 xlsx file 
you are standardize data in it by:
dropping duplicates and rows with blank values 
duplicates include words or letters in different case but same spelling 
in the dataset you will remove these rows:
created on, Customer Acc and region 
on the batteries collumn remove the first digit as this refers to the quantity we don need this data 

you are to save the new table into the batteryfinderdev db with a uniques name



this data directly matches a car to battery instead of making a calculated guess in our matcher how can we use this data as inference table before the matcher engine logic fires as it provides real world data?


how can we match car models to this data when cars have various trims but likey have the same battery our vehicle dataset has exapnsive model list 



suggest a plan before you make file changes 