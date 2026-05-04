"""Generate a structured accuracy report for the Battery Finder matcher.

Produces an Excel workbook (by default: `accuracy_analysis_hard_failure_modes_200.xlsx`)
that mirrors the structure and intent of `accuracy_analysis.xlsx`, but focuses on a
deterministic 200-case "hard failure mode" suite across both UI input types:

- Select mode: exact Make/Model/Year from the dataset (baseline + wrong optional specs)
- Type mode: noisy/typed Make/Model/Year with required Engine CC + Fuel Type

Metrics captured:
- Vehicle match accuracy (matched_make/model/year vs expected)
- Spec-behaviour accuracy (whether engine_cc/fuel_type are treated as expected)
- Match-type and confidence distributions

Usage:
  python scripts/generate_accuracy_report_hard_failure_modes_200.py

Environment overrides:
  N_TOTAL=200                Total cases (default 200)
  SELECT_RATIO=0.5           Fraction of cases in select mode (default 0.5)
  OUT_XLSX=path.xlsx         Output workbook path
"""

from __future__ import annotations

import os
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import pandas as pd


# Ensure repository root is on sys.path so we can import local modules
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

import matcher  # noqa: E402


_WS_RE = re.compile(r"\s+")


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().upper()
    s = _WS_RE.sub(" ", s)
    return s


def _norm_fuel(value: Any) -> str:
    # mirror matcher behaviour for comparison
    return str(matcher._norm_fuel(None if value is None else str(value))).strip().upper()  # type: ignore[attr-defined]


def _dataset_fuel_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    return _norm_fuel(s)


def _expected_specs_from_dataset(
    dataset_cc: Optional[int],
    dataset_fuel: Optional[str],
    input_cc: Optional[int],
    input_fuel: Optional[str],
) -> tuple[Optional[int], Optional[str]]:
    # When dataset has values, it should override; otherwise preserve caller input.
    exp_cc = dataset_cc if dataset_cc is not None else input_cc
    exp_fuel = dataset_fuel if dataset_fuel is not None else (None if input_fuel is None else _norm_fuel(input_fuel))
    return exp_cc, exp_fuel


def _safe_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pick_wrong_fuel(correct: str) -> str:
    c = _norm_fuel(correct)
    # choose a deliberately different fuel label
    options = ["PETROL", "DIESEL", "HYBRID", "EV"]
    options = [o for o in options if o != c]
    return random.choice(options) if options else "PETROL"


def _pick_wrong_cc(correct: Optional[int]) -> int:
    base = correct if isinstance(correct, int) and 600 <= correct <= 8000 else 1500
    # force a meaningful delta
    delta = random.choice([400, 600, 800, 1200, 1600, 2000])
    if random.random() < 0.5:
        return max(600, base - delta)
    return min(8000, base + delta)


# ----------------------------
# Hard-noise mutators (Type mode)
# ----------------------------

def _typo_insert(s: str) -> str:
    if not s:
        return s
    i = random.randrange(0, len(s))
    return s[:i] + random.choice("abcdefghijklmnopqrstuvwxyz") + s[i:]


def _typo_swap(s: str) -> str:
    if len(s) < 2:
        return s
    i = random.randrange(0, len(s) - 1)
    lst = list(s)
    lst[i], lst[i + 1] = lst[i + 1], lst[i]
    return "".join(lst)


def _truncate(s: str) -> str:
    if len(s) <= 5:
        return s
    cut = random.randint(3, max(3, len(s) - 2))
    return s[:cut]


def _remove_vowels(s: str) -> str:
    return "".join([c for c in s if c.lower() not in "aeiou"])


def _remove_spaces(s: str) -> str:
    return s.replace(" ", "")


def _add_trim_noise(s: str) -> str:
    # Add common trim tokens that can confuse token-set matching
    tokens = ["G", "V", "RS", "ACTIVE", "SPORT", "EXECUTIVE", "LIMITED", "L", "X", "GX"]
    noise = " ".join(random.sample(tokens, k=random.choice([1, 2])))
    return f"{s} {noise}".strip()


TYPE_MODEL_MUTATORS: list[tuple[str, Any]] = [
    ("typo_insert", _typo_insert),
    ("typo_swap", _typo_swap),
    ("truncate", _truncate),
    ("remove_vowels", _remove_vowels),
    ("remove_spaces", _remove_spaces),
    ("add_trim_noise", _add_trim_noise),
    ("upper", lambda s: s.upper()),
]


@dataclass(frozen=True)
class Case:
    case_id: str
    input_type: str  # 'select' | 'type'
    failure_mode: str
    input_make: str
    input_model: str
    input_year: int
    input_engine_cc: Optional[int]
    input_fuel_type: Optional[str]
    expected_make: str
    expected_model: str
    expected_year: int
    expected_engine_cc: Optional[int]
    expected_fuel_type: Optional[str]


def _load_vehicle_rows() -> pd.DataFrame:
    veh = matcher._vehicles().copy()  # type: ignore[attr-defined]
    veh = veh.dropna(subset=["make", "model", "year"]).copy()
    veh["year"] = veh["year"].astype(int)
    return veh


def _build_cases(n_total: int, select_ratio: float) -> list[Case]:
    veh = _load_vehicle_rows()

    # Use a stable unique set of base rows to prevent duplicate expectations.
    base = veh[["make", "model", "year", "engine_capacity", "fuel"]].drop_duplicates().copy()

    n_select = int(round(n_total * select_ratio))
    n_type = n_total - n_select

    if len(base) < n_total:
        raise RuntimeError(f"Not enough unique vehicle rows to sample {n_total} cases (have {len(base)}).")

    select_rows = base.sample(n=n_select, random_state=42).to_dict(orient="records")
    type_rows = base.sample(n=n_type, random_state=7).to_dict(orient="records")

    cases: list[Case] = []

    # Select-mode cases: exact make/model/year; user may provide incorrect optional specs.
    for i, r in enumerate(select_rows, start=1):
        make = str(r["make"])
        model = str(r["model"])
        year = int(r["year"])
        ds_cc = _safe_int(r.get("engine_capacity"))
        ds_fuel = _dataset_fuel_or_none(r.get("fuel"))

        # Wrong optional specs (common user error in Select path).
        in_cc = _pick_wrong_cc(ds_cc)
        in_fuel = _pick_wrong_fuel(ds_fuel or "PETROL")

        exp_cc, exp_fuel = _expected_specs_from_dataset(ds_cc, ds_fuel, in_cc, in_fuel)

        cases.append(
            Case(
                case_id=f"S{i:03d}",
                input_type="select",
                failure_mode="wrong_optional_specs",
                input_make=make,
                input_model=model,
                input_year=year,
                input_engine_cc=in_cc,
                input_fuel_type=in_fuel,
                expected_make=make,
                expected_model=model,
                expected_year=year,
                expected_engine_cc=exp_cc,
                expected_fuel_type=exp_fuel,
            )
        )

    # Type-mode cases: mutate make/model/year; engine_cc & fuel_type provided.
    for i, r in enumerate(type_rows, start=1):
        make = str(r["make"])
        model = str(r["model"])
        year = int(r["year"])
        ds_cc = _safe_int(r.get("engine_capacity"))
        ds_fuel = _dataset_fuel_or_none(r.get("fuel"))

        mut_name, mut_fn = random.choice(TYPE_MODEL_MUTATORS)
        noisy_model = mut_fn(model)
        failure_mode = f"model_{mut_name}"

        noisy_make = make
        if random.random() < 0.25:
            noisy_make = _typo_swap(make)
            failure_mode += "+make_typo"

        noisy_year = year
        # year drift: mostly within ±3, with some intentionally out-of-window
        roll = random.random()
        if roll < 0.35:
            noisy_year = year + random.choice([-1, 1, -2, 2, -3, 3])
            failure_mode += "+year_drift_pm3"
        elif roll < 0.45:
            noisy_year = year + random.choice([-5, 5, -7, 7])
            failure_mode += "+year_drift_gt3"

        # In Type mode, we assume the user provides CC/fuel (UI enforces).
        # If CC is missing in the base row, provide a typical value.
        in_cc = ds_cc if ds_cc is not None else random.choice([1000, 1300, 1500, 1800, 2000, 2500])
        in_fuel = (ds_fuel or "PETROL")

        exp_cc, exp_fuel = _expected_specs_from_dataset(ds_cc, ds_fuel, int(in_cc), in_fuel)

        cases.append(
            Case(
                case_id=f"T{i:03d}",
                input_type="type",
                failure_mode=failure_mode,
                input_make=noisy_make,
                input_model=noisy_model,
                input_year=int(noisy_year),
                input_engine_cc=int(in_cc),
                input_fuel_type=in_fuel,
                expected_make=make,
                expected_model=model,
                expected_year=year,
                expected_engine_cc=exp_cc,
                expected_fuel_type=exp_fuel,
            )
        )

    # stable order: select first then type
    return cases


def _run_cases(cases: list[Case]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for c in cases:
        out = matcher.recommend(
            c.input_make,
            c.input_model,
            int(c.input_year),
            engine_cc=c.input_engine_cc,
            fuel_type=c.input_fuel_type,
            enable_aliases=True,
        )
        primary = out.get("primary") or {}

        matched_make = out.get("matched_make")
        matched_model = out.get("matched_model")
        matched_year = out.get("matched_year")

        vehicle_match_ok = (
            _norm_text(matched_make) == _norm_text(c.expected_make)
            and _norm_text(matched_model) == _norm_text(c.expected_model)
            and matched_year == c.expected_year
        )

        spec_ok = (
            (out.get("engine_cc") == c.expected_engine_cc)
            and (_norm_fuel(out.get("fuel_type")) == _norm_fuel(c.expected_fuel_type))
        )

        rows.append(
            {
                "Case ID": c.case_id,
                "Input Type": c.input_type,
                "Failure Mode": c.failure_mode,
                "Input Make": c.input_make,
                "Input Model": c.input_model,
                "Input Year": c.input_year,
                "Input Engine CC": c.input_engine_cc,
                "Input Fuel": c.input_fuel_type,
                "Expected Make": c.expected_make,
                "Expected Model": c.expected_model,
                "Expected Year": c.expected_year,
                "Expected Engine CC": c.expected_engine_cc,
                "Expected Fuel": c.expected_fuel_type,
                "Actual Matched Make": matched_make,
                "Actual Matched Model": matched_model,
                "Actual Matched Year": matched_year,
                "Actual Engine CC": out.get("engine_cc"),
                "Actual Fuel": out.get("fuel_type"),
                "Match Type": out.get("match_type"),
                "Confidence": out.get("confidence"),
                "Battery Region": out.get("battery_region"),
                "Recommended Ah": out.get("recommended_ah"),
                "Preferred Tech": out.get("preferred_tech"),
                "Primary Battery Code": primary.get("battery_code"),
                "Primary Model Key": primary.get("model_key"),
                "Primary Ah": primary.get("ah"),
                "Vehicle Match ✓": "PASS" if vehicle_match_ok else "FAIL",
                "Spec Behaviour ✓": "PASS" if spec_ok else "FAIL",
            }
        )

    return pd.DataFrame(rows)


def _summarise(df: pd.DataFrame) -> pd.DataFrame:
    def _acc(series: pd.Series) -> float:
        if series.empty:
            return 0.0
        return 100.0 * (series == "PASS").mean()

    summary_rows: list[dict[str, Any]] = []
    for mode in ["select", "type", "ALL"]:
        sub = df if mode == "ALL" else df[df["Input Type"] == mode]
        summary_rows.append(
            {
                "Input Type": mode,
                "Total Cases": int(len(sub)),
                "Vehicle Match Accuracy %": round(_acc(sub["Vehicle Match ✓"]), 1),
                "Spec Behaviour Accuracy %": round(_acc(sub["Spec Behaviour ✓"]), 1),
                "Avg Confidence": round(float(sub["Confidence"].mean()) if len(sub) else 0.0, 1),
                "Exact Match %": round(100.0 * (sub["Match Type"] == "Exact Match").mean() if len(sub) else 0.0, 1),
                "Close Match %": round(100.0 * (sub["Match Type"] == "Close Match").mean() if len(sub) else 0.0, 1),
                "Rule-Based %": round(100.0 * (sub["Match Type"] == "Estimated (Rule-Based)").mean() if len(sub) else 0.0, 1),
            }
        )
    return pd.DataFrame(summary_rows)


def _failure_mode_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Failure Mode", "Count", "Vehicle Match Accuracy %", "Spec Behaviour Accuracy %"])

    out_rows: list[dict[str, Any]] = []
    for mode, sub in df.groupby("Failure Mode", dropna=False):
        out_rows.append(
            {
                "Failure Mode": str(mode),
                "Count": int(len(sub)),
                "Vehicle Match Accuracy %": round(100.0 * (sub["Vehicle Match ✓"] == "PASS").mean(), 1),
                "Spec Behaviour Accuracy %": round(100.0 * (sub["Spec Behaviour ✓"] == "PASS").mean(), 1),
                "Most Common Match Type": Counter(sub["Match Type"].tolist()).most_common(1)[0][0] if len(sub) else None,
            }
        )

    bd = pd.DataFrame(out_rows)
    bd = bd.sort_values(["Count", "Vehicle Match Accuracy %"], ascending=[False, True]).reset_index(drop=True)
    return bd


def _pipeline_stats() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    files = [
        ("battery_lookup_dataset.csv", ["make", "model", "engine_capacity", "fuel"]),
        ("vehicle_years.csv", ["make", "model", "year", "engine_capacity", "fuel"]),
        ("unmatched_models.csv", None),
        ("nts_vehicles_clean.csv", ["make", "model", "year"]),
        ("nts_vehicles_with_cc.csv", None),
    ]

    for fname, cols in files:
        path = os.path.join(ROOT, fname)
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue

        if cols is not None:
            present = [c for c in cols if c in df.columns]
            df2 = df[present].copy() if present else df
        else:
            df2 = df

        rows.append(
            {
                "File": fname,
                "Rows": int(len(df2)),
                "Columns": int(len(df.columns)),
                "Unique Makes": int(df2["make"].nunique()) if "make" in df2.columns else None,
                "Unique Models": int(df2["model"].nunique()) if "model" in df2.columns else None,
                "Year Min": int(df2["year"].min()) if "year" in df2.columns and len(df2) else None,
                "Year Max": int(df2["year"].max()) if "year" in df2.columns and len(df2) else None,
            }
        )

    return pd.DataFrame(rows)


def _app_state_sheet(summary_df: pd.DataFrame, pipeline_df: pd.DataFrame) -> pd.DataFrame:
    # Keep this sheet human-readable inside Excel.
    def _get_summary(mode: str, col: str) -> Any:
        row = summary_df[summary_df["Input Type"] == mode]
        if row.empty:
            return None
        return row.iloc[0].get(col)

    file_rows = {r["File"]: r for r in pipeline_df.to_dict(orient="records")}

    return pd.DataFrame(
        [
            {"Section": "App", "Item": "Backend", "Value": "FastAPI (app.py) serving /api/makes, /api/models/{make}, /api/years, /api/recommend"},
            {"Section": "App", "Item": "Frontend", "Value": "React + TS (frontend/) with dual input type toggle: Select vs Type"},
            {"Section": "Matcher", "Item": "Primary vehicle data", "Value": "vehicle_years.csv (loaded by matcher._vehicles())"},
            {"Section": "Matcher", "Item": "Alias data", "Value": "model_aliases.csv (optional alias recovery)"},
            {"Section": "Pipelines", "Item": "CRSP prep", "Value": "dataprep.py → battery_lookup_dataset.csv"},
            {"Section": "Pipelines", "Item": "Year enrichment", "Value": "enrich_years.py → vehicle_years.csv"},
            {"Section": "Pipelines", "Item": "NTS prep", "Value": "nts_dataprep.py → nts_vehicles_clean.csv"},
            {"Section": "Pipelines", "Item": "NTS CC/Fuel enrichment", "Value": "allocate_cc_fuel.py → nts_vehicles_with_cc.csv (via fueleconomy.gov + public sources)"},
            {"Section": "Accuracy", "Item": "200-case suite", "Value": "Deterministic hard-failure-mode suite split across Select and Type input types"},
            {"Section": "Accuracy", "Item": "Overall vehicle match accuracy", "Value": f"{_get_summary('ALL', 'Vehicle Match Accuracy %')}%"},
            {"Section": "Accuracy", "Item": "Select vehicle match accuracy", "Value": f"{_get_summary('select', 'Vehicle Match Accuracy %')}%"},
            {"Section": "Accuracy", "Item": "Type vehicle match accuracy", "Value": f"{_get_summary('type', 'Vehicle Match Accuracy %')}%"},
            {"Section": "Data", "Item": "vehicle_years.csv rows", "Value": file_rows.get("vehicle_years.csv", {}).get("Rows")},
            {"Section": "Data", "Item": "battery_lookup_dataset.csv rows", "Value": file_rows.get("battery_lookup_dataset.csv", {}).get("Rows")},
            {"Section": "Data", "Item": "nts_vehicles_clean.csv rows", "Value": file_rows.get("nts_vehicles_clean.csv", {}).get("Rows")},
        ]
    )


def _real_world_failures_sheet(df: pd.DataFrame) -> pd.DataFrame:
    # Derive a concise summary table similar to the template workbook.
    if df.empty:
        return pd.DataFrame(columns=["Failure Mode", "Affects", "Frequency", "Vehicle Match Accuracy", "Spec Behaviour Accuracy", "Notes"])

    grouped = (
        df.groupby(["Input Type", "Failure Mode"], dropna=False)
        .agg(
            frequency=("Case ID", "count"),
            vehicle_acc=("Vehicle Match ✓", lambda s: float((s == "PASS").mean()) * 100.0),
            spec_acc=("Spec Behaviour ✓", lambda s: float((s == "PASS").mean()) * 100.0),
        )
        .reset_index()
    )

    # Show the most impactful (low accuracy, higher frequency) issues first.
    grouped = grouped.sort_values(["vehicle_acc", "frequency"], ascending=[True, False]).reset_index(drop=True)

    def _note(fm: str, input_type: str) -> str:
        fm = str(fm)
        if input_type == "select" and fm == "wrong_optional_specs":
            return "Select path: optional engine_cc/fuel_type can steer output if provided. If you intend DB override, this is a gap."
        if "truncate" in fm:
            return "Short model strings can collide with many trims; tie-breaking may select the wrong variant."
        if "remove_spaces" in fm:
            return "No-space inputs reduce token quality; consider additional normalisation (space-insertion) before fuzzy match."
        if "remove_vowels" in fm:
            return "Aggressive abbreviation; often drops below fuzzy thresholds for correct variant selection."
        if "make_typo" in fm:
            return "Make typo recovery relies on fuzzy make match ≥ 75; below that, matching can drift."
        if "year_drift_gt3" in fm:
            return "Year drift beyond ±3 forces fallback or nearest-year selection, increasing mismatch risk."
        return ""

    out_rows: list[dict[str, Any]] = []
    for _, r in grouped.head(15).iterrows():
        out_rows.append(
            {
                "Failure Mode": r["Failure Mode"],
                "Affects": r["Input Type"],
                "Frequency": int(r["frequency"]),
                "Vehicle Match Accuracy": round(float(r["vehicle_acc"]), 1),
                "Spec Behaviour Accuracy": round(float(r["spec_acc"]), 1),
                "Notes": _note(r["Failure Mode"], r["Input Type"]),
            }
        )
    return pd.DataFrame(out_rows)


def _key_sheet() -> pd.DataFrame:
    # Updated to reflect current matcher behaviour (caller-provided cc/fuel are preserved).
    return pd.DataFrame(
        [
            {
                "MATCH TYPE — possible values": "Value",
                "When it occurs": "When it occurs",
                "Confidence range": "Confidence range",
                "Data source used": "Data source used",
            },
            {
                "MATCH TYPE — possible values": "Exact Match",
                "When it occurs": "Make matched in DB, model fuzzy-score ≥ 90, requested year found exactly in vehicle_years.csv",
                "Confidence range": "100 (or fuzzy score if < 90)",
                "Data source used": "engine_cc/fuel_type come from the DB row when present; otherwise they fall back to the caller-provided values (or defaults).",
            },
            {
                "MATCH TYPE — possible values": "Close Match",
                "When it occurs": "Make matched, model fuzzy-score ≥ 60, but exact year not found. Nearest year within ±3 years is used instead",
                "Confidence range": "60–89 (reduced by 3 per year of drift)",
                "Data source used": "engine_cc/fuel_type come from the nearest DB row when present; otherwise they fall back to the caller-provided values (or defaults).",
            },
            {
                "MATCH TYPE — possible values": "Estimated (Rule-Based)",
                "When it occurs": "Model fuzzy-score < 60, or make not found in DB at all",
                "Confidence range": "40",
                "Data source used": "engine_cc defaults to 1500cc if not supplied; fuel_type defaults to PETROL if not supplied.",
            },
        ]
    )


def main() -> int:
    random.seed(42)

    n_total = int(os.environ.get("N_TOTAL", "200"))
    select_ratio = float(os.environ.get("SELECT_RATIO", "0.5"))
    out_xlsx = os.environ.get("OUT_XLSX", os.path.join(ROOT, "accuracy_analysis_hard_failure_modes_200.xlsx"))

    cases = _build_cases(n_total=n_total, select_ratio=select_ratio)
    df = _run_cases(cases)

    select_df = df[df["Input Type"] == "select"].reset_index(drop=True)
    type_df = df[df["Input Type"] == "type"].reset_index(drop=True)
    summary_df = _summarise(df)
    breakdown_df = _failure_mode_breakdown(df)
    pipeline_df = _pipeline_stats()
    key_df = _key_sheet()
    app_state_df = _app_state_sheet(summary_df, pipeline_df)
    rwf_df = _real_world_failures_sheet(df)

    # "Check Summary" sheet in the style of accuracy_analysis.xlsx
    check_rows = [
        {
            "Check": "Vehicle Match",
            "Description": "Did the engine match the expected make/model/year?",
            "Cases Passing (Now)": f"{int((df['Vehicle Match ✓'] == 'PASS').sum())}/{len(df)}",
            "Accuracy Now (%)": round(100.0 * (df["Vehicle Match ✓"] == "PASS").mean(), 1),
            "Notes": "PASS when matched_make/model/year equals the base dataset row used to construct the case.",
        },
        {
            "Check": "Spec Behaviour",
            "Description": "Were engine_cc and fuel_type treated as expected for the input type?",
            "Cases Passing (Now)": f"{int((df['Spec Behaviour ✓'] == 'PASS').sum())}/{len(df)}",
            "Accuracy Now (%)": round(100.0 * (df["Spec Behaviour ✓"] == "PASS").mean(), 1),
            "Notes": "Select expects DB values to win; Type expects user-provided values to win.",
        },
    ]
    checks_df = pd.DataFrame(check_rows)

    meta_df = pd.DataFrame(
        [
            {"Field": "Generated At", "Value": _now_iso()},
            {"Field": "Total Cases", "Value": n_total},
            {"Field": "Select Cases", "Value": int(len(select_df))},
            {"Field": "Type Cases", "Value": int(len(type_df))},
            {"Field": "Repo Root", "Value": ROOT},
        ]
    )

    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        key_df.to_excel(writer, sheet_name="Key", index=False)
        meta_df.to_excel(writer, sheet_name="Meta", index=False)
        app_state_df.to_excel(writer, sheet_name="App State", index=False)
        checks_df.to_excel(writer, sheet_name="Check Summary", index=False)
        rwf_df.to_excel(writer, sheet_name="Real-World Failures", index=False)
        summary_df.to_excel(writer, sheet_name="200-Case Summary", index=False)
        breakdown_df.to_excel(writer, sheet_name="Failure Mode Breakdown", index=False)
        pipeline_df.to_excel(writer, sheet_name="Pipeline Summary", index=False)
        select_df.to_excel(writer, sheet_name="200-Case Select", index=False)
        type_df.to_excel(writer, sheet_name="200-Case Type", index=False)

    print(f"Wrote: {out_xlsx}")
    print(summary_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
