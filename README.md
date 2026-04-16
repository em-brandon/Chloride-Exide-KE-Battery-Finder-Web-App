# Battery Finder Project — CSRP Data Set 2025

A data pipeline and analysis toolkit for building a vehicle battery lookup dataset from the CRSP (July 2025) source data.

## Overview

This project processes raw vehicle data from an Excel source file, cleans and normalises it, produces a structured lookup dataset, and enriches it with production year ranges sourced from multiple public APIs.

## Project Structure

```
├── dataprep.py                    # Data preparation pipeline script
├── enrich_years.py                # Year enrichment script (multi-source API lookup)
├── analysis.ipynb                 # Jupyter notebook for exploratory analysis
├── battery_lookup_dataset.csv     # Cleaned output dataset (CSV)
├── battery_lookup_dataset.xlsx    # Cleaned output dataset (Excel)
├── vehicle_years.csv              # Year-enriched dataset (CSV)
├── vehicle_years.xlsx             # Year-enriched dataset (Excel)
├── unmatched_models.csv           # Rows where no year range was found
├── year_cache.json                # API response cache (auto-generated)
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

| Column | Description |
|---|---|
| `make` | Vehicle manufacturer |
| `model` | Vehicle model name and variant |
| `year_from` | First production year |
| `year_to` | Last production year (blank if still in production) |
| `year_source` | API source that provided the year data (`carapi`, `wikipedia`, `wikidata`) |

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
2. Clean and normalise column names
3. Filter out electric vehicles
4. Deduplicate records
5. Save `battery_lookup_dataset.csv` and `battery_lookup_dataset.xlsx`

Progress is logged to the console every 500 rows (configurable via `LOG_EVERY_N_ROWS` in `dataprep.py`).

### Run the Year Enrichment Script

```bash
python enrich_years.py
```

The script will:
1. Load `battery_lookup_dataset.csv`
2. Fetch model lists from NHTSA VPIC and CarAPI (cached to `year_cache.json`)
3. Look up production year ranges in three stages:
   - **Stage 1** — NHTSA VPIC model list per make (used for fuzzy name matching)
   - **Stage 2** — CarAPI model list per make (includes year ranges)
   - **Stage 3** — Year lookup per unique make+model using the NHTSA fuzzy-matched name (falls back to raw model name)
4. Save `vehicle_years.csv`, `vehicle_years.xlsx`, and `unmatched_models.csv`

API results are cached in `year_cache.json` to avoid redundant requests on re-runs.

#### Year Lookup Search Priority

| Priority | Search term used |
|---|---|
| 1st | NHTSA fuzzy-matched model name — if score ≥ 45 |
| 2nd | Raw model name from the dataset |

#### Supported API Sources

| Source | Purpose |
|---|---|
| [NHTSA VPIC](https://vpic.nhtsa.dot.gov/api/) | US government vehicle model reference list |
| [CarAPI](https://carapi.app/) | Community car database with year ranges |
| [Wikipedia API](https://en.wikipedia.org/w/api.php) | Page extracts for year range parsing |
| [Wikidata SPARQL](https://query.wikidata.org/) | Structured production year data |

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
