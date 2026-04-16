# Battery Finder Project — CSRP Data Set 2025

A data pipeline and analysis toolkit for building a vehicle battery lookup dataset from the CRSP (July 2025) source data.

## Overview

This project processes raw vehicle data from an Excel source file, cleans and normalises it, and produces a structured lookup dataset that maps vehicle make, model, and specifications to battery requirements.

## Project Structure

```
├── dataprep.py                    # Data preparation pipeline script
├── analysis.ipynb                 # Jupyter notebook for exploratory analysis
├── battery_lookup_dataset.csv     # Cleaned output dataset (CSV)
├── battery_lookup_dataset.xlsx    # Cleaned output dataset (Excel)
├── requirements.txt               # Python dependencies
└── README.md
```

> **Note:** The source file `New-CRSP---July-2025.xlsx` is required to run `dataprep.py` but is not included in the repository.

## Dataset Columns

| Column | Description |
|---|---|
| `make` | Vehicle manufacturer (e.g. AUDI, TOYOTA) |
| `model` | Vehicle model name and variant |
| `engine_capacity` | Engine displacement in cc or kWh (electric vehicles) |
| `fuel` | Fuel type (GASOLINE, DIESEL, ELECTRIC, etc.) |

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
3. Filter and deduplicate records
4. Save `battery_lookup_dataset.csv` and `battery_lookup_dataset.xlsx`

Progress is logged to the console every 500 rows by default (configurable via `LOG_EVERY_N_ROWS` in `dataprep.py`).

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
