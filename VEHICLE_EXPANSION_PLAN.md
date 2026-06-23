# Plan: Expand vehicle_years from ~60k to 100k rows

## Context

The `vehicle_years` table currently has **~60,714 rows**. The target is 100k rows — a gap of ~39k.

The existing CRSP enrichment pipeline (`pipelines/enrich_years.py`) is bounded by `battery_lookup_dataset.csv` — it cannot add vehicles not in the battery catalogue. To expand beyond this, a supplementary pipeline (`pipelines/vehicle_coverage_expansion.py`) populates `vehicle_years_staging` directly from external global vehicle databases, independent of the CRSP data.

**Status:** `pipelines/vehicle_coverage_expansion.py` was created in a previous session (unapproved). It has a HINO duplicate in `TARGET_MAKES` that needs fixing. The remaining tasks below are **not yet implemented**.

---

## Data Sources (5 total, priority order)

### Source 1 — NHTSA VPIC per-year (already in expansion.py)
`GET /GetModelsForMakeYear/make/{make}/modelYear/{year}` — exact per-year model lists for US-sold vehicles (1981–present). Best for Japanese/Korean/US makes.

### Source 2 — CarQuery API (already in expansion.py)
Free JSONP API at `carqueryapi.com/api/0.3/?cmd=getModels&make={make}`. Returns `year_first`/`year_last` per model globally. Covers European/Korean makes CarAPI misses. JSONP strip: `re.search(r'\{.*\}', text, re.DOTALL)`.

### Source 3 — auto-data.net (NEW — to add)
**Best single source for European makes** (Peugeot, Citroën, Renault, Opel, Vauxhall) and JDM model generations. Structured HTML per model page.
- URL pattern: `https://www.auto-data.net/en/allmodels-{slug}.html` (e.g. `peugeot`, `renault`)
- Scrape: model name + generation year ranges from the model listing tables
- Fills the gap for makes mapped to `None` in `FE_MAKE_MAP` in `enrich_years.py`

### Source 4 — car.info (already scaffolded in expansion.py, needs full implementation)
Global coverage including full JDM lineups (Hiace, Land Cruiser Prado variants, trims) with production year ranges per trim.
- URL pattern: `https://www.car.info/en-gb/{slug}/` (e.g. `toyota`, `nissan`)
- Scrape: model name + year range from model listing cards

### Source 5 — cars-data.com (already scaffolded in expansion.py, needs full implementation)
Chinese brands (Haval, Great Wall, SAIC) and commercial vehicles (Iveco, Fuso) with year ranges — directly fills None-mapped makes.
- URL pattern: `https://www.cars-data.com/en/{slug}-cars` (e.g. `haval`, `great-wall`, `iveco`)
- Scrape: model name + year range from model listing

---

## Target Makes

40+ makes in `TARGET_MAKES` dict in `vehicle_coverage_expansion.py` — covers Japanese, European, Korean, Chinese, and commercial truck segments. Fix duplicate HINO key before running.

---

## Remaining Implementation Tasks

### Task 1: Fix HINO duplicate in `pipelines/vehicle_coverage_expansion.py`
- Line ~80 and line ~111 both define `"HINO"` key — second silently overwrites first
- Keep one entry (the commercial trucks section), remove the duplicate in the Japanese section or rename it

### Task 2: Add auto-data.net scraper to `pipelines/vehicle_coverage_expansion.py`
New function `_scrape_autodata(slug: str, cache: dict, log=print) -> list[dict]`:
- GET `https://www.auto-data.net/en/allmodels-{slug}.html` with BeautifulSoup/lxml
- Parse model table rows: extract model name + year range columns
- Return `[{model, year_from, year_to}]`
- Add `"autodata"` slug to each make in `TARGET_MAKES` (None where not covered)
- Call in `main()` alongside other scrapers; results merged into `pairs` set

### Task 3: Complete car.info scraper in `pipelines/vehicle_coverage_expansion.py`
`_scrape_carinfo()` is scaffolded but needs production-ready HTML parsing:
- Target: model cards/rows with year span text like "2005–2015"
- Add error handling + cache write on success

### Task 4: Complete cars-data.com scraper in `pipelines/vehicle_coverage_expansion.py`
`_scrape_carsdata()` is scaffolded but needs production-ready HTML parsing:
- Target: model listing with year columns
- Add error handling + cache write on success

### Task 5: Add CarQuery as Source 6 in `pipelines/enrich_years.py`
For the CRSP pipeline's unmatched pairs (Peugeot, Haval, etc. mapped to `None` in `FE_MAKE_MAP`):
- Add `CARQUERY_URL` constant and make name map
- Add `fetch_carquery_for_enrich(make, cache, log)` function (reuse JSONP-strip pattern)
- Add CarQuery fetch stage in `main()` alongside CarAPI
- Extend `lookup_years()` with CarQuery fallback as Source 6 after Wikidata

### Task 6: Add expansion pipeline endpoints to `admin_router.py`
Mirror the existing CRSP pipeline pattern (`_crsp_lock`, `_crsp_state`, `_crsp_thread`):
- New `_expansion_lock`, `_expansion_state`, `_expansion_thread()`
- `POST /api/admin/pipeline/vehicle-expansion/run` — background thread, returns `run_id`
- `GET /api/admin/pipeline/vehicle-expansion/status` — progress + log lines
- `POST /api/admin/pipeline/vehicle-expansion/pause|resume|cancel`

### Task 7: Add expansion API functions to `frontend/src/lib/adminApi.ts`
- New `ExpansionStatus` interface (mirrors `CrspStatus`)
- `runExpansionPipeline()`, `getExpansionStatus()`, `cancelExpansion()` functions

### Task 8: Add ExpansionTab UI to `frontend/src/pages/admin/AdminDataPipeline.tsx`
- Add `'expansion'` to `type DatasetTab = 'crsp' | 'webvalidate'`
- New `ExpansionTab` component: Run button, live log feed, staging row count before/after
- New tab button alongside CRSP and Webvalidate tabs
- **Use inline `style={{}}` props throughout — no Tailwind utility classes** (per CLAUDE.md)

---

## Expected Yield

| Source | New rows (est.) |
|---|---|
| NHTSA per-year (Japanese/Korean/US) | ~15–20k |
| CarQuery (European + global) | ~10–15k |
| auto-data.net (European/JDM) | ~8–12k |
| car.info (JDM trims) | ~5–8k |
| cars-data.com (Chinese/commercial) | ~5–8k |
| Overlap removed by `write_to_staging` dedup | −5–10k |
| **Net new rows** | **~38–53k** |

Combined with existing 60,714 → target ~95k–100k+ rows.

---

## Verification

1. Fix HINO duplicate, then run CLI test: `python pipelines/vehicle_coverage_expansion.py --makes peugeot,haval --years 2000-2026`
2. Check staging row count in log output and source breakdown
3. Admin UI → DataPipeline → Expansion tab → review staging rows (filter by source)
4. Commit staging → `SELECT COUNT(*) FROM vehicle_years` should approach 100k
5. Spot-check: Peugeot 208, Haval H6, Renault Duster — confirm now in `vehicle_years`
