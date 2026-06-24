# Vehicle Data Quality Plan

## Audit Date: 2026-06-24

---

## Issue 1 — Wrong Year Ranges (Wikidata Inception Date Bug)

### Root Cause

The CRSP enrichment pipeline looked up models on Wikidata using property **P571 (inception)**,
which stores the founding/introduction year of the entire nameplate — not the specific trim or
generation. For example:

- Toyota Land Cruiser P571 → **1951** (when the first BJ prototype was built)
- Hino P571 → **1953** (when Hino Motors was founded)
- Land Rover P571 → **1951** (when the first Land Rover launched)
- Chevrolet Corvette P571 → **1953** (first Corvette year)

These inception dates were then applied as `year_from` to every trim under that nameplate,
producing rows like `(Toyota, Land Cruiser 250 VX, 1951)` — a model that only launched in 2024.

### Scale of Impact

| Metric | Value |
|---|---|
| Total rows with year < 1960 | **920 rows** |
| Makes affected | **20 makes** |
| Model entries affected | **182 distinct models** |

### Affected Makes

| Make | Bad models | Earliest bad year |
|---|---|---|
| TOYOTA | 60 | 1951 |
| NISSAN | 21 | 1955 |
| LANDROVER | 20 | 1951 |
| ISUZU | 20 | 1952 |
| HINO | 15 | 1953 |
| SUBARU | 7 | 1958 |
| MINI | 5 | 1959 |
| MERCEDES | 5 | 1953 |
| NISSAN DIESEL/UD | 4 | 1955 |
| DAIHATSU | 4 | 1951 |
| BENTLEY | 3 | 1959 |
| CHEVROLET | 3 | 1950 |
| MAN | 2 | 1951 |
| JEEP | 2 | 1951 |
| HONDA | 2 | 1958 |
| FORD | 2 | 1956 |
| FIAT | 1 | 1957 |
| SUZUKI | 1 | 1959 |
| DODGE | 1 | 1955 |
| VAUXHALL | 1 | 1952 |

### Known Bad Entries (Toyota Land Cruiser example)

All 18 Land Cruiser entries incorrectly span **1951–2025** (75 rows each):

| Model | Correct years | Current (wrong) |
|---|---|---|
| LAND CRUISER 250 VX | 2024–present | 1951–2025 |
| LAND CRUISER 250 ZX FIRST EDITION | 2024–present | 1951–2025 |
| LAND CRUISER 200 VXR 1VD | 2007–2021 | 1951–2025 |
| LAND CRUISER 70 AX | 1984–present | 1951–2025 |
| LAND CRUISER PRADO TX | 1990–present | 1951–2025 |
| LAND CRUISER PRADO TZ-G | 2009–present | 1951–2025 |

### Fix Strategy

Two steps:

**Step 1 — Delete all rows where year < 1960**
```sql
DELETE FROM vehicle_years WHERE year < 1960;
```
920 rows removed. No real Kenyan-market vehicle sold today was manufactured before 1960.

**Step 2 — Re-enrich affected model+make pairs via CRSP pipeline**
After deletion, re-run Stage 2 enrichment for the affected pairs so they get correct
year ranges from fueleconomy.gov or CarQuery instead of Wikidata inception dates.

**Step 3 — Fix Wikidata enrichment in `pipelines/enrich_years.py`**
The Wikidata `get_years_from_wikidata()` function uses P571 (inception). This should be
cross-checked: if the returned `year_start` is more than 20 years before the model's
plausible production start (e.g. pre-1970 for a specific trim), treat it as a bad signal
and return `None, None` to fall through to Wikipedia/cluster fallback instead.

---

## Issue 2 — Missing Kenya-Market Models

### Toyota — Missing Models

| Missing model | Production years | Kenya relevance |
|---|---|---|
| Land Cruiser 100 | 1998–2007 | Very common — predecessor to 200 series |
| Land Cruiser 105 | 1998–2007 | Diesel variant of 100, common |
| Land Cruiser Prado 90 series | 1996–2002 | Older but still seen |
| Land Cruiser Prado 120 series | 2002–2009 | Common mid-era Prado |
| Land Cruiser Prado 150 series | 2009–2024 | Most common Prado on Kenyan roads |
| Toyota Succeed | 2002–present | Estate version of Probox — extremely common |
| Toyota Hilux Surf | 1984–2009 | 4x4 SUV, very widely used |
| Toyota Kluger / Highlander | 2000–present | Popular mid-size family SUV |
| Toyota Avanza | 2003–present | Affordable 7-seater MPV, popular in East Africa |
| Toyota IST | 2002–2016 | Compact JDM car, common import |
| Toyota Caldina | 1992–2007 | JDM wagon, seen regularly |
| Toyota Ipsum / Nadia / Gaia | 1995–2009 | JDM 7-seater MPVs |
| Toyota Mark II / Chaser | 1968–2007 | Classic JDM luxury sedans still on Kenyan roads |
| Toyota Runx / Allex | 2001–2006 | JDM compact hatches, common budget imports |
| Toyota 4Runner | 1984–present | US name for Hilux Surf |

### Other Makes — Confirmed Gaps

| Make | Missing / bad | Details |
|---|---|---|
| HAVAL | H6, H9, Jolion, F7, Dargo | Only 4 generic entries (CITY, PREMIUM, ULTRA) — H6 is a top-selling Kenya SUV |
| FOTON | All models | 0 rows — Foton trucks (Aumark, Ollin, Tornado) very common |
| FAW | All passenger models | Only 2 internal truck codes; Bestune T77, Sirius missing |
| RENAULT | Duster | 68 models in DB but French-market only; Duster is one of Kenya's most popular SUVs |
| MITSUBISHI | Pajero Sport, ASX, L200 | DB has JDM trim names only; Pajero Sport (Kenya market) missing |

---

## Fix Plan

### Fix 1 — Data cleanup script (immediate)

Create `scripts/fix_vehicle_year_ranges.py`:
- Delete all `vehicle_years` rows where `year < 1960` (920 rows)
- Log which make/model pairs were affected
- Re-queue those pairs for CRSP enrichment

### Fix 2 — Wikidata guard in `pipelines/enrich_years.py`

In `get_years_from_wikidata()`, add a sanity check on the returned `yf`:
```python
if yf and yf < 1960:
    log(f"    [Wikidata] Rejecting inception year {yf} — likely brand founding date, not model year")
    return None, None
```

### Fix 3 — Vehicle Expansion Pipeline (planned, separate plan)

The expansion pipeline (`pipelines/vehicle_coverage_expansion.py`) will add all the
missing Kenya-market models from CarQuery, NHTSA, cars-data.com and car.info.
See `VEHICLE_EXPANSION_PLAN.md` for full implementation plan.

---

## Current vehicle_years Stats

| Metric | Value |
|---|---|
| Total rows | 58,350 |
| Rows with bad year (< 1960) | 920 |
| Rows after cleanup | ~57,430 |
| Target after expansion | ~100,000 |
