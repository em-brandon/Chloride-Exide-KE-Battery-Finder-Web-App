# Chloride Exide KE — Battery Finder

A full-stack production web application that recommends the correct car battery for Kenyan vehicles, built on a cleaned and enriched CRSP dataset.

The project is organized into three distinct layers:

1. **Data pipelines** — clean and normalize raw CRSP/NTS vehicle data, enrich with production years and engine specs from multiple public APIs, and produce structured lookup datasets.
2. **Backend API** — a FastAPI (Python) server with a 3-layer rule-based matching engine, rate limiting, admin dashboard, feedback collection, and test-user auth.
3. **Frontend** — a React 19 + TypeScript app built with Vite and Tailwind CSS v4, served as static assets from the backend in production.

> **Audience:** This service is available to Kenyan clients only. Geographic access controls are enforced at the CDN and API gateway levels.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Running the App](#running-the-app)
- [Pipeline App](#pipeline-app)
- [API Reference](#api-reference)
- [Matching Engine](#matching-engine)
- [Admin Dashboard](#admin-dashboard)
- [Data Pipelines](#data-pipelines)
- [Database Schema](#database-schema)
- [Security](#security)
- [Production Architecture](#production-architecture)
- [Environment Variables](#environment-variables)

---

## Tech Stack

### Backend
| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Web framework | [FastAPI](https://fastapi.tiangolo.com/) (`app.py`) |
| ASGI server | Uvicorn |
| Rate limiting | `slowapi` — per-endpoint limits in `app.py` and `admin_router.py` |
| ORM | SQLAlchemy 2.0 (`db.py`, `models.py`) |
| Migrations | Alembic (`alembic/`) |
| Auth | bcrypt + HttpOnly session cookies (`admin_auth.py`) |
| Database | PostgreSQL via `psycopg2-binary` |

### Frontend
| Layer | Technology |
|---|---|
| Framework | [React 19](https://react.dev/) + [TypeScript 6](https://www.typescriptlang.org/) |
| Build tool | [Vite 8](https://vite.dev/) |
| Package manager | [Bun](https://bun.sh/) |
| Styling | [Tailwind CSS v4](https://tailwindcss.com/) |
| UI primitives | [Radix UI](https://www.radix-ui.com/) |
| Routing | [React Router v7](https://reactrouter.com/) |
| Icons | [Lucide React](https://lucide.dev/) + [Heroicons](https://heroicons.com/) |

### Data Pipeline
| Tool | Purpose |
|---|---|
| Pandas | Data cleaning, normalization, and output |
| `rapidfuzz` | Fuzzy model name matching across external API results |
| NHTSA VPIC API | Vehicle make/model lookup |
| CarAPI | Year-range data per model |
| fueleconomy.gov | US DOE/EPA bulk CSV (local cache) |
| Wikidata / Wikipedia | Supplementary year and fuel-type enrichment |

---

## Project Structure

```
├── app.py                      # FastAPI entrypoint — public API, auth, middleware
├── admin_router.py             # All /api/admin/* routes (batteries, audit, sessions)
├── admin_auth.py               # bcrypt + HttpOnly cookie session management
├── matcher.py                  # 3-layer battery matching engine (exact → soft → rule)
├── models.py                   # SQLAlchemy ORM models for all tables
├── db.py                       # SQLAlchemy engine + SessionLocal factory
├── upload_pipeline.py          # Battery spec upload/import handler
├── seed.py                     # Seed DB from battery_specs_output.xlsx
├── create_admin.py             # CLI: create/update admin user accounts
├── check_db.py                 # Diagnostic: quick DB query for feedback records
├── remove_ultrapower.py        # Maintenance: remove ULTRAPOWER battery entries
├── audit_28_case.py            # Maintenance: audit specific case records
│
├── dataprep.py                 # Pipeline 1: clean CRSP Excel → vehicles_raw
├── nts_dataprep.py             # Pipeline 2: clean NTS workbook → nts_vehicles_clean
├── enrich_years.py             # Pipeline 3: enrich vehicles with production years
├── allocate_cc_fuel.py         # Pipeline 4: enrich NTS vehicles with CC + fuel type
│
├── alembic/                    # Database migration scripts
│   └── versions/               # One migration file per schema change
│
├── frontend/                   # React + TypeScript frontend
│   ├── src/
│   │   ├── App.tsx             # Root layout — navbar, dark mode, routing
│   │   ├── components/
│   │   │   ├── VehicleFinderForm.tsx   # Main search form (Select/Type toggle)
│   │   │   ├── ResultCard.tsx          # Battery recommendation result display
│   │   │   ├── FeedbackModal.tsx       # User feedback submission modal
│   │   │   ├── ConfidenceBar.tsx       # Match confidence visual indicator
│   │   │   ├── Notification.tsx        # Toast notification system
│   │   │   ├── PageLoader.tsx          # Animated battery splash screen
│   │   │   └── admin/
│   │   │       ├── AdminLayout.tsx     # Admin panel shell (sidebar nav)
│   │   │       └── ProtectedRoute.tsx  # Auth guard for admin routes
│   │   ├── pages/
│   │   │   ├── admin/
│   │   │   │   ├── AdminDashboard.tsx
│   │   │   │   ├── AdminBatteries.tsx
│   │   │   │   ├── AdminFeedback.tsx
│   │   │   │   ├── AdminAuditLog.tsx
│   │   │   │   ├── AdminSessions.tsx
│   │   │   │   ├── AdminTestSessions.tsx
│   │   │   │   ├── AdminCoverage.tsx   # Battery coverage stats + unmatched table
│   │   │   │   └── AdminLogin.tsx
│   │   │   └── TestUserLogin.tsx
│   │   ├── lib/
│   │   │   ├── api.ts              # Typed fetch wrappers for public API
│   │   │   ├── adminApi.ts         # Typed fetch wrappers for admin API
│   │   │   ├── testUserApi.ts      # Test-user auth API helpers
│   │   │   └── TestUserContext.tsx # React context for test-user session state
│   │   └── types/
│   │       └── battery.ts          # TypeScript interfaces for API responses
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.app.json
│
├── pipeline_app/               # Standalone pipeline browser app (separate from admin)
│   ├── app.py                  # FastAPI backend — pipeline routes only, port 8001
│   ├── requirements.txt
│   └── frontend/               # Vite/React pipeline UI, port 5175
│       ├── src/
│       │   ├── App.tsx         # Auth shell — Login → Web Validate / CRSP tabs
│       │   ├── pages/
│       │   │   ├── WebValidatePage.tsx  # Web Validate pipeline control + staging area
│       │   │   ├── CrspPage.tsx         # CRSP dataset pipeline
│       │   │   └── LoginPage.tsx
│       │   └── lib/
│       │       └── api.ts      # Typed fetch wrappers (HttpOnly cookie session)
│       ├── package.json
│       ├── vite.config.ts
│       └── index.html
│
├── pipelines/                  # Data pipeline scripts
│   ├── dataprep.py             # Pipeline 1: CRSP Excel → vehicles_raw
│   ├── nts_dataprep.py         # Pipeline 2: NTS workbook → nts_vehicles_clean
│   ├── enrich_years.py         # Pipeline 3: enrich with production years
│   └── dial_battery_clean.py   # Pipeline 4: Dial-A-Battery inference table
│
├── scripts/                    # Accuracy and failure mode analysis scripts
├── requirements.txt            # Python dependencies
├── alembic.ini                 # Alembic configuration
├── Jenkinsfile                 # CI/CD pipeline definition
└── .env                        # Environment variables (not committed)
```

> **Note:** The source file `New-CRSP---July-2025.xlsx` is required to run `dataprep.py` but is not committed to the repository.

---

## Getting Started

### Prerequisites

- Python 3.10 or later
- [Bun](https://bun.sh/) (for frontend builds)
- PostgreSQL running and accessible
- `.env` file configured (see [Environment Variables](#environment-variables))

### Set Up Python Virtual Environment

```bash
# Create the virtual environment (first time only)
python -m venv .venv

# Activate it — PowerShell
.venv\Scripts\Activate.ps1

# Activate it — bash / Git Bash
source .venv/Scripts/activate
```

> You must activate the virtual environment in every new terminal session before running `uvicorn`, `python`, or `alembic`.

### Install Dependencies

```bash
# Python (with .venv active)
pip install -r requirements.txt

# Frontend
cd frontend && bun install
```

### Apply Database Migrations

```bash
alembic upgrade head
```

### Create First Admin User

```bash
python scripts/create_admin.py --username admin --password yourpassword
```

Use `--force` to update an existing password:

```bash
python scripts/create_admin.py --username admin --password newpassword --force
```

---

## Running the App

### Production

```bash
# Build the frontend
cd frontend && bun run build && cd ..

# Start the backend (serves built frontend from frontend/dist/)
source .venv/Scripts/activate   # or .venv\Scripts\Activate.ps1 on PowerShell
uvicorn app:app --host 0.0.0.0 --port 8000
```

The app starts on **http://localhost:8000**. Static frontend assets are served directly from `frontend/dist/` by FastAPI.

### Development (hot reload)

```bash
# Activate the virtual environment first (every new terminal session)
source .venv/Scripts/activate        # bash / Git Bash
# .venv\Scripts\Activate.ps1         # PowerShell

# Terminal 1 — backend (port 8000)
uvicorn app:app --reload

# Terminal 2 — frontend (port 5173, proxies /api to port 8000)
cd frontend && bun run dev
```

Frontend dev server: **http://localhost:5173**

---

## Pipeline App

The pipeline app is a **standalone browser application** that runs separately from the main admin dashboard. It connects directly to the same PostgreSQL database and is designed to be used locally during data preparation.

> In production, point `DATABASE_URL` in `.env` to your AWS RDS instance — no other changes needed.

The pipeline app shares the same `.env` (and therefore the same `DATABASE_URL`) as the main app. No additional environment setup is needed beyond what is already configured.

### Running the Pipeline App

```bash
# Terminal 1 — pipeline backend (port 8001)
source .venv/Scripts/activate        # bash / Git Bash
# .venv\Scripts\Activate.ps1         # PowerShell
cd pipeline_app
pip install -r requirements.txt      # first time only
uvicorn app:app --port 8001 --reload

# Terminal 2 — pipeline frontend (port 5175, proxies /api to port 8001)
cd pipeline_app/frontend
bun install                          # first time only
bun run dev
```

Open **<http://localhost:5175>** and sign in with the same admin credentials created during [Getting Started](#getting-started).

### Pipeline App Features

| Tab | Description |
|---|---|
| **Web Validate** | Run the web battery validation pipeline — toggle providers, choose phase (Phase 1 prefetch / Phase 2 lookup / Both), monitor live progress, review the staging area, fix suspicious Ah values, resolve conflicts, and commit to master |
| **CRSP Dataset** | Run the CRSP data prep pipeline — specify the Excel file path, stream stage progress (Loading → Schema → Normalizing → Dedup → Saving), and review the output summary |

### Accessing from Admin Dashboard

Once the pipeline app is running, the admin dashboard sidebar shows a **Pipeline App ↗** link that opens `http://localhost:5175` in a new tab. The URL can be overridden by setting `VITE_PIPELINE_APP_URL` in the frontend `.env`.

### Building the Desktop `.exe` (Windows)

The pipeline app can be packaged as a standalone Windows desktop application using PyInstaller and pywebview. The resulting `.exe` opens the React UI in a native Edge WebView2 window — no browser, no address bar.

**Prerequisites (developer only):**

- [Inno Setup](https://jrsoftware.org/isdl.php) installed (free)
- Python virtual environment active

**Build steps:**

```bash
# 1. Compile the React frontend
bun --cwd pipeline_app/frontend run build

# 2. Install PyInstaller and pywebview (first time only)
pip install pyinstaller pywebview

# 3. Bundle into a single .exe
cd pipeline_app
pyinstaller pipeline_app.spec
# → dist/PipelineApp.exe (~50 MB)

# 4. Fill in pipeline.env with the real values (do NOT commit this file)
#    DATABASE_URL=postgresql://user:password@your-rds-endpoint:5432/batteryfinderdev?sslmode=require
#    BRAVE_SEARCH_API_KEY=...
#    TAVILY_API_KEY=...

# 5. Compile the Windows installer
iscc installer.iss
# → dist/PipelineApp-Setup-1.0.0.exe
```

**End-user experience:** double-click `PipelineApp-Setup-1.0.0.exe`, follow the standard Windows installer, then launch from the Desktop shortcut. No terminal, no config files, no browser needed.

> The `.exe` reads `pipeline.env` from the same directory — `DATABASE_URL` and API keys are never bundled inside the binary. The installer copies `pipeline.env.example` as `pipeline.env` on first install only; edit it with the real credentials before distributing to users.

---

## API Reference

All public endpoints are rate-limited and served under `/api/`.

### Public Endpoints

| Method | Endpoint | Rate Limit | Description |
|---|---|---|---|
| `GET` | `/api/makes` | 20/min | List all available vehicle makes |
| `GET` | `/api/models/{make}` | 20/min | List models for a given make |
| `GET` | `/api/years?make=&model=` | 20/min | List available years for a make + model |
| `POST` | `/api/recommend` | 10/min | Get a battery recommendation |
| `POST` | `/api/feedback` | 5/min | Submit feedback on a recommendation |

### Auth Endpoints (Test Users)

| Method | Endpoint | Rate Limit | Description |
|---|---|---|---|
| `POST` | `/api/auth/register` | 5/min | Register a new test user |
| `POST` | `/api/auth/login` | 10/min | Log in as a test user |
| `POST` | `/api/auth/logout` | — | Log out |
| `GET` | `/api/auth/me` | — | Get current test user info |

### `POST /api/recommend` — Request Body

```json
{
  "make": "TOYOTA",
  "model": "Corolla",
  "year": 2015,
  "engine_cc": 1500,
  "fuel_type": "Petrol"
}
```

`engine_cc` (500–8000) and `fuel_type` are optional but improve match confidence.

### `POST /api/recommend` — Response

```json
{
  "match_type": "exact",
  "confidence": 100,
  "matched_make": "TOYOTA",
  "matched_model": "COROLLA AXIO G",
  "matched_year": 2015,
  "engine_cc": 1500,
  "fuel_type": "Petrol",
  "primary": {
    "battery_code": "NS60",
    "model_key": "NS60",
    "ah": 45,
    "cca_en": 390,
    "technology": "MF"
  },
  "alternatives": []
}
```

---

## Matching Engine

Defined in `matcher.py`. Data is loaded from the database at startup via `lru_cache` and held in memory. The engine applies a **3-layer rule hierarchy**:

| Layer | Trigger | Confidence |
|---|---|---|
| **Exact** | Make + fuzzy model (≥90 score) + exact year in `vehicle_years` | 100% |
| **Soft** | Make + fuzzy model (≥60 score) + year within ±3 years | 60–89% |
| **Rule-based fallback** | Engine CC + fuel type → Ah bracket | 30–59% |

The engine also:
- Resolves international model names to JDM equivalents via `model_aliases`
- Infers stop-start battery requirement from make + year
- Applies NS/JIS vs DIN battery standard based on vehicle origin region (see `_NS_MAKES`, `_DIN_MAKES` in `matcher.py`)

---

## Admin Dashboard

Protected under `/api/admin/*`. Access requires an HttpOnly session cookie issued by `POST /api/admin/login`. Implemented in `admin_router.py` with auth enforced by `admin_auth.py`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/admin/login` | Admin login (5/min rate limit) |
| `POST` | `/api/admin/logout` | Clear session |
| `GET` | `/api/admin/me` | Current admin user |
| `GET` | `/api/admin/stats` | Usage stats and record counts |
| `GET` | `/api/admin/health` | Database connectivity check |
| `GET/POST` | `/api/admin/batteries` | List or create battery specs |
| `PATCH` | `/api/admin/batteries/{id}` | Update a battery spec |
| `DELETE` | `/api/admin/batteries/{id}` | Soft-delete a battery spec |
| `POST` | `/api/admin/batteries/upload` | Bulk upload from Excel |
| `GET` | `/api/admin/batteries/export` | Export battery specs as Excel |
| `GET` | `/api/admin/audit` | Full change history |
| `POST` | `/api/admin/cache/refresh` | Reload matcher caches from DB |
| `GET/DELETE` | `/api/admin/sessions` | View or revoke admin sessions |

---

## Data Pipelines

Run scripts in order when refreshing the dataset.

### Pipeline 1 — CRSP Data Prep

```bash
python dataprep.py
```

Input: `New-CRSP---July-2025.xlsx` (not committed)
Output: `battery_lookup_dataset.csv`, `battery_lookup_dataset.xlsx`

### Pipeline 2 — NTS Data Prep

```bash
python nts_dataprep.py
```

Input: `NTSA Vehicles Registered 2024.xlsx`
Output: `nts_vehicles_clean.csv`, `nts_vehicles_clean.xlsx`

### Pipeline 3 — Year Enrichment

```bash
python enrich_years.py
```

Input: `battery_lookup_dataset.csv`
Output: `vehicle_years.csv`, `vehicle_years.xlsx`, `unmatched_models.csv`

Fetches production years from (in order): fueleconomy.gov bulk CSV → NHTSA VPIC → CarAPI → Wikidata/Wikipedia.
API results cached in `year_cache.json` (the `years` key is cleared on each run; `nhtsa` and `carapi` persist).

### Pipeline 4 — NTS CC + Fuel Enrichment

```bash
python allocate_cc_fuel.py
```

Input: `nts_vehicles_clean.csv`
Output: `nts_vehicles_enriched.csv`, `nts_vehicles_enriched.xlsx`, `nts_unmatched_enriched.csv`

Enriches each NTS vehicle with engine displacement (cc) and fuel type. Results cached in `enrichment_cache.json`.

Fuel type is normalized to one of: `PETROL` · `DIESEL` · `ELECTRIC` · `HYBRID` · `PLUG-IN HYBRID` · `CNG` · `LPG` · `HYDROGEN`

---

## Database Schema

Managed by Alembic (`alembic/versions/`). Apply migrations with `alembic upgrade head`.

| Table | Written by | Read by | Description |
|---|---|---|---|
| `vehicles_raw` | `dataprep.py` | `enrich_years.py` | Cleaned CRSP vehicle records |
| `vehicle_years` | `enrich_years.py` | `matcher.py` | Per-make/model/year rows with CC + fuel |
| `battery_specs` | `seed.py`, admin upload | `matcher.py` | Battery catalogue (soft-delete via `deleted_at`) |
| `model_aliases` | `seed.py` | `matcher.py` | International → JDM model name mappings |
| `admin_users` | `create_admin.py` | `admin_auth.py` | Admin credentials (bcrypt hashed, cost 12) |
| `admin_sessions` | `admin_auth.py` | `admin_auth.py` | Active admin sessions (8-hour TTL) |
| `battery_audit_log` | `admin_router.py` | Admin UI | Immutable change history for battery_specs |
| `admin_stats` | `app.py` middleware | Admin UI | Persisted usage counters (e.g. `db_reads`) |
| `test_users` | `/api/auth/register` | `app.py` | Test user accounts |
| `test_user_sessions` | `/api/auth/login` | `app.py` | Test user tokens (24-hour TTL) |
| `user_feedback` | `/api/feedback` | Admin UI | User feedback on recommendations |

---

## Security

- All secrets loaded from environment variables via `python-dotenv` (`db.py`)
- Admin passwords stored as bcrypt hashes with cost factor 12 (`admin_auth.py`)
- Admin sessions use cryptographically random 64-character hex tokens
- Session cookies are `HttpOnly`, `Secure`, `SameSite=Strict`
- Rate limiting applied per endpoint via `slowapi`
- Input validation enforced on all request bodies via Pydantic models
- IP addresses captured and truncated to 45 characters for feedback and session records
- Geographic access restricted to Kenya (enforced at CDN + WAF layer in production)

---

## Production Architecture

```
Users (Kenya only — geo-restricted)
  │
  ▼
Route 53 ─► CloudFront (KE geo-restriction)
               │                  │
        static assets        API requests
               │                  │
               ▼                  ▼
         S3 Frontend         ALB + AWS WAF
         Bucket              (rate limits, bot filtering)
                                  │
                                  ▼
                            ECS Fargate
                            FastAPI backend
                            (min 2 tasks / hard max cap)
                                  │
                     ┌────────────┴────────────┐
                     ▼                         ▼
               ElastiCache Redis          RDS PostgreSQL
               (cache / rate state)       (auth, feedback,
                     │                    sessions, audit)
                     ▼
               S3 Data Bucket
               (CSVs, uploads,
               pipeline outputs)

Pipelines
  EventBridge Scheduler ─► ECS Fargate Tasks
  (dataprep · enrich · upload · publish jobs)
```

Secrets are stored in AWS SSM Parameter Store or Secrets Manager and injected as environment variables at task runtime.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values before running the app:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `ADMIN_COOKIE_SECURE` | No | Set `false` for local HTTP dev (default `true`) |

Example `.env`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/battery_finder
ADMIN_COOKIE_SECURE=false
```

> **Never commit `.env` to version control.** The repository `.gitignore` already excludes it.

---

## CI/CD

Defined in `Jenkinsfile`. Pipeline stages:

1. Checkout source
2. Install Python dependencies
3. Install Bun + frontend dependencies
4. Frontend lint (`bun run lint`)
5. Frontend build (`bun run build`)
6. Python tests (`pytest`)
7. Archive `frontend/dist/` artifacts

Build failure notifications are sent by email.
