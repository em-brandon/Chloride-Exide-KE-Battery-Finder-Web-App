# Chloride Exide KE — Battery Finder

A full-stack production web application that recommends the correct car battery for Kenyan vehicles, built on a cleaned and enriched CRSP dataset.

The project is organized into three distinct layers:

1. **Data pipelines** — clean and normalize raw CRSP/NTS vehicle data, enrich with production years and engine specs from multiple public APIs, and produce structured lookup datasets.
2. **Backend API** — a FastAPI (Python) server with a 5-layer rule-based matching engine, rate limiting, admin dashboard, feedback collection, and test-user auth.
3. **Frontend** — a React 19 + TypeScript app built with Vite and Tailwind CSS v4, served as static assets from the backend in production. Includes a dedicated mobile step-wizard UI for phone browsers.

> **Audience:** This service is available to Kenyan clients only. Geographic access controls are enforced at the CDN and API gateway levels.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Running the App](#running-the-app)
- [Testing on a Real Device](#testing-on-a-real-device)
- [Pipeline App](#pipeline-app)
- [Mobile Experience](#mobile-experience)
- [API Reference](#api-reference)
- [Matching Engine](#matching-engine)
- [Admin Dashboard](#admin-dashboard)
- [Data Pipelines](#data-pipelines)
- [Database Schema](#database-schema)
- [Security](#security)
- [Production Architecture](#production-architecture)
- [Environment Variables](#environment-variables)
- [CI/CD](#cicd)

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
| File uploads | `python-multipart` — multipart form parsing for battery Excel uploads |
| PDF export | `reportlab` — admin battery catalogue PDF generation |

### Frontend
| Layer | Technology |
|---|---|
| Framework | [React 19](https://react.dev/) + [TypeScript 6](https://www.typescriptlang.org/) |
| Build tool | [Vite 8](https://vite.dev/) |
| Package manager | [Bun](https://bun.sh/) |
| Styling | [Tailwind CSS v4](https://tailwindcss.com/) + inline `style={{}}` props |
| UI primitives | [Radix UI](https://www.radix-ui.com/) |
| Routing | [React Router v7](https://reactrouter.com/) |
| Icons | [Lucide React](https://lucide.dev/) + [Heroicons](https://heroicons.com/) |
| Country flags | [react-country-flag](https://www.npmjs.com/package/react-country-flag) — SVG flag icons in result card |

### Data Pipeline
| Tool | Purpose |
|---|---|
| Pandas | Data cleaning, normalization, and output |
| `rapidfuzz` | Fuzzy model name matching across external API results |
| NHTSA VPIC API | Vehicle make/model lookup |
| CarAPI | Year-range data per model |
| fueleconomy.gov | US DOE/EPA bulk CSV (local cache) |
| Wikidata / Wikipedia | Supplementary year and fuel-type enrichment |
| `ddgs` | DuckDuckGo Search — web battery validation pipeline |
| `tavily-python` | Tavily AI Search — web battery validation pipeline |

---

## Project Structure

```
├── app.py                      # FastAPI entrypoint — public API, auth, middleware
├── admin_router.py             # All /api/admin/* routes (batteries, audit, sessions)
├── admin_auth.py               # bcrypt + HttpOnly cookie session management
├── matcher.py                  # 5-layer battery matching engine
├── models.py                   # SQLAlchemy ORM models for all tables
├── db.py                       # SQLAlchemy engine + SessionLocal factory
├── upload_pipeline.py          # Battery spec upload/import handler
├── seed.py                     # Seed DB from battery_specs_output.xlsx
│
├── alembic/                    # Database migration scripts
│   └── versions/               # One migration file per schema change
│
├── frontend/                   # React + TypeScript frontend
│   ├── src/
│   │   ├── App.tsx             # Root layout — navbar, dark mode, routing, mobile detection
│   │   ├── components/
│   │   │   ├── VehicleFinderForm.tsx   # Desktop search form (Select/Type toggle)
│   │   │   ├── MobileVehicleFinder.tsx # Mobile step-wizard (Make→Model→Year→Details→Result)
│   │   │   ├── AccuracyBar.tsx         # Segmented match accuracy bar
│   │   │   ├── FeedbackModal.tsx       # User feedback submission drawer
│   │   │   ├── Notification.tsx        # Toast notification system
│   │   │   ├── PageLoader.tsx          # Animated battery splash screen
│   │   │   ├── TermsGate.tsx           # Terms & conditions acceptance gate
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
│   │   │   │   ├── AdminCoverage.tsx
│   │   │   │   ├── AdminDataPipeline.tsx
│   │   │   │   └── AdminLogin.tsx
│   │   │   └── TestUserLogin.tsx
│   │   ├── lib/
│   │   │   ├── api.ts              # Typed fetch wrappers for public API
│   │   │   ├── adminApi.ts         # Typed fetch wrappers for admin API
│   │   │   ├── testUserApi.ts      # Test-user auth API helpers
│   │   │   ├── utils.ts            # cn() + useIsMobile() hook
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
│
├── pipelines/                  # Data pipeline scripts
│   ├── dataprep.py             # Pipeline 1: CRSP Excel → vehicles_raw
│   ├── enrich_years.py         # Pipeline 2: enrich with production years
│   └── dial_battery_clean.py   # Pipeline 3: Dial-A-Battery inference table
│
├── scripts/                    # Accuracy and failure mode analysis scripts
├── requirements.txt            # Python dependencies
├── alembic.ini                 # Alembic configuration
├── Jenkinsfile                 # CI/CD pipeline definition
└── .env                        # Environment variables (not committed)
```

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
# Terminal 1 — backend (port 8000)
source .venv/Scripts/activate
uvicorn app:app --reload

# Terminal 2 — frontend (port 5173, proxies /api to port 8000)
cd frontend && bun run dev
```

Frontend dev server: **http://localhost:5173**

---

## Testing on a Real Device

To test the mobile wizard on your phone during development, expose the Vite dev server via ngrok. Vite's proxy handles `/api` forwarding server-side so only one tunnel is needed.

```bash
# Terminal 1 — backend
uvicorn app:app --reload

# Terminal 2 — frontend
cd frontend && bun run dev

# Terminal 3 — tunnel
ngrok http 5173
```

Open the ngrok HTTPS URL on your phone. The mobile wizard activates automatically at screen widths ≤ 600 px.

> **Note:** The app has geo-restriction middleware that blocks non-Kenyan IPs. If your ngrok exit node resolves as a non-KE IP, you may hit the geo-gate. Test from the same network or temporarily bypass the restriction in development.

---

## Pipeline App

The pipeline app is a **standalone browser application** that runs separately from the main admin dashboard. It connects directly to the same PostgreSQL database and is designed to be used locally during data preparation.

### Running the Pipeline App

```bash
# Terminal 1 — pipeline backend (port 8001)
source .venv/Scripts/activate
cd pipeline_app
pip install -r requirements.txt      # first time only
uvicorn app:app --port 8001 --reload

# Terminal 2 — pipeline frontend (port 5175, proxies /api to port 8001)
cd pipeline_app/frontend
bun install                          # first time only
bun run dev
```

Open **<http://localhost:5175>** and sign in with the same admin credentials created during Getting Started.

### Pipeline App Features

| Tab | Description |
|---|---|
| **Web Validate** | Run the web battery validation pipeline — toggle providers, choose phase (Phase 1 prefetch / Phase 2 lookup / Both), monitor live progress, review staging area, fix suspicious Ah values, resolve conflicts, and commit to master |
| **CRSP Dataset** | Run the CRSP data prep pipeline — specify the Excel file path, stream stage progress, and review the output summary |

### Building the Desktop `.exe` (Windows)

```bash
# 1. Compile the React frontend
bun --cwd pipeline_app/frontend run build

# 2. Bundle into a single .exe
cd pipeline_app
pyinstaller pipeline_app.spec

# 3. Compile the Windows installer
iscc installer.iss
# → dist/PipelineApp-Setup-1.0.0.exe
```

---

## Mobile Experience

On screens ≤ 600 px wide (phones), the app renders a dedicated **step-by-step wizard** (`MobileVehicleFinder.tsx`) instead of the desktop form. The desktop UI (`VehicleFinderForm.tsx`) is completely unchanged.

### Wizard Flow

```
Step 1: Select Make  →  Step 2: Select Model
→  Step 3: Select Year  →  Step 4: Engine Details (optional)
→  Result screen
```

- **Auto-advance** — selecting a Make immediately fetches models and advances to Step 2. Selecting a Model immediately fetches years and advances to Step 3.
- **Year** requires an explicit "Continue" tap to prevent accidental advances.
- **Engine Details** (fuel type + CC) are optional; a "Skip & Find Battery" button proceeds without them.
- **Result screen** shows: vehicle label, primary battery (Ah, CCA, code with copy button), result accuracy bar, Rate / Shop Now buttons, Dial-a-Battery numbers, collapsible same-tech alternatives, and a "Search Again" reset button.
- Dark mode is fully supported — CSS variables apply automatically.

### Breakpoint

| Width | Experience |
|---|---|
| ≤ 600 px | Mobile wizard (`MobileVehicleFinder`) |
| > 600 px | Desktop form (`VehicleFinderForm`) |

Detection is done client-side via `useIsMobile()` in `frontend/src/lib/utils.ts`, which uses `window.matchMedia` and responds to resize events.

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
| `POST` | `/api/battery-search` | 10/min | Search batteries by Ah and/or CCA spec |

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
  "fuel_type": "Petrol",
  "stop_start": true
}
```

`engine_cc` (500–8000), `fuel_type`, and `stop_start` are optional but improve match confidence.

### `POST /api/recommend` — Response

```json
{
  "match_type": "Exact Match",
  "confidence": 100,
  "matched_make": "TOYOTA",
  "matched_model": "COROLLA AXIO G",
  "matched_year": 2015,
  "engine_cc": 1500,
  "fuel_type": "PETROL",
  "battery_region": "NS",
  "recommended_ah": 45,
  "preferred_tech": "MF",
  "primary": {
    "battery_code": "NS60",
    "model_key": "NS60",
    "ah": 45,
    "cca_en": 390,
    "technology": "MF",
    "origin": "imported"
  },
  "alternatives": []
}
```

---

## Matching Engine

Defined in `matcher.py`. All data sources are loaded from the database at startup via `@lru_cache` and held in memory for fast lookups. Cache can be flushed from the admin dashboard.

### Layer Overview

| Priority | Layer | Data Source | Confidence |
|---|---|---|---|
| 0a | **Web Validation** | `web_battery_validation` — internet-sourced fitment data | 75–90% |
| 0b | **Real-World Inference** | `dial_battery_inference` — Dial-A-Battery historical orders | 80–95% |
| 1 | **Exact Match** | `vehicle_years` — fuzzy model ≥ 90 + exact year | 100% |
| 2 | **Soft Match** | `vehicle_years` — fuzzy model ≥ 60 + year within ±3 | 60–89% |
| 3 | **Rule-Based Fallback** | Engine CC + fuel → Ah bracket table | 40% |

Aliases (`model_aliases`) are applied between layers 1/2 and 3 to map international model names (e.g. "Civic") to their JDM dataset equivalents (e.g. "CIVIC FERIO").

### Flowchart

```mermaid
flowchart TD
    A([User Input: make / model / year / fuel_type / engine_cc]) --> B[Normalize\n_norm_model_key / _norm_fuel\nUPPERCASE / strip / collapse whitespace]
    B --> C{Layer 0a\nWeb Validation\nweb_battery_validation}

    C -->|Hit - conf 75-90| D[Resolve engine specs\nfrom vehicle_years]
    D --> WF[Parse battery code\n_lookup_battery_by_code\nexact then fuzzy then legacy parser]
    WF --> SEL

    C -->|Miss| E{Layer 0b\nReal-World Inference\ndial_battery_inference}
    E -->|Hit - conf 80-95\nhighest frequency + latest sale| G[Resolve engine specs\nfrom vehicle_years]
    G --> WF2[Parse battery code\n_lookup_battery_by_code\nhonour AGM/EFB tech from inference]
    WF2 --> SEL

    E -->|Miss| H{Layer 1 - Exact Match\nvehicle_years\nfuzzy model score >= 90\nexact year hit}
    H -->|Match - conf 100| I[Record make / model / year / CC / fuel]
    H -->|Soft - fuzzy >= 60\nyear +/-3 - conf 60-89| J[Record nearest year / CC / fuel]
    H -->|No match| K{Alias lookup\nmodel_aliases\nintl model to JDM model}

    I --> AH
    J --> AH

    K -->|Alias found\nfuzzy WRatio >= 75| M[Re-run fuzzy match\nwith JDM model name\nprefer exact year then +/-3]
    M --> AH
    K -->|No alias| N[Layer 3 - Rule-Based\nconf 40\nengine CC + fuel to Ah bracket\n_year_ah_modifier applied]
    N --> AH

    AH[_target_ah\nCC + fuel bracket\n+ year modifier -5 to +10] --> PT
    SEL --> PT[_preferred_tech\nLuxury = AGM\nHybrid = EFB\nStop-start + diesel/large = AGM\nStop-start standard = EFB\nNo stop-start = MF]
    PT --> RG[_make_region\nNS/JIS: Japanese / Korean / Chinese\nDIN: European / American / other]
    RG --> SB[_select_batteries\nFilter by region\nMatch Ah + preferred tech\nSort: imported before local\nFallback to nearest Ah if none]
    SB --> R([Return: primary + up to 6 alternatives\nconfidence / match_type\nmatched_make / matched_model / matched_year])
```

### Fuzzy Model Scoring

`_fuzzy_model_score_for_year()` runs three scorers in priority order, selecting candidates that exist near the requested year:

1. `partial_ratio` (≥ 80, query len ≥ 4) — catches prefix inputs like "COROLLA" → "COROLLA AXIO G"
2. `token_set_ratio` (≥ 72) — handles variant-token inputs like "MARCH ACTIVE" → "MARCH G"
3. `WRatio` (≥ 60) — legacy fallback

Among candidates that tie, selection prefers: semantic prefix match → exact year hit → smallest year delta → highest fuzzy score.

### Ah Bracket Rules

| Engine CC | Petrol (Ah) | Diesel (Ah) | Hybrid (Ah) |
|---|---|---|---|
| ≤ 1000 | 35 | 40 | 35 |
| ≤ 1600 | 45 | 50 | 45 |
| ≤ 2000 | 55 | 65 | 55 |
| ≤ 2500 | 70 | 80 | 65 |
| ≤ 3000 | 80 | 90 | 80 |
| ≤ 4000 | 90 | 100 | 90 |
| > 4000 | 100 | 120 | 100 |

Year modifier applied on top: `< 2000 → −5` · `2000–2011 → 0` · `2012–2017 → +5` · `≥ 2018 → +10`.

### Result Accuracy Bar

The result card renders a segmented accuracy bar (`AccuracyBar.tsx`) with four independently scored factors:

| Segment | Max | Color | Scoring |
|---|---|---|---|
| Car Found | 50 pts | Green | 50 for exact/real-world; 20–40 for close; 0 for fallback |
| Year | 25 pts | Blue | 25 exact; decreasing with delta; 0 if > 3 years off |
| Data Quality | 15 pts | Violet | 15 real-world source; 12 model found; 4 fallback |
| Engine Info | 10 pts | Amber | 10 model matched; 6 CC provided; 2 otherwise |

Total (0–100) shown as a percentage with a 0.7 s ease-out fill animation.

---

## Admin Dashboard

Protected under `/api/admin/*`. Access requires an HttpOnly session cookie issued by `POST /api/admin/login`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/admin/login` | Admin login (5/min) |
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
python pipelines/dataprep.py
```

Input: `New-CRSP---July-2025.xlsx` (not committed)
Output: `battery_lookup_dataset.csv`

### Pipeline 2 — Year Enrichment

```bash
python pipelines/enrich_years.py
```

Fetches production years from (in order): fueleconomy.gov bulk CSV → NHTSA VPIC → CarAPI → Wikidata/Wikipedia.
Results cached in `cache/year_cache.json` and `cache/fueleconomy_vehicles.csv`. Safe to delete to force a full re-fetch.

### Pipeline 3 — Dial-A-Battery Inference

```bash
python pipelines/dial_battery_clean.py
```

Input: `data/Dial-A-Battery Data - 2023-2026.xlsx`
Output: `dial_battery_inference` table

---

## Database Schema

Managed by Alembic (`alembic/versions/`). Apply all migrations with `alembic upgrade head`.

### Table Overview

| Table | Written by | Read by | Description |
|---|---|---|---|
| `vehicles_raw` | `dataprep.py` | pipelines | Cleaned CRSP vehicle records |
| `vehicle_years` | `enrich_years.py` | `matcher.py` | Per-make/model/year rows with CC + fuel |
| `vehicle_years_staging` | pipeline app | admin UI | Enriched rows pending admin review |
| `vehicle_years_versions` | admin UI | admin UI | One record per approved merge commit |
| `vehicle_years_changelog` | admin UI | admin UI | Row-level diffs for rollback |
| `vehicle_years_unmatched` | `enrich_years.py` | admin UI | Models that failed year enrichment |
| `battery_specs` | seed / admin upload | `matcher.py` | Battery catalogue (soft-delete via `deleted_at`) |
| `battery_audit_log` | `admin_router.py` | admin UI | Immutable change history |
| `model_aliases` | seed | `matcher.py` | International → JDM model name mappings |
| `dial_battery_inference` | `dial_battery_clean.py` | `matcher.py` | Real-world call-centre order data |
| `web_battery_validation` | pipeline app | `matcher.py` | Internet-validated fitment data |
| `web_battery_staging` | pipeline app | admin UI | Web validation rows pending review |
| `web_battery_validation_versions` | admin UI | admin UI | One record per approved web validation commit |
| `web_battery_validation_changelog` | admin UI | admin UI | Row-level diffs |
| `enrichment_cache_meta` | pipelines | admin UI | Cache download timestamps for external sources |
| `pipeline_run_log` | pipeline app | admin UI | Web validation run history |
| `fueleconomy_vehicles` | `enrich_years.py` | pipelines | fueleconomy.gov vehicle cache |
| `api_usage_quota` | pipelines | admin UI | Per-provider API call quotas (30-day rolling) |
| `admin_users` | `create_admin.py` | `admin_auth.py` | Admin credentials (bcrypt, cost 12) |
| `admin_sessions` | `admin_auth.py` | `admin_auth.py` | Active admin sessions (8-hour TTL) |
| `admin_stats` | `app.py` middleware | admin UI | Persisted usage counters |
| `app_settings` | admin UI | app | Key-value runtime configuration |
| `test_users` | `/api/auth/register` | `app.py` | Test user accounts |
| `test_user_sessions` | `/api/auth/login` | `app.py` | Test user tokens (24-hour TTL) |
| `user_feedback` | `/api/feedback` | admin UI | User feedback on recommendations |

### Core App Tables

Solid lines (`--`) are enforced foreign keys. Dashed lines (`..`) are logical references by value (no DB-level FK).

```mermaid
erDiagram
    admin_users {
        int id PK
        string username UK
        string password_hash
        datetime created_at
    }
    admin_sessions {
        int id PK
        string session_token UK
        int admin_id FK
        datetime created_at
        datetime expires_at
        string ip_address
    }
    admin_stats {
        int id PK
        string stat_key UK
        bigint stat_value
        datetime updated_at
    }
    app_settings {
        int id PK
        string setting_key UK
        string setting_value
        datetime updated_at
        string updated_by
    }
    battery_specs {
        int id PK
        string battery_code UK
        string model_key
        float ah
        float cca_en
        string technology
        string origin
        string brand
        datetime deleted_at
    }
    battery_audit_log {
        int id PK
        int battery_id FK
        string action
        string changed_by
        datetime changed_at
        text old_values
        text new_values
    }
    model_aliases {
        int id PK
        string make
        string international_model
        string jdm_model
        int priority
    }
    vehicle_years {
        int id PK
        string make
        string model
        int year
        int engine_capacity
        string fuel
        string source
        datetime created_at
        datetime updated_at
    }
    dial_battery_inference {
        int id PK
        text vehicle_type
        text vehicle_model
        text battery_code
        int frequency
        datetime last_sale_date
    }
    web_battery_validation {
        int id PK
        text make_n
        text model_n
        int year
        text battery_code
        int ah
        text technology
        text source
        int engine_cc
        string fuel_type
        datetime validated_at
    }
    test_users {
        int id PK
        string username UK
        string email UK
        string password_hash
        datetime created_at
        int is_active
    }
    test_user_sessions {
        int id PK
        string session_token UK
        int user_id FK
        datetime created_at
        datetime expires_at
        string ip_address
        string user_agent
        datetime last_seen_at
    }
    user_feedback {
        int id PK
        string vehicle_label
        int satisfaction
        string accuracy
        text wrong_parts
        text comments
        datetime submitted_at
        string ip_address
        int test_user_id FK
        string input_type
        int match_confidence
        string match_type
        string recommended_battery
    }

    admin_users      ||--o{ admin_sessions     : "admin_id → admin_users.id (CASCADE)"
    battery_specs    ||--o{ battery_audit_log  : "battery_id → battery_specs.id (SET NULL)"
    test_users       ||--o{ test_user_sessions : "user_id → test_users.id (CASCADE)"
    test_users       |o--o{ user_feedback      : "test_user_id → test_users.id (SET NULL)"
    battery_specs    }o..o{ dial_battery_inference  : "battery_code (logical ref)"
    battery_specs    }o..o{ web_battery_validation  : "battery_code (logical ref)"
    vehicle_years    }o..o{ web_battery_validation  : "make / model / year (logical ref)"
    vehicle_years    }o..o{ dial_battery_inference  : "vehicle_type / vehicle_model (logical ref)"
```

### Pipeline & Staging Tables

Solid lines (`--`) are enforced foreign keys. Dashed lines (`..`) show pipeline data flow (no DB-level FK).

```mermaid
erDiagram
    vehicles_raw {
        int id PK
        string make
        string model
        string model_number
        int engine_capacity
        string fuel
    }
    vehicle_years {
        int id PK
        string make
        string model
        int year
        int engine_capacity
        string fuel
        string source
    }
    vehicle_years_staging {
        int id PK
        text run_id
        string make
        string model
        int year
        int engine_capacity
        string fuel
        string source
        bool is_valid
        bool conflict
        text conflict_detail
        datetime staged_at
    }
    vehicle_years_versions {
        text id PK
        int version_number
        datetime committed_at
        text run_id
        int committed_count
        int updated_count
        int removed_count
        string committed_by
        string initiated_by
    }
    vehicle_years_changelog {
        int id PK
        text version_id FK
        string make
        string model
        int year
        text change_type
        text old_values
        text new_values
    }
    vehicle_years_unmatched {
        int id PK
        text run_id
        string make
        string model
        string fuel
        datetime recorded_at
    }
    web_battery_validation {
        int id PK
        text make_n
        text model_n
        int year
        text battery_code
        text run_id
        text version_id
    }
    web_battery_staging {
        int id PK
        text run_id
        text make_n
        text model_n
        int year
        text battery_code
        int ah
        text technology
        bool is_valid
        bool conflict
        datetime staged_at
    }
    web_battery_validation_versions {
        text id PK
        int version_number
        datetime committed_at
        text run_id
        int committed_count
        int removed_count
        text committed_by
        text initiated_by
    }
    web_battery_validation_changelog {
        int id PK
        text version_id FK
        text make_n
        text model_n
        int year
        text change_type
        text old_values
        text new_values
    }
    enrichment_cache_meta {
        text key PK
        datetime downloaded_at
        bigint file_size_bytes
        int record_count
        datetime updated_at
    }
    pipeline_run_log {
        int id PK
        text run_id
        text status
        datetime finished_at
        int combos_processed
        int combos_matched
    }
    fueleconomy_vehicles {
        int id PK
        int year
        string make
        string model
    }
    api_usage_quota {
        int id PK
        string provider
        string month
        int calls_made
        int quota_limit
        datetime period_start
        datetime period_end
    }

    vehicle_years_versions          ||--o{ vehicle_years_changelog          : "version_id → vehicle_years_versions.id (CASCADE)"
    web_battery_validation_versions ||--o{ web_battery_validation_changelog : "version_id → web_battery_validation_versions.id (CASCADE)"
    vehicles_raw                    }o..o{ vehicle_years                    : "dataprep.py produces"
    fueleconomy_vehicles            }o..o{ vehicle_years                    : "enrich_years.py populates from"
    vehicle_years_staging           }o..|| vehicle_years                    : "admin commit merges into"
    web_battery_staging             }o..|| web_battery_validation           : "admin commit merges into"
    web_battery_validation_versions |o..o{ web_battery_validation          : "version_id (run tracking)"
```

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
                                          sessions, audit)

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
