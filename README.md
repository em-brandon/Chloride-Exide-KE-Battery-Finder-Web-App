# Battery Finder Project — CSRP Data Set 2025

flowchart TD
    subgraph Offline["Offline / Data Preparation"]
        XLSX["New-CRSP---July-2025.xlsx\n(source data)"]
        DP["dataprep.py\nETL + normalisation"]
        CSV["battery_lookup_dataset.csv\n4,567 rows"]
        EY["enrich_years.py\n5-source enrichment pipeline"]
        VY["vehicle_years.csv\n75,052 rows"]
        UM["unmatched_models.csv\n490 pairs"]
        YC["year_cache.json\nAPI result cache"]
        SPECS["battery_specs_output.xlsx\n64 batteries (NS + DIN)"]

        subgraph ExternalAPIs["External APIs"]
            NHTSA["NHTSA VPIC"]
            WIKI["Wikipedia"]
            WIKIDATA["Wikidata SPARQL"]
            CARAPI["CarAPI"]
            FUELGOV["fueleconomy.gov"]
        end

        XLSX --> DP --> CSV
        CSV --> EY
        EY <--> YC
        EY --> VY
        EY --> UM
        EY <--> NHTSA
        EY <--> WIKI
        EY <--> WIKIDATA
        EY <--> CARAPI
        EY <--> FUELGOV
    end

    subgraph Runtime["Runtime / API Server"]
        APP["app.py\nFastAPI + slowapi"]
        MATCHER["matcher.py\nRule-based engine\n+ rapidfuzz matching"]
        FRONTEND["static/index.html\nBrowser UI"]

        VY -->|loaded at startup| MATCHER
        SPECS -->|loaded at startup| MATCHER
        MATCHER -->|lru_cache| MATCHER
        APP --> MATCHER
        FRONTEND -->|HTTP GET/POST| APP
    end

    subgraph MatchingLayers["Matching Layers (matcher.py)"]
        L1["Layer 1 — Exact\nmake + model ≥90 + exact year\nconfidence 100"]
        L2["Layer 2 — Soft\nmake + model ≥60 + year ±3\nconfidence 60–89"]
        L3["Layer 3 — Rule\nengine_cc + fuel → Ah bracket\nconfidence 40"]
        L1 -->|no match| L2 -->|no match| L3
    end

    MATCHER --- MatchingLayers

A data pipeline and analysis toolkit for building a vehicle battery lookup dataset from the CRSP (July 2025) source data.

## Overview

This project processes raw vehicle data from an Excel source file, cleans and normalises it, produces a structured lookup dataset, and enriches it with individual production years sourced from multiple public APIs. Each output row represents one specific model year, ready for direct rule-based battery matching.

## Project Structure

```
├── dataprep.py                    # Data preparation pipeline script
├── enrich_years.py                # Year enrichment script (multi-source API lookup)
├── analysis.ipynb                 # Jupyter notebook for exploratory analysis
├── battery_lookup_dataset.csv     # Cleaned output dataset (CSV)
├── battery_lookup_dataset.xlsx    # Cleaned output dataset (Excel)
├── vehicle_years.csv              # Year-enriched dataset — one row per production year (CSV)
├── vehicle_years.xlsx             # Year-enriched dataset — one row per production year (Excel)
├── unmatched_models.csv           # Make/model pairs where no year data was found
├── year_cache.json                # API response cache (auto-generated)
├── fueleconomy_vehicles.csv       # Local cache of fueleconomy.gov bulk CSV (auto-generated)
├── requirements.txt               # Python dependencies
└── README.md
```

> **Note:** The source file `New-CRSP---July-2025.xlsx` is required to run `dataprep.py` but is not included in the repository.

## Dataset Columns

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
- The source Excel file: `New-CRSP---July-2025.xlsx` placed in the project folder

### Install Dependencies

```bash
pip install -r requirements.txt
```

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

| Package | Version |
|---|---|
| pandas | ≥ 2.2.0 |
| numpy | ≥ 1.26.0 |
| openpyxl | ≥ 3.1.0 |
| xlrd | ≥ 2.0.1 |
| matplotlib | ≥ 3.8.0 |
| seaborn | ≥ 0.13.0 |
| jupyter | ≥ 1.0.0 |
| ipykernel | ≥ 6.29.0 |
| requests | ≥ 2.31.0 |
| rapidfuzz | ≥ 3.6.0 |
| pandas-stubs | latest |
| types-requests | latest |
