# Plan: Vehicle Expansion Pipeline — Own Tab with Editable Makes List

## Context

`pipelines/vehicle_coverage_expansion.py` is fully implemented (NHTSA, CarQuery, cars-data.com, car.info scrapers, cancel/pause support, dedup against `vehicle_years`) but has no admin UI and no backend endpoints. The user wants:
- A **Vehicle Expansion** tab (its own tab, not under CRSP)
- A **curated Kenya-market make list editable from the admin UI** — stored in the DB, not hardcoded
- Year range tiers per segment (agreed with user)
- Pipeline reads existing `vehicle_years` at startup and only stages genuinely new rows
- Staged rows reviewed → committed via the existing staging → commit flow

---

## Year Range Tiers (agreed with user)

| Tier | Makes | Year range |
|---|---|---|
| `default` | Toyota, Nissan, Honda, Mazda, Subaru, Mitsubishi, Suzuki, Daihatsu, Lexus, Hyundai, Kia, BMW, Mercedes, Audi, VW, Land Rover, Jaguar, Peugeot, Citroën, Renault, Opel, Fiat, Skoda, Volvo, Mini, Ford, Chevrolet, Jeep | 2003–2026 |
| `commercial` | Isuzu, Hino, Mitsubishi Fuso, MAN, Scania, Iveco Daily, Nissan Diesel/UD | 1995–2026 |
| `chinese` | Haval, Great Wall, Chery, Foton, FAW, Dongfeng, JAC, Tata, Maruti Suzuki, SAIC Motors | 2010–2026 |

---

## Files to Modify (6 files)

### 1. `models.py`

Add `ExpansionMake` after `FueleconomyVehicle` (~line 583):

```python
class ExpansionMake(Base):
    __tablename__ = "expansion_makes"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    make          = Column(String(100), nullable=False, unique=True)   # e.g. "TOYOTA"
    year_tier     = Column(String(20),  nullable=False, default="default")  # default | commercial | chinese
    nhtsa_slug    = Column(String(100), nullable=True)   # e.g. "Toyota"
    cq_slug       = Column(String(100), nullable=True)   # e.g. "toyota"
    carsdata_slug = Column(String(100), nullable=True)   # e.g. "toyota"
    carinfo_slug  = Column(String(100), nullable=True)   # e.g. "toyota"
    enabled       = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), nullable=True)
    updated_at    = Column(DateTime(timezone=True), nullable=True)
```

---

### 2. `alembic/versions/` — new migration

**Filename:** `20260624_c3d4e5f6a7b8_expansion_makes.py`
**Revises:** `f2a3b4c5d6e7` (current latest)

```python
def upgrade() -> None:
    op.create_table(
        "expansion_makes",
        sa.Column("id",            sa.Integer(),               primary_key=True, autoincrement=True),
        sa.Column("make",          sa.String(100),             nullable=False),
        sa.Column("year_tier",     sa.String(20),              nullable=False, server_default="default"),
        sa.Column("nhtsa_slug",    sa.String(100),             nullable=True),
        sa.Column("cq_slug",       sa.String(100),             nullable=True),
        sa.Column("carsdata_slug", sa.String(100),             nullable=True),
        sa.Column("carinfo_slug",  sa.String(100),             nullable=True),
        sa.Column("enabled",       sa.Boolean(),               nullable=False, server_default="true"),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",    sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("make", name="uq_expansion_makes_make"),
    )
```

**Seed data:** Insert the full curated list from the current `TARGET_MAKES` dict inside `upgrade()` using `op.bulk_insert()` — so on `alembic upgrade head` the table is pre-populated with the Kenya-market list. No manual seeding step required.

---

### 3. `pipelines/vehicle_coverage_expansion.py`

**a. Keep `TARGET_MAKES` as the fallback seed** (used for `alembic upgrade head` seeding and CLI runs without a DB connection). Do not delete it.

**b. Add `YEAR_TIERS` dict:**
```python
YEAR_TIERS = {
    "commercial": (1995, 2026),
    "chinese":    (2010, 2026),
    "default":    (2003, 2026),
}
```

**c. Add `load_makes_from_db(db) -> dict`** function:
```python
def load_makes_from_db(db) -> dict:
    """Load enabled makes from expansion_makes table. Falls back to TARGET_MAKES if table empty."""
    from models import ExpansionMake
    rows = db.query(ExpansionMake).filter(ExpansionMake.enabled == True).all()
    if not rows:
        return TARGET_MAKES   # fallback for fresh installs before seeding
    return {
        r.make: {
            "nhtsa": r.nhtsa_slug, "cq": r.cq_slug,
            "carsdata": r.carsdata_slug, "carinfo": r.carinfo_slug,
            "year_tier": r.year_tier,
        }
        for r in rows
    }
```

**d. Update `main()`** — replace `TARGET_MAKES` reference with `load_makes_from_db(db)` when `db` is provided. Use `YEAR_TIERS[make_config.get("year_tier", "default")]` to clamp year range per make.

**e. Fix HINO duplicate** — remove the first HINO entry (~line 80). Keep only the commercial trucks entry.

**f. Add JAC to `TARGET_MAKES`:**
```python
"JAC": {"nhtsa": None, "cq": None, "carsdata": "jac", "carinfo": "jac"},
```

**g. Remove** `VAUXHALL`, `DODGE`, `EICHER` from `TARGET_MAKES`.

---

### 4. `admin_router.py`

#### 4a — Expansion pipeline state + thread (insert after `_crsp_state` block ~line 2495)

```python
_expansion_lock = threading.Lock()
_expansion_state: dict = {
    "run_id":          None,
    "status":          "idle",   # idle | running | paused | done | cancelled | error
    "current_make":    None,
    "makes_total":     0,
    "makes_processed": 0,
    "rows_staged":     0,
    "rows_skipped":    0,
    "source_counts":   {},
    "logs":            deque(maxlen=50),
    "started_at":      None,
    "finished_at":     None,
    "error_detail":    None,
    "cancel_event":    None,
    "pause_event":     None,
    "initiated_by":    None,
}
```

`_expansion_thread()` opens its own `SessionLocal()`, calls `expansion_main()`, updates state under lock, closes session on exit.

#### 4b — Five pipeline endpoints (after CRSP cancel ~line 3134)

| Method | Path | Action |
|---|---|---|
| POST | `/pipeline/expansion/run` | spawn thread, return `{run_id}` |
| GET  | `/pipeline/expansion/status` | return state minus events |
| POST | `/pipeline/expansion/pause` | set pause_ev |
| POST | `/pipeline/expansion/resume` | clear pause_ev |
| POST | `/pipeline/expansion/cancel` | set cancel_ev, wait 3s, force `"cancelled"` |

#### 4c — Four expansion makes CRUD endpoints

| Method | Path | Action |
|---|---|---|
| GET    | `/pipeline/expansion/makes` | return all rows ordered by make |
| POST   | `/pipeline/expansion/makes` | create new make; 409 if make name already exists |
| PATCH  | `/pipeline/expansion/makes/{id}` | update slugs / year_tier / enabled |
| DELETE | `/pipeline/expansion/makes/{id}` | hard delete (not soft — list management, not audit-critical) |

Pattern mirrors battery CRUD (lines 293–434): `Depends(require_admin)`, `Depends(get_db)`, return updated row. No audit log needed for makes list changes.

---

### 5. `frontend/src/lib/adminApi.ts`

Add after line 1114.

**Two new interfaces:**
```typescript
export interface ExpansionMake {
  id:            number
  make:          string
  year_tier:     'default' | 'commercial' | 'chinese'
  nhtsa_slug:    string | null
  cq_slug:       string | null
  carsdata_slug: string | null
  carinfo_slug:  string | null
  enabled:       boolean
}

export interface ExpansionStatus {
  run_id:          string | null
  status:          'idle' | 'running' | 'paused' | 'done' | 'cancelled' | 'error'
  current_make:    string | null
  makes_total:     number
  makes_processed: number
  rows_staged:     number
  rows_skipped:    number
  source_counts:   Record<string, number>
  logs:            string[]
  started_at:      string | null
  finished_at:     string | null
  error_detail:    string | null
  initiated_by:    string | null
}
```

**Nine functions:**
```typescript
// Pipeline control
export async function runExpansionPipeline(): Promise<{ run_id: string }>
export async function getExpansionStatus(): Promise<ExpansionStatus>
export async function pauseExpansion(): Promise<{ detail: string }>
export async function resumeExpansion(): Promise<{ detail: string }>
export async function cancelExpansion(): Promise<{ detail: string }>

// Makes list CRUD
export async function getExpansionMakes(): Promise<ExpansionMake[]>
export async function createExpansionMake(data: Omit<ExpansionMake, 'id'>): Promise<ExpansionMake>
export async function updateExpansionMake(id: number, data: Partial<ExpansionMake>): Promise<ExpansionMake>
export async function deleteExpansionMake(id: number): Promise<{ detail: string }>
```

---

### 6. `frontend/src/pages/admin/AdminDataPipeline.tsx`

**a. Extend `DatasetTab` type** (line 120):
```typescript
type DatasetTab = 'crsp' | 'webvalidate' | 'expansion'
```

**b. Add tab button** after Web Battery Validation button (~line 3670):
```tsx
<button style={tabStyle('expansion')} onClick={() => setActiveTab('expansion')}>
  <CircleStackIcon style={{ width: 14, height: 14 }} /> Vehicle Expansion
</button>
```

**c. Update conditional render** (lines 3673–3677):
```tsx
{activeTab === 'crsp'      ? <CrspTab /> :
 activeTab === 'expansion' ? <ExpansionTab /> :
 <WebValidateTab />}
```

**d. New `ExpansionTab` component** — insert above `AdminDataPipeline` default export. All `style={{}}` inline props, zero Tailwind.

Layout:
```
┌─ Makes List card ────────────────────────────────────┐
│  Heading: "Kenya-Market Makes"  [+ Add Make] button  │
│  Table rows: Make | Year Tier | Sources | Enabled    │
│    each row: inline edit (tier dropdown, enable tog) │
│    each row: [Delete] button                         │
│  Source columns: NHTSA / CQ / cars-data / car.info   │
│    show slug text, greyed if null                    │
└───────────────────────────────────────────────────────┘

┌─ Run controls ───────────────────────────────────────┐
│  [Run Expansion]  [Pause] [Resume] [Cancel]           │
│  Progress bar: makes_processed / makes_total          │
│  "Processing: TOYOTA" label                          │
└───────────────────────────────────────────────────────┘

┌─ Stats row ──────────────────────────────────────────┐
│  Staged: N  |  Skipped (already in master): N         │
│  Source chips: nhtsa N | carquery N | carsdata N      │
└───────────────────────────────────────────────────────┘

┌─ Log panel ──────────────────────────────────────────┐
│  Reuse existing LogPanel / LogLine components         │
└───────────────────────────────────────────────────────┘
```

Makes table behaviour:
- Loads on tab mount via `getExpansionMakes()`
- Tier dropdown (`default` / `commercial` / `chinese`) calls `updateExpansionMake` on change
- Enabled toggle calls `updateExpansionMake` on change
- [+ Add Make] opens an inline form row at the bottom of the table
- [Delete] calls `deleteExpansionMake` with confirmation prompt
- Run button disabled while pipeline is running

---

## Dedup Logic (confirmed in existing pipeline)

`_load_existing_pairs()` in `vehicle_coverage_expansion.py` queries `vehicle_years` for all `(make, model, year)` tuples at pipeline startup. Only rows not in that set are written to `vehicle_years_staging`. The existing staging → commit flow promotes them to `vehicle_years`.

Makes/models not yet in `vehicle_years` are the explicit target — the pipeline stages them and the admin commits them. Trims (TX, VX, GX etc.) are NOT stored as separate rows; the matcher handles trim disambiguation via fuzzy matching at query time.

---

## Confirmed Kenya-Market Gaps (from live DB audit — 2026-06-24)

These are real vehicles used in Kenya today with no match in `vehicle_years`:

| Make | Missing models | Impact |
|---|---|---|
| HAVAL | H6, H9, Jolion, F7, Dargo | H6 is a top-selling SUV in Kenya; only 4 generic entries exist (CITY, PREMIUM, ULTRA) |
| FOTON | Aumark, Ollin, Tornado, View | 0 models in DB — very common Kenyan commercial trucks |
| FAW | Bestune T77, Sirius, trucks | Only 2 internal Chinese code entries (CA3252, CA6371) — not recognisable |
| RENAULT | Duster | 68 models in DB but all French-market only; Duster is one of Kenya's most popular SUVs |
| MITSUBISHI | Pajero Sport, ASX, L200 | DB has JDM Pajero trim names only; Pajero Sport (body-on-frame Kenya market) missing |

**Toyota missing models (from audit):**

| Missing model | Production years | Kenya relevance |
|---|---|---|
| Land Cruiser 100 / 105 | 1998–2007 | Very common — predecessor to 200 series |
| Land Cruiser Prado 90 | 1996–2002 | Older but still seen |
| Land Cruiser Prado 120 | 2002–2009 | Common mid-era Prado |
| Land Cruiser Prado 150 | 2009–2024 | Most common Prado on Kenyan roads today |
| Toyota Succeed | 2002–present | Estate version of Probox — extremely common |
| Toyota Hilux Surf / 4Runner | 1984–2009 | 4x4 SUV, very widely used |
| Toyota Kluger / Highlander | 2000–present | Popular mid-size family SUV |
| Toyota Avanza | 2003–present | Affordable 7-seater MPV, popular in East Africa |
| Toyota IST | 2002–2016 | Compact JDM car, common import |
| Toyota Caldina | 1992–2007 | JDM wagon, seen regularly |
| Toyota Ipsum / Nadia / Gaia | 1995–2009 | JDM 7-seater MPVs |
| Toyota Mark II / Chaser | 1968–2007 | Classic JDM luxury sedans |
| Toyota Runx / Allex | 2001–2006 | JDM compact hatches, common budget imports |

Current `vehicle_years` row count: **58,350** (target: 100k)

---

## Verification

1. `alembic upgrade head` — `expansion_makes` table created and pre-seeded with curated list
2. `python -c "from pipelines.vehicle_coverage_expansion import TARGET_MAKES; print(len(TARGET_MAKES))"` — ~43 (HINO deduped, JAC added, Vauxhall/Dodge/Eicher removed)
3. Admin → Data Pipeline → **Vehicle Expansion** tab appears as third tab
4. Makes table loads showing all seeded makes with tier and source slugs
5. Edit a year tier dropdown → change persists on page reload
6. Add a new make → appears in table; delete it → removed
7. Click **Run Expansion** → progress bar increments per make, log streams live
8. Pause / Resume / Cancel all work
9. On completion: Staging Review (CRSP tab) shows new rows
10. Commit → `SELECT COUNT(*) FROM vehicle_years` increases
