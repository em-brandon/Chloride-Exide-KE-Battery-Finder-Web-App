# Battery Finder — CRSP Dataset 2025

A data pipeline, rule-based matching engine, and web application for recommending the correct car battery for a given vehicle.

The project has two phases:

1. **Data pipeline** — cleans and normalises raw CRSP vehicle data, enriches it with individual production years from multiple public APIs, and produces a structured lookup dataset.
2. **Battery Finder web app** — a FastAPI backend with a vanilla-JS single-page frontend that lets users look up the right battery by Make / Model / Year, with optional Engine CC and Fuel Type information.

## Project Structure

```
├── app.py                         # FastAPI web server (serves API + frontend)
├── matcher.py                     # Rule-based battery matching engine (3-layer)
├── static/
│   └── index.html                 # Single-page battery finder UI
├── dataprep.py                    # Data preparation pipeline script
├── enrich_years.py                # Year enrichment script (multi-source API lookup)
├── analysis.ipynb                 # Jupyter notebook for exploratory analysis
├── battery_lookup_dataset.csv     # Cleaned output dataset (CSV)
├── vehicle_years.csv              # Year-enriched dataset — one row per production year (CSV)
├── unmatched_models.csv           # Make/model pairs where no year data was found
├── year_cache.json                # API response cache (auto-generated)
├── fueleconomy_vehicles.csv       # Local cache of fueleconomy.gov bulk CSV (auto-generated)
├── requirements.txt               # Python dependencies
└── README.md
```

> **Note:** The source file `New-CRSP---July-2025.xlsx` is required to run `dataprep.py` but is not included in the repository.

---

## Battery Finder Web App

### Running the App

```bash
pip install -r requirements.txt
python app.py
```

The app starts on **http://localhost:8000**.

### How It Works

Users select (or manually type) their vehicle's **Make**, **Model**, and **Year**. The UI cascades — selecting a make populates the model list, selecting a model populates the year list. If a vehicle isn't in the database, each field has a **Select / Type** toggle that lets the user enter the details manually.

Optional fields — **Engine CC** and **Fuel Type** — improve recommendation accuracy. When any field is in manual (Type) mode, Engine CC and Fuel Type become required.

### Matching Engine (`matcher.py`)

The matching engine applies a **3-layer rule hierarchy**:

| Layer | Trigger | Confidence |
|---|---|---|
| **Exact match** | Make + Model + Year found in `vehicle_years.csv` | 100% |
| **Close match** | Make + Model found, year within ±2 years | 60–85% |
| **Fallback** | Engine CC + Fuel Type rules only | 30–50% |

The engine returns a primary recommendation and up to three alternative batteries, with a `match_type` label and `confidence` percentage.

Stop-start capability is inferred from make + year.

### API Endpoints

All endpoints are rate-limited (20 req/min for lookups, 10 req/min for recommendations).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/makes` | List all available makes |
| `GET` | `/api/models/{make}` | List models for a given make |
| `GET` | `/api/years?make=&model=` | List available years for a make + model |
| `POST` | `/api/recommend` | Get a battery recommendation |

#### `POST /api/recommend` — Request Body

```json
{
  "make": "TOYOTA",
  "model": "Corolla",
  "year": 2015,
  "engine_cc": 1500,
  "fuel_type": "Petrol"
}
```

#### Response

```json
{
  "match_type": "exact",
  "confidence": 100,
  "matched_make": "TOYOTA",
  "matched_model": "Corolla",
  "matched_year": 2015,
  "engine_cc": 1500,
  "fuel_type": "Petrol",
  "primary": {
    "battery_code": "NS60",
    "model_key": "...",
    "ah": 45,
    "cca_en": 390,
    "technology": "MF"
  },
  "alternatives": [ ... ]
}
```

---

## Dataset

### `battery_lookup_dataset.csv`

| Column | Description |
|---|---|
| `make` | Vehicle manufacturer (e.g. AUDI, TOYOTA) |
| `model` | Vehicle model name and variant |
| `engine_capacity` | Engine displacement in cc |
| `fuel` | Fuel type (GASOLINE, DIESEL, etc.) — electric vehicles are excluded |

### `vehicle_years.csv`

Each row represents a single make + model + production year combination. This flat structure enables direct lookup for rule-based battery matching (e.g. user inputs `Toyota Corolla 2012` → one exact row match).

| Column | Description |
|---|---|
| `make` | Vehicle manufacturer |
| `model` | Vehicle model name and variant |
| `year` | Individual production year (one row per year) |
| `engine_capacity` | Engine displacement in cc |
| `fuel` | Fuel type (GASOLINE, DIESEL, etc.) |

> Rows where no year data could be found are excluded from this file and written to `unmatched_models.csv` instead.

## Getting Started

### Prerequisites

- Python 3.10 or later
- The source Excel file: `New-CRSP---July-2025.xlsx` placed in the project folder (only needed to re-run the data pipeline)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run the Battery Finder Web App

```bash
python app.py
```

Open **http://localhost:8000** in your browser.

### Run the Data Preparation Pipeline

```bash
python dataprep.py
```

The script will:
1. Load `New-CRSP---July-2025.xlsx`
2. Clean and normalise column names , remove model number collumn
3. 
4. Filter out electric vehicles
5. Deduplicate records
6. Save `battery_lookup_dataset.csv` and `battery_lookup_dataset.xlsx`

Progress is logged to the console every 500 rows (configurable via `LOG_EVERY_N_ROWS` in `dataprep.py`).

### Run the Year Enrichment Script

```bash
python enrich_years.py
```

The script will:
1. Load `battery_lookup_dataset.csv`
2. Reset the years cache (see [Caching](#caching) below)
3. Fetch model lists from NHTSA VPIC and CarAPI (cached to `year_cache.json`)
4. Look up production years in four stages:
   - **Stage 1** — Download the fueleconomy.gov bulk CSV (cached locally as `fueleconomy_vehicles.csv`)
   - **Stage 2** — NHTSA VPIC model list per make (used for fuzzy name matching)
   - **Stage 3** — CarAPI model list per make (includes year-range data)
   - **Stage 4** — Year lookup per unique make+model using the NHTSA fuzzy-matched name (falls back to raw model name)
5. Save `vehicle_years.csv`, `vehicle_years.xlsx`, and `unmatched_models.csv`

#### Caching

`year_cache.json` has three sections:

| Section | Behaviour |
|---|---|
| `nhtsa` | Persisted across runs — model lists are reused |
| `carapi` | Persisted across runs — model lists are reused |
| `years` | **Cleared on every run** — always re-fetched to avoid stale data |

`fueleconomy_vehicles.csv` is downloaded once from the US DOE/EPA and reused on subsequent runs. Delete the file to force a fresh download.

#### Year Lookup Search Priority

| Priority | Search term used |
|---|---|
| 1st | NHTSA fuzzy-matched model name — if score ≥ 45 |
| 2nd | Raw model name from the dataset |

#### Supported API Sources

Sources are tried in priority order. fueleconomy.gov provides exact per-year records and is the highest-quality source for US-market vehicles.

| Priority | Source | Coverage | Data type |
|---|---|---|---|
| 1 | [fueleconomy.gov](https://www.fueleconomy.gov/feg/epadata/vehicles.csv) (US DOE/EPA bulk CSV) | US-market, 1984–present | Exact years |
| 2 | [CarAPI](https://carapi.app/) | Global, community-sourced | Year range (expanded) |
| 3 | [Wikipedia API](https://en.wikipedia.org/w/api.php) | Global, best-effort | Year range (expanded) |
| 4 | [Wikidata SPARQL](https://query.wikidata.org/) | Global, structured | Year range (expanded) |

Non-US makes (Great Wall, SAIC, Maruti Suzuki, Peugeot, Citroën, Renault, Haval, Iveco, Mitsubishi Fuso) are automatically skipped for fueleconomy.gov and fall through to CarAPI / Wikipedia / Wikidata.

*NHTSA VPIC is used only for fuzzy model-name matching — it does not provide year data.*

### Run the Analysis Notebook

```bash
jupyter notebook analysis.ipynb
```

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| fastapi | ≥ 0.110.0 | Web API framework |
| uvicorn | ≥ 0.29.0 | ASGI server |
| slowapi | ≥ 0.1.9 | Rate limiting |
| pydantic | ≥ 2.0.0 | Request validation |
| pandas | ≥ 2.2.0 | Data processing |
| numpy | ≥ 1.26.0 | Numerical operations |
| openpyxl | ≥ 3.1.0 | Excel read/write |
| xlrd | ≥ 2.0.1 | Legacy Excel read |
| matplotlib | ≥ 3.8.0 | Analysis charts |
| seaborn | ≥ 0.13.0 | Analysis charts |
| jupyter | ≥ 1.0.0 | Notebook support |
| ipykernel | ≥ 6.29.0 | Notebook kernel |
| requests | ≥ 2.31.0 | HTTP client (year enrichment) |
| rapidfuzz | ≥ 3.6.0 | Fuzzy model-name matching |
| pandas-stubs | latest | Type stubs |
| types-requests | latest | Type stubs |
