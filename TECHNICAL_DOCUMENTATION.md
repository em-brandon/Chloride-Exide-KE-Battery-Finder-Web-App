# Chloride Exide KE — Battery Finder: Technical Documentation

**Version:** 1.0 | **Date:** 2026-05-28 | **Stack:** FastAPI · PostgreSQL · React 19 · TypeScript · Tailwind CSS v4

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level System Diagram](#2-high-level-system-diagram)
3. [Backend Architecture](#3-backend-architecture)
4. [Database Schema](#4-database-schema)
5. [The Matching Engine — Deep Dive](#5-the-matching-engine--deep-dive)
6. [Matching Mode 1: Select Mode](#6-matching-mode-1-select-mode)
7. [Matching Mode 2: Type Mode](#7-matching-mode-2-type-mode)
8. [Authentication & Security](#8-authentication--security)
9. [Admin Dashboard API](#9-admin-dashboard-api)
10. [Frontend Architecture](#10-frontend-architecture)
11. [Data Pipelines](#11-data-pipelines)
12. [Rate Limiting & Observability](#12-rate-limiting--observability)
13. [Deployment & Environment](#13-deployment--environment)

---

## 1. System Overview

The Battery Finder is a production web application that recommends the correct car battery for Kenyan vehicles. Users enter their vehicle details — make, model, year, fuel type, and engine CC — and the system returns a primary battery recommendation with same-technology alternatives. The application is geo-restricted to Kenya and is built to serve the Chloride Exide KE brand.

**Core technologies:**

| Layer       | Technology                                                        |
|-------------|-------------------------------------------------------------------|
| Backend API | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, slowapi           |
| Matching    | pandas DataFrames, rapidfuzz (fuzzy text matching), rule engine   |
| Database    | PostgreSQL (connection pool: 10 + 15 overflow)                    |
| Frontend    | React 19, TypeScript, Vite, Tailwind CSS v4, Bun                  |
| Auth        | bcrypt (cost 12), HttpOnly cookies (admin), Bearer tokens (tests) |
| Serving     | Uvicorn (ASGI); FastAPI serves the built React SPA                |

---

## 2. High-Level System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CLIENT BROWSER                                    │
│                                                                              │
│  ┌──────────────────────────┐      ┌─────────────────────────────────────┐  │
│  │   Public Battery Finder  │      │      Admin Dashboard (/admin/*)     │  │
│  │  (VehicleFinderForm.tsx) │      │  (AdminBatteries, Audit, Feedback,  │  │
│  │  React 19 + TypeScript   │      │   Sessions, DataPipeline pages)     │  │
│  └────────────┬─────────────┘      └────────────────┬────────────────────┘  │
│               │  GET /api/makes                     │  POST /api/admin/login │
│               │  GET /api/models/:make              │  GET  /api/admin/*     │
│               │  GET /api/years?make=&model=        │  (HttpOnly cookie auth) │
│               │  POST /api/recommend                │                        │
│               │  POST /api/feedback                 │                        │
└───────────────┼─────────────────────────────────────┼────────────────────────┘
                │  HTTP/JSON                          │  HTTP/JSON
                ▼                                     ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend (app.py)                             │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                       Middleware Stack                                │   │
│  │  1. HTTP Request arrives at Uvicorn ASGI server                      │   │
│  │  2. slowapi rate-limit check (by client IP)                          │   │
│  │  3. count_reads_middleware  — increments in-memory counter if POST   │   │
│  │     /api/recommend (flushed to DB every 60 s by background timer)   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────┐   ┌────────────────────────┐   ┌──────────────────┐  │
│  │  Public Routes   │   │   Admin Router         │   │  Static Files    │  │
│  │  /api/makes      │   │  /api/admin/*          │   │  /assets/*       │  │
│  │  /api/models/:m  │   │  (admin_router.py)     │   │  /static/*       │  │
│  │  /api/years      │   │  requires HttpOnly      │   │  /* → index.html │  │
│  │  /api/recommend  │   │  session cookie         │   │  (SPA fallback)  │  │
│  │  /api/feedback   │   └────────────────────────┘   └──────────────────┘  │
│  │  /api/auth/*     │                                                        │
│  └────────┬─────────┘                                                        │
│           │  calls                                                           │
│           ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     matcher.py  (Rule Engine)                        │    │
│  │                                                                      │    │
│  │   In-memory LRU Cache (warmed at startup, cleared on admin update)  │    │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────┐  ┌───────────┐  │    │
│  │   │ _vehicles()  │  │ _batteries() │  │_aliases()│  │_inference │  │    │
│  │   │ vehicle_years│  │battery_specs │  │  model_  │  │dial_batt_ │  │    │
│  │   │ → DataFrame  │  │ → DataFrame  │  │ aliases  │  │inference  │  │    │
│  │   └──────────────┘  └──────────────┘  └──────────┘  └───────────┘  │    │
│  │                                                                      │    │
│  │   recommend() — 4-layer matching pipeline                           │    │
│  │   Layer 0: Inference (real-world order data)    → confidence 80–95  │    │
│  │   Layer 1: Exact match (make+model+year)        → confidence 90–100 │    │
│  │   Layer 2: Soft match (±3 year window)          → confidence 60–89  │    │
│  │   Layer 3: Rule-based (engine_cc + fuel type)   → confidence 40     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│           │                                                                  │
│           ▼                                                                  │
└──────────────────────────────────────────────────────────────────────────────┘
                │  SQLAlchemy 2.0 (pool_size=10, max_overflow=15)
                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         PostgreSQL Database                                   │
│                                                                              │
│  Runtime tables (read by matcher at startup):                                │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────┐  ┌─────────────┐ │
│  │ vehicle_years │  │ battery_specs │  │ model_aliases  │  │dial_battery │ │
│  │ (make/model/  │  │ (battery SKUs │  │ (intl→JDM      │  │_inference   │ │
│  │  year/cc/fuel)│  │  soft-delete) │  │  name maps)    │  │(order data) │ │
│  └───────────────┘  └───────────────┘  └────────────────┘  └─────────────┘ │
│                                                                              │
│  Admin / audit tables (written by dashboard):                                │
│  ┌──────────────┐  ┌────────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │ admin_users  │  │ admin_sessions │  │battery_audit_ │  │ admin_stats │  │
│  │              │  │                │  │     log       │  │(db_reads)   │  │
│  └──────────────┘  └────────────────┘  └───────────────┘  └─────────────┘  │
│                                                                              │
│  User tables:                                                                │
│  ┌──────────────┐  ┌───────────────────┐  ┌─────────────────────────────┐  │
│  │  test_users  │  │test_user_sessions │  │       user_feedback         │  │
│  └──────────────┘  └───────────────────┘  └─────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Backend Architecture

### 3.1 Entry Point: `app.py`

`app.py` is the FastAPI application root. On startup (via the `lifespan` async context manager) it:

1. Verifies PostgreSQL connectivity with a `SELECT 1`.
2. Warms all four LRU caches in `matcher.py` so the first user request is not cold.
3. Starts a background `threading.Timer` that flushes the in-memory read counter to `admin_stats` every 60 seconds.
4. Schedules a midnight `threading.Timer` that resets the daily read counter to zero.

**Public API routes registered in `app.py`:**

| Method | Path                  | Rate Limit | Description                                         |
|--------|-----------------------|------------|-----------------------------------------------------|
| GET    | `/api/makes`          | 20/min     | Returns sorted list of all vehicle makes            |
| GET    | `/api/models/:make`   | 20/min     | Returns models for a given make                     |
| GET    | `/api/years`          | 20/min     | Returns available years for make + model            |
| POST   | `/api/recommend`      | 10/min     | Main recommendation endpoint (triggers read counter)|
| POST   | `/api/feedback`       | 5/min      | Stores user feedback after a recommendation         |
| POST   | `/api/auth/register`  | 5/min      | Register a test-user account                        |
| POST   | `/api/auth/login`     | 10/min     | Log in as test user, returns Bearer token           |
| POST   | `/api/auth/logout`    | —          | Invalidate test-user Bearer token                   |
| GET    | `/api/auth/me`        | —          | Get current test-user info from Bearer token        |
| GET    | `/{full_path}`        | —          | SPA fallback: serves React `index.html`             |

**`POST /api/recommend` request body:**

```json
{
  "make":       "TOYOTA",
  "model":      "Corolla",
  "year":       2015,
  "engine_cc":  1500,
  "fuel_type":  "Petrol",
  "stop_start": true
}
```

**`POST /api/recommend` response:**

```json
{
  "make":           "TOYOTA",
  "model":          "COROLLA",
  "year":           2015,
  "engine_cc":      1496,
  "fuel_type":      "PETROL",
  "battery_region": "NS",
  "recommended_ah": 45,
  "preferred_tech": "EFB",
  "confidence":     100,
  "match_type":     "Exact Match",
  "matched_make":   "TOYOTA",
  "matched_model":  "COROLLA AXIO G",
  "matched_year":   2015,
  "primary": {
    "battery_code": "NS60 POWERLAST EFB",
    "model_key":    "NS60",
    "ah":           45,
    "cca_en":       430,
    "technology":   "EFB",
    "origin":       "imported"
  },
  "alternatives": [...]
}
```

> **Note:** `confidence` and `match_type` are returned in every response but are no longer displayed as raw numbers or labels to end users. The frontend translates them into the **Result Accuracy bar** (`AccuracyBar.tsx`) — a four-segment coloured strip that communicates match quality visually (see §10.2).

### 3.2 Read Counter Middleware

Every `POST /api/recommend` request increments `_read_counter_pending` (in-memory integer, thread-safe via `threading.Lock`). A `threading.Timer` fires every 60 seconds to write the accumulated delta to `admin_stats` in a single SQL `UPDATE`. This avoids a DB write on every recommendation while still persisting the count across restarts. The counter resets to zero at local midnight via a second scheduled timer.

### 3.3 Static File Serving & Maintenance Mode

`app.py` mounts:
- `/assets/*` — Vite-built JS/CSS chunks from `frontend/dist/assets/`
- `/static/*` — raw static files (maintenance page, logos)
- `/{full_path}` catch-all — returns React `index.html` for all non-API paths (SPA client-side routing)

If `MAINTENANCE_MODE=true` is set in environment variables, the catch-all returns `static/maintenance.html` instead of the React app. Static assets continue to load normally during maintenance.

---

## 4. Database Schema

All migrations are managed by **Alembic** (in `alembic/versions/`). Run `alembic upgrade head` after pulling.

### 4.1 Runtime Tables (read by matcher)

**`vehicle_years`** — Primary vehicle lookup table. One row per make/model/year combination.

| Column           | Type         | Constraints          | Description                      |
|------------------|--------------|----------------------|----------------------------------|
| id               | Integer      | PK, autoincrement    |                                  |
| make             | String(100)  | NOT NULL             | e.g. "TOYOTA"                    |
| model            | String(200)  | NOT NULL             | e.g. "COROLLA AXIO G"            |
| year             | Integer      | NOT NULL             | e.g. 2015                        |
| engine_capacity  | Integer      | nullable             | Engine CC e.g. 1496              |
| fuel             | String(50)   | nullable             | "Petrol", "Diesel", "Hybrid"     |

Unique constraint: `(make, model, year)`. Indexes on `make` and `(make, model)`.

**`battery_specs`** — Battery catalogue. One row per battery SKU.

| Column       | Type         | Constraints          | Description                          |
|--------------|--------------|----------------------|--------------------------------------|
| id           | Integer      | PK                   |                                      |
| battery_code | String(100)  | NOT NULL, UNIQUE     | e.g. "NS60 POWERLAST EFB"            |
| model_key    | String(100)  | NOT NULL             | e.g. "NS60" (standard size group)    |
| ah           | Float        | nullable             | Amp-hour capacity                    |
| cca_en       | Float        | nullable             | Cold Cranking Amps (EN standard)     |
| technology   | String(100)  | nullable             | "MF", "EFB", "AGM", "SB (Flooded)"  |
| origin       | String(50)   | nullable             | "imported" or "local"                |
| brand        | String(100)  | nullable             | e.g. "Powerlast", "Sebang"           |
| deleted_at   | DateTime(tz) | nullable             | Soft-delete timestamp                |

Always filter `deleted_at IS NULL` when querying active batteries. Indexes on `model_key` and `ah`.

**`model_aliases`** — International → JDM model name mappings.

| Column              | Type         | Description                                  |
|---------------------|--------------|----------------------------------------------|
| id                  | Integer      | PK                                           |
| make                | String(100)  | e.g. "TOYOTA"                                |
| international_model | String(200)  | User-facing name e.g. "COROLLA"              |
| jdm_model           | String(200)  | Dataset name e.g. "AXIO", "FIELDER"          |
| priority            | Integer      | Lower = preferred (used for tie-breaking)    |

**`dial_battery_inference`** — Real-world call-centre order data (what batteries were actually sold per vehicle type/model).

| Column          | Type      | Description                                   |
|-----------------|-----------|-----------------------------------------------|
| vehicle_type    | String    | Make (e.g. "TOYOTA")                          |
| vehicle_model   | String    | Model (e.g. "COROLLA")                        |
| battery_code    | String    | The battery that was sold                     |
| frequency       | Integer   | How many times this battery was sold for this vehicle |
| last_sale_date  | DateTime  | Most recent sale date                         |

### 4.2 Admin / Audit Tables

**`admin_users`** — Admin credentials (bcrypt, cost 12). Written by `create_admin.py`.

**`admin_sessions`** — One row per active admin login. 8-hour TTL. Token is a 64-char hex string (32 random bytes).

**`battery_audit_log`** — Immutable change history for `battery_specs`. One row per INSERT/UPDATE/DELETE. Stores old/new values as JSON strings.

**`admin_stats`** — Key-value store for persisted counters. Currently stores `db_reads` (daily recommendation count).

### 4.3 User Tables

**`user_feedback`** — One row per feedback submission. Captures satisfaction (1–5 stars), accuracy rating (exact/close/wrong/unsure), wrong parts flagged, comments, IP, and match metadata.

**`test_users`** — Registered test-user accounts (bcrypt hashed passwords).

**`test_user_sessions`** — Bearer-token sessions for test users. 24-hour TTL, stored in client `localStorage`.

---

## 5. The Matching Engine — Deep Dive

`matcher.py` is the recommendation core. It runs entirely in-process, using four pandas DataFrames held in LRU caches for O(1) repeated access. No database is hit during a recommendation request.

### 5.1 Data Loading & Caching

At startup, `app.py` calls four cache-warming functions:

```
matcher._vehicles()      → SELECT make, model, year, engine_capacity, fuel FROM vehicle_years
matcher._batteries()     → SELECT battery_code, model_key, ah, cca_en, technology, origin FROM battery_specs WHERE deleted_at IS NULL
matcher._model_aliases() → SELECT make, international_model, jdm_model, priority FROM model_aliases
matcher._inference()     → SELECT vehicle_type, vehicle_model, battery_code, frequency, last_sale_date FROM dial_battery_inference
```

Each function is decorated with `@lru_cache(maxsize=1)`. The cache is invalidated (`.cache_clear()`) whenever the admin updates battery specs via the dashboard or explicitly triggers a cache refresh. Immediately after clearing, the cache is re-warmed in-process.

**Normalised columns added at load time:**

- `make_n` — uppercase + strip + collapse whitespace
- `model_n` — result of `_norm_model_key()`: uppercase, hyphens → space, letter↔digit boundary spaces inserted (`CX5` → `CX 5`)
- `fuel_n` — mapped through `_FUEL_MAP` (handles typos like "DEISEL" → "DIESEL")
- `vtype_n`, `vmodel_n`, `bcode_n` — same normalisation for inference table

### 5.2 The `recommend()` Function — 4-Layer Pipeline

```
recommend(make, model, year, engine_cc, fuel_type, stop_start) → dict
```

**Pre-processing:**

1. Normalise `make_n` = `make.upper().strip()`
2. Normalise `model_n` = `_norm_model_key(model)` (hyphen removal, letter/digit spacing)
3. Set defaults: `resolved_cc = engine_cc or 1500`, `resolved_fuel = _norm_fuel(fuel_type)`
4. Set `confidence = 40`, `match_type = "Estimated (Rule-Based)"` as defaults

The engine then tries layers in order and **returns at the first successful match**.

---

## Layer 0: Inference Match (Real-World Order Data)

**What it does:** Looks up the `dial_battery_inference` table first. This table contains actual Dial-A-Battery call-centre sales data — if a battery was sold for a Toyota Corolla 100 times, that's the authoritative answer.

**How it works:**

1. Filter inference rows where `vtype_n == make_n`.
2. Check if `model_n` exists exactly in `vmodel_n` choices → confidence 95.
3. If not, fuzzy match with `token_set_ratio ≥ 85` → confidence 80.
4. Among all rows for the matched (make, model), pick the battery with the **highest frequency** (tiebreak: most recent `last_sale_date`).
5. Look up that battery code in `battery_specs` (exact → fuzzy → legacy parser) to get `(target_ah, technology)`.
6. **Technology override logic:**
   - If `stop_start=False` → compute preferred tech from rules (always MF or lower).
   - If inference returned AGM or EFB → honour it (deliberate upgrade by call centre).
   - If inference returned MF and `stop_start=True` → recompute via `_preferred_tech()` (MF in inference often means wrong recommendation; we fix it for i-stop vehicles).
7. Call `_select_batteries(target_ah, pref_tech, region)` and return.

**Return confidence:** 80 (fuzzy model match) or 95 (exact model match). `match_type = "Real-World Data Match"`. The frontend `AccuracyBar` awards full scores for both Car Found and Data Quality segments when this layer fires.

---

## Layer 1: Exact Match

Reached only if inference had no hit.

**Step 1 — Make resolution:**
Filter `vehicle_years` to rows where `make_n == make_n`. If no rows found, fuzzy-match the make against all known makes using `fuzz.WRatio ≥ 75`.

**Step 2 — Model fuzzy match (`_fuzzy_model_score_for_year`):**
This function is the core of input-to-database matching. It runs three scorers in order:

```
1. fuzz.partial_ratio    (threshold ≥ 80, only if len(query) ≥ 4)
   — catches prefix inputs: "COROLLA" matches "COROLLA AXIO G"

2. fuzz.token_set_ratio  (threshold ≥ 72)
   — catches variant-token inputs: "MARCH ACTIVE" matches "MARCH G"
   — ignores word order and extra tokens

3. fuzz.WRatio           (threshold ≥ 60)
   — general-purpose weighted ratio fallback
```

For each scorer, instead of just returning the top-scoring candidate, it collects **all** candidates above threshold and picks the best using a multi-key sort:

```
Priority key: (starts_with_query, is_exact_year, -year_delta, score, model_n)
```

`starts_with_query` = 1 if the candidate model name starts with the user's input. This prevents "FIT" from being hijacked by a longer "FIT SPORT" when "FIT SHUTTLE" (which the user's year matches) also scores 100.

**Step 3a — Exact year match:**
Filter the matched model's rows for `year == year`. If found:
- `confidence = 100` if model_score ≥ 90, else `int(model_score)`
- `match_type = "Exact Match"` if model_score ≥ 90, else `"Close Match"`
- `resolved_cc` and `resolved_fuel` taken from this row (dataset is authoritative).
- AccuracyBar: Car Found fills to 50/50; Year fills to 25/25 (zero delta).

---

## Layer 2: Soft Year Match

Reached if no exact year row was found for the matched model.

**Step 3b — ±3 year window:**
Filter matched model's rows where `year ∈ [year-3, year+3]`. Pick the row with the closest year.

```
year_delta  = |nearest["year"] - requested_year|
confidence  = max(60, int(model_score) - year_delta * 3)
match_type  = "Close Match"
```

Example: model score 85, year delta 2 → `confidence = max(60, 85 - 6) = 79`.

AccuracyBar Year segment: delta 0 → 25 pts, delta 1 → 20, delta 2 → 13, delta 3 → 8. Car Found segment fills proportionally to the model_score (20–40 out of 50 pts in close-match range).

---

## Layer 2b: Alias Resolution (runs after Layer 2 fails)

If no match was found at all (`matched_year is None`) but `enable_aliases=True`, the engine tries international→JDM model name aliases:

1. Filter `model_aliases` for the current make.
2. Fuzzy-match `model_n` against `intl_model_n` values using `fuzz.WRatio ≥ 75`.
3. For each matching alias, look up its `jdm_model_n` values and fuzzy-match those against the vehicle dataset.
4. From all resolved candidates, pick the best by: exact year first, then smallest year delta, then highest alias priority, then highest JDM similarity score.
5. Re-run Steps 3a/3b with the resolved JDM model name.

This is how a user typing "COROLLA" gets matched to "COROLLA AXIO G" or "COROLLA FIELDER" — the alias table maps "COROLLA" to multiple JDM trim names, and the engine picks the one whose year range best overlaps with the requested year.

---

## Layer 3: Rule-Based Fallback

Reached if all matching layers failed (confidence remains 40). AccuracyBar: Car Found = 0, Data Quality = 4 (minimum), Engine Info proportional to whether the CC was non-default. An amber warning banner is shown above the result card when this layer fires (`matched_make` is `null` in the response).

**`_target_ah(engine_cc, fuel, year)`** — Ah bracket lookup table:

| Max CC (inclusive) | Petrol Ah | Diesel Ah | Hybrid Ah |
|--------------------|-----------|-----------|-----------|
| 1000               | 35        | 40        | 35        |
| 1600               | 45        | 50        | 45        |
| 2000               | 55        | 65        | 55        |
| 2500               | 70        | 80        | 65        |
| 3000               | 80        | 90        | 80        |
| 4000               | 90        | 100       | 90        |
| 9999+              | 100       | 120       | 100       |

**Year modifier** (only applied in rule-based mode):

| Year range   | Modifier |
|--------------|----------|
| ≥ 2018       | +10 Ah   |
| 2012–2017    | +5 Ah    |
| 2000–2011    | 0        |
| < 2000       | -5 Ah    |

**`_preferred_tech(engine_cc, fuel, year, make, stop_start)`** — Technology selection:

| Condition                                               | Technology |
|---------------------------------------------------------|------------|
| EV fuel type                                            | MF         |
| Luxury/premium make (BMW, Mercedes, Lexus, Audi, etc.) | AGM        |
| Hybrid fuel type                                        | EFB        |
| stop_start=True AND (Diesel OR engine_cc ≥ 2500)       | AGM        |
| stop_start=True (standard petrol)                       | EFB        |
| stop_start=False                                        | MF         |

**Battery region detection (`_make_region`):**

| Region | Makes                                                                     |
|--------|---------------------------------------------------------------------------|
| NS     | Toyota, Honda, Nissan, Mazda, Subaru, Isuzu, Mitsubishi, Hyundai, Kia, + Chinese makes |
| DIN    | Audi, BMW, Mercedes, VW, Ford, Chevrolet, Peugeot, Renault, Fiat, Tata, etc. |

This determines whether the `battery_specs` pool is filtered to NS-standard or DIN-standard batteries (detected from the `Model Key` prefix: "DIN..." → DIN, all others → NS).

---

## Battery Selection (`_select_batteries`)

Once `target_ah`, `preferred_tech`, and `region` are known:

1. Filter `battery_specs` to the correct region.
2. Filter to rows where `Ah == target_ah`.
3. Sort by technology preference order: `EFB > AGM > MF > SB (Flooded)`.
4. Within same technology, sort by origin: `imported` batteries listed before `local`.
5. If `preferred_tech` is in stock at `target_ah` → select that as primary.
6. If not → pick best available technology at same Ah.
7. If nothing at `target_ah` → find nearest Ah in any technology.
8. **Alternatives:** same Ah + same technology + same CCA as the primary, capped at 6. Sorted with imported first.

---

## 6. Matching Mode 1: Select Mode

Select mode is the default user experience. The form uses three cascading dropdowns.

**Interaction flow:**

```
User selects Make (dropdown)
  → GET /api/makes (loaded on page mount, cached in React state)
  → handleMakeChange() fires GET /api/models/:make
  → models dropdown is populated

User selects Model
  → handleModelChange() fires GET /api/years?make=&model=
  → years dropdown is populated

User selects Year
  → form is ready; user may also choose Fuel Type and Engine CC (optional in select mode)

User clicks "Find Battery"
  → POST /api/recommend with { make, model, year, fuel_type?, engine_cc?, stop_start }
```

**Why select mode can still use fuzzy matching:** The API route sends the model name as it appears in the database (since the user picked it from a dropdown that was populated from `GET /api/models`). However, the matcher still normalises it through `_norm_model_key()` and performs an exact match against `model_n` in the DataFrame. If the exact key is found, it bypasses fuzzy matching entirely (score = 100.0).

**Confidence in select mode:**

- When a model is chosen from the dropdown, it exactly matches a `model_n` key in the database → model_score = 100.
- If the year is in the database → confidence = 100, "Exact Match".
- If the year is not in the database but within ±3 years → confidence = 60–97, "Close Match".
- If no year window match → falls through to rule-based, confidence = 40.

---

## 7. Matching Mode 2: Type Mode

Type mode allows free-text entry. This is where the full fuzzy matching pipeline matters.

**Interaction flow:**

```
User types make, model, year in free-text inputs
User must also provide Fuel Type and Engine CC (required in type mode)

User clicks "Find Battery"
  → POST /api/recommend with all fields
```

**Estimated confidence indicator (frontend only):**
Before submitting, the form shows a live confidence estimate to encourage users to fill in all fields:

| Fields filled                           | Shown confidence | Label                               |
|-----------------------------------------|------------------|-------------------------------------|
| Make only                               | 40%              | "Low — only make entered"           |
| Make + Model                            | 55%              | "Fair — add year, fuel, engine"     |
| Make + Model + Year                     | 70%              | "Good — add fuel & engine size"     |
| Make + Model + Year + Fuel + Engine CC  | 85%              | "High — all details provided"       |

This estimate disappears once the form is submitted and re-appears only when all fields are cleared.

**Type mode fuzzy matching in the backend:**

1. `make_n = make.upper().strip()` — no fuzzy on make initially; if no vehicle rows are found, a `fuzz.WRatio ≥ 75` make-level fuzzy pass runs.
2. `model_n = _norm_model_key(model)` — normalises separators, inserts letter/digit spaces.
3. `_fuzzy_model_score_for_year(model_n, make_df, year)` — runs partial_ratio / token_set_ratio / WRatio with year-proximity tie-breaking (described in Layer 1 above).
4. If no match found, alias resolution tries to map the typed name to a JDM equivalent.

**Stop-start inference:** If the user doesn't check the stop-start toggle, `_infer_stop_start(make, year, fuel)` is called to auto-detect likely stop-start vehicles:

| Make + condition                                    | Inferred stop-start from year |
|-----------------------------------------------------|-------------------------------|
| Honda, Mazda                                        | ≥ 2012                        |
| BMW, Mercedes, Audi, VW                             | ≥ 2011                        |
| Ford, Peugeot, Renault, Citroën                     | ≥ 2013                        |
| Toyota, Nissan (petrol only)                        | ≥ 2014                        |
| Any Hybrid                                          | Always                        |

---

## 8. Authentication & Security

### 8.1 Admin Authentication (`admin_auth.py`)

Admin accounts use **bcrypt** (cost 12) for password storage. Sessions are tracked in the `admin_sessions` database table.

**Login flow:**
1. `POST /api/admin/login` with username + password.
2. bcrypt hash comparison runs regardless of whether the user exists (prevents timing attacks via dummy hash).
3. On success: generate 64-char hex token (`secrets.token_hex(32)`), insert `AdminSession` row (expires in 8 hours), set `HttpOnly; Secure; SameSite=Strict` cookie.

**Per-request auth:**
Every admin endpoint uses `Depends(require_admin)`. This dependency reads the `admin_session` cookie, looks up the `AdminSession` row, checks expiry, deletes expired sessions automatically, and returns the `AdminUser`.

**Cookie security properties:**
- `HttpOnly` — JavaScript cannot read the token (XSS mitigation).
- `SameSite=Strict` — Blocks CSRF from cross-origin requests.
- `Secure` — HTTPS only in production (disabled for local HTTP dev via `ADMIN_COOKIE_SECURE=false`).
- 8-hour TTL.

### 8.2 Test-User Authentication

Test users are registered via `POST /api/auth/register` and authenticate via `POST /api/auth/login`. Sessions use Bearer tokens stored in client `localStorage` (not cookies). TTL is 24 hours. The token is included as `Authorization: Bearer <token>` on feedback submissions to associate feedback with a user account.

### 8.3 Rate Limiting

All public endpoints are rate-limited via `slowapi` (keyed by client IP):

| Endpoint           | Limit    |
|--------------------|----------|
| `/api/recommend`   | 10/min   |
| `/api/feedback`    | 5/min    |
| `/api/makes`, `/api/models`, `/api/years` | 20/min |
| `/api/auth/*`      | 5–10/min |
| `/api/admin/login` | 5/min    |

On rate limit exceeded, the API returns HTTP 429 with a `retry_after` field.

---

## 9. Admin Dashboard API

All routes are mounted under `/api/admin/` (from `admin_router.py`) and require a valid admin session cookie.

### 9.1 Stats & Health

| Endpoint               | Description                                                    |
|------------------------|----------------------------------------------------------------|
| `GET /api/admin/stats` | Row counts for all tables + today's recommendation count       |
| `GET /api/admin/health`| DB connectivity, latency_ms, connection pool utilisation       |

Health status is `"ok"` (latency < 500ms and pool < 85% used), `"degraded"`, or `"down"`.

### 9.2 Battery CRUD

| Endpoint                           | Description                                              |
|------------------------------------|----------------------------------------------------------|
| `GET /api/admin/batteries`         | Paginated list; supports search and technology filter    |
| `POST /api/admin/batteries`        | Add a new battery (writes audit log, clears cache)       |
| `PATCH /api/admin/batteries/:id`   | Update a battery (writes audit log, clears cache)        |
| `DELETE /api/admin/batteries/:id`  | Soft-delete a battery (writes audit log, clears cache)   |
| `POST /api/admin/batteries/upload` | Bulk upsert from .xlsx file (max 10 MB, via `upload_pipeline.py`) |
| `GET /api/admin/batteries/export`  | Download all active batteries as .xlsx                   |

Every mutation clears and re-warms the `matcher._batteries()` LRU cache instantly so new batteries are visible to the next recommendation request.

### 9.3 Audit Log

`GET /api/admin/audit` — Returns paginated battery change history with filters for action type (INSERT/UPDATE/DELETE), admin username, battery code, and date range. Each entry has `old_values` and `new_values` as JSON objects.

### 9.4 Cache Management

`POST /api/admin/cache/refresh` — Clears all four matcher caches (`_vehicles`, `_batteries`, `_model_aliases`, `_inference`) and re-warms them immediately. Used after running data pipelines.

### 9.5 Feedback Reports

| Endpoint                              | Description                              |
|---------------------------------------|------------------------------------------|
| `GET /api/admin/feedback`             | Paginated feedback with accuracy filter  |
| `GET /api/admin/feedback/summary`     | Aggregate stats (avg satisfaction, etc.) |
| `GET /api/admin/feedback/export-pdf`  | Full report as PDF (ReportLab)           |
| `GET /api/admin/feedback/export-csv`  | Full report as CSV                       |

### 9.6 Session Management

| Endpoint                               | Description                                |
|----------------------------------------|--------------------------------------------|
| `GET /api/admin/sessions`              | List admin's own active sessions           |
| `DELETE /api/admin/sessions/:id`       | Revoke an admin session                    |
| `GET /api/admin/test-sessions`         | List all test-user sessions (admin view)   |
| `DELETE /api/admin/test-sessions/:id`  | Revoke a test-user session                 |
| `GET /api/admin/test-users`            | List all test user accounts                |

---

## 10. Frontend Architecture

### 10.1 Stack

| Concern     | Technology                                     |
|-------------|------------------------------------------------|
| Framework   | React 19 (concurrent mode)                     |
| Language    | TypeScript (strict mode)                       |
| Build tool  | Vite + Bun                                     |
| Styling     | Tailwind CSS v4 + custom CSS variables         |
| Icons       | Lucide React + Heroicons                       |
| HTTP client | Native `fetch` with typed wrappers in `lib/api.ts` |
| Routing     | React Router (SPA, served by FastAPI catch-all) |

In development, Vite proxies `/api/*` to `localhost:8000`. In production, FastAPI serves the built `frontend/dist/` directory.

### 10.2 Key Components

**`VehicleFinderForm.tsx`** (`frontend/src/components/`) — The main public-facing search form. It manages all form state in local React state (no external state manager):

- `makes`, `models`, `years` — populated from cascading API calls in Select mode.
- `typeMode` boolean — switches between Select and Type input modes.
- `istop` boolean — i-stop (stop-start) toggle, defaults to `true`.
- Estimated confidence bar (type mode only) — calculated from which fields are filled, shown before submission to guide the user.
- On submit: calls `fetchRecommendation()`, renders `ResultPanel` inline.
- `ResultPanel` — displays primary battery (Ah, CCA, technology, battery code), segmented **Result Accuracy bar** (`AccuracyBar.tsx`), same-technology alternatives grid, an amber fallback warning when no model was matched (`matched_make` is null), and "Rate this result" feedback trigger.

**`AccuracyBar.tsx`** (`frontend/src/components/`) — Four-segment coloured accuracy bar rendered below every recommendation. Each segment's width is proportional to its maximum possible contribution to the total score (Car Found 50 pts, Year 25 pts, Data Quality 15 pts, Engine Info 10 pts). Each segment fills with an animated colour based on the actual match quality computed from `match_type`, `confidence`, `matched_year`, and `matched_make` in the API response:

| Segment | Colour | Max | What it measures |
| --- | --- | --- | --- |
| Car Found | Green `#10b981` | 50 | Whether the vehicle was found in the database (0 if rule-based fallback) |
| Year | Blue `#3b82f6` | 25 | Year delta from matched row (25 exact, 20 delta-1, 13 delta-2, 8 delta-3) |
| Data Quality | Purple `#8b5cf6` | 15 | Data source: real-world (15), dataset (12), engine estimate (4) |
| Engine Info | Amber `#f59e0b` | 10 | Whether engine details came from the database or were inferred |

The total score (0–100) is displayed as a percentage alongside the bar. Uses inline styles for compatibility with both Tailwind and legacy CSS contexts.

**`ResultCard.tsx`** (`frontend/src/components/`) — An alternate result display used in other parts of the app. Renders the same data with Tailwind classes, includes `AccuracyBar`, the amber fallback warning, and supports the Exide Maxx logo badge for Powerlast/Spark battery codes.

**`FeedbackModal`** — Modal dialog collecting 1–5 star satisfaction, accuracy rating, which parts were wrong, and freeform comments. Submits to `POST /api/feedback`. Attaches Bearer token header if a test user is logged in.

### 10.3 Admin Pages (`frontend/src/pages/admin/`)

| Page                  | Route               | Description                                              |
|-----------------------|---------------------|----------------------------------------------------------|
| `AdminLogin.tsx`      | `/admin/login`      | Username/password form, sets cookie via API              |
| `AdminDashboard.tsx`  | `/admin`            | Stats overview cards + DB health indicator               |
| `AdminBatteries.tsx`  | `/admin/batteries`  | Paginated battery list with search, add, edit, delete, upload, export |
| `AdminAuditLog.tsx`   | `/admin/audit`      | Filterable audit log table (action, user, date, diff)    |
| `AdminFeedback.tsx`   | `/admin/feedback`   | Feedback table with summary stats, PDF/CSV export        |
| `AdminSessions.tsx`   | `/admin/sessions`   | Admin's own sessions with revoke                         |
| `AdminTestSessions.tsx`| `/admin/test-sessions` | All test-user sessions + user list                   |
| `AdminDataPipeline.tsx`| `/admin/pipeline`  | Trigger data pipeline runs from the dashboard            |

### 10.4 API Layer (`lib/api.ts` and `lib/adminApi.ts`)

All HTTP calls go through typed async wrapper functions. Errors are normalised: if the response body contains `{ detail: "..." }`, that message is thrown as an `Error`. This makes all API errors catchable with `err.message` in components.

```typescript
// Example: typed recommendation fetch
export async function fetchRecommendation(payload: RecommendRequest): Promise<RecommendationResult>
// Times out after 8 seconds for makes fetch (backend startup check)
export async function fetchMakes(): Promise<string[]>
```

### 10.5 Two Input Modes — UI Perspective

**Select Mode (default):**
- Three cascading `<select>` elements (Make → Model → Year).
- Models dropdown is disabled until a make is selected; years disabled until a model is selected.
- Fuel type and engine CC are marked optional.
- A hint link "Don't see your model? Type your query instead →" appears after selecting a make.

**Type Mode:**
- Three free-text `<input>` elements.
- Fuel type and engine CC are **required** (server-side validation will also enforce this since the rule-based fallback needs them).
- Live estimated confidence bar guides the user to fill in more fields.
- The "Type / Select" toggle button switches between modes and resets all fields.

---

## 11. Data Pipelines

Data pipelines are standalone Python scripts run manually (or via the admin DataPipeline page) to refresh the database. They must be run in order when refreshing the dataset.

### 11.1 Pipeline Order

```
1. pipelines/dataprep.py
   Input:  data/CSRP Excel file
   Output: vehicles_raw table + vehicles_raw.csv
   Does:   Parses the raw CSRP dealer dataset, deduplicates by make/model/cc/fuel,
           upserts into vehicles_raw.

2. pipelines/nts_dataprep.py
   Input:  NTS workbook
   Output: nts_vehicles_clean.csv
   Does:   Parses NTS vehicle data into a clean CSV for year enrichment.

3. pipelines/enrich_years.py
   Input:  vehicles_raw table
   Output: vehicle_years table
   Does:   For each unique make/model, queries NHTSA, CarAPI, fueleconomy.gov,
           and Wikidata APIs to find production year ranges.
           Uses cache/year_cache.json and cache/enrichment_cache.json to avoid
           re-fetching on re-runs. Upserts rows into vehicle_years.

4. pipelines/dial_battery_clean.py
   Input:  data/Dial-A-Battery Data - 2023-2026.xlsx
   Output: dial_battery_inference table
   Does:   Cleans and normalises the Dial-A-Battery call-centre order data,
           aggregates by vehicle_type + vehicle_model + battery_code,
           counts frequency, and loads into dial_battery_inference.

5. pipelines/fill_cca.py
   Input:  battery_specs table
   Output: battery_specs table (updates cca_en column)
   Does:   Fills missing CCA values in battery_specs using lookup logic.
```

### 11.2 Upload Pipeline (`upload_pipeline.py`)

The admin dashboard's "Upload" feature uses this module. It accepts an `.xlsx` file (max 10 MB) and performs:

- **Column aliasing**: accepts multiple column name variants (`battery_code` / `code` / `sku`, `model_key` / `model`, `ah` / `capacity_ah`, etc.)
- **Row validation**: rejects rows missing required fields or with type errors.
- **Merge rules**: INSERT if new, UPDATE if changed, SKIP if identical.
- **Audit logging**: every INSERT and UPDATE writes to `battery_audit_log`.
- **Last-write-wins**: duplicate battery codes within the same file take the last occurrence.

Returns a structured result: `{ inserted, updated, skipped_unchanged, rejected, errors }`.

---

## 12. Rate Limiting & Observability

### 12.1 Rate Limiting

Rate limiting is implemented with `slowapi`, which uses Redis or an in-process store keyed by client IP. On `RateLimitExceeded`, the API returns:

```json
{
  "detail": "Rate limit exceeded. Please try again later.",
  "retry_after": "10 second"
}
```

### 12.2 Read Counter

The admin dashboard displays "today's API reads" — the number of `POST /api/recommend` calls made today. This is tracked via:

1. `count_reads_middleware`: increments `_read_counter_pending` (in-memory) on every successful recommendation request.
2. `_flush_read_counter()`: fires every 60 seconds, writes the accumulated delta to `admin_stats` (`stat_key="db_reads"`) in a single DB write.
3. `_reset_daily_reads()`: fires at local midnight, resets `stat_value` to 0 and zeroes the in-memory counter.

### 12.3 Health Endpoint

`GET /api/admin/health` returns:

```json
{
  "status":           "ok",
  "connected":        true,
  "latency_ms":       3.2,
  "pool_size":        10,
  "pool_checked_out": 1,
  "pool_usage_pct":   9.1
}
```

Status degrades to `"degraded"` if latency > 500ms or pool usage > 85%, and `"down"` if DB is unreachable.

---

## 13. Deployment & Environment

### 13.1 Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost:5432/batteryfinderdev
ADMIN_COOKIE_SECURE=false     # false for local HTTP dev; true for production HTTPS
MAINTENANCE_MODE=false        # set true to show maintenance page to users
```

### 13.2 Starting the Server

**Development:**
```bash
# Backend
uvicorn app:app --reload          # http://localhost:8000

# Frontend (separate terminal, hot-reload with Vite proxy to :8000)
cd frontend && bun run dev        # http://localhost:5173
```

**Production:**
```bash
# Build frontend once
cd frontend && bun run build      # outputs to frontend/dist/

# Serve everything from one process
uvicorn app:app --host 0.0.0.0 --port 8000
```

FastAPI automatically detects `frontend/dist/` at startup and serves it. All non-API paths fall through to `index.html`.

### 13.3 CI/CD (Jenkinsfile)

The pipeline stages are:

1. **Checkout** — pull source
2. **Setup Python** — install `requirements.txt`
3. **Setup Node.js & Bun** — install frontend dependencies
4. **Lint Frontend** — `bun run lint`
5. **Build Frontend** — `bun run build`
6. **Test Python** — `pytest`
7. **Archive Artifacts** — store build artifacts

### 13.4 First-Time Setup

```bash
# 1. Set up environment
cp .env.example .env   # fill in DATABASE_URL

# 2. Run migrations
alembic upgrade head

# 3. Create admin account
python scripts/create_admin.py --username admin --password <password>

# 4. Seed vehicle and battery data
python pipelines/dataprep.py
python pipelines/enrich_years.py
python pipelines/dial_battery_clean.py
# (seed battery_specs separately from battery_specs_output.xlsx via admin upload)

# 5. Start server
uvicorn app:app --reload
```

---

*This documentation covers the complete system as of 2026-05-28. For changelog and migration notes see `alembic/versions/` and the git log.*
