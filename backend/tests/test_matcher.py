"""
Unit tests for matcher.py's rule engine: normalisation, Ah/technology
selection, and the three matching layers, exercised against small synthetic
DataFrames (no DB needed).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matcher

_CACHED_FNS = (
    matcher._vehicles, matcher._make_index, matcher._batteries,
    matcher._model_aliases, matcher._inference, matcher._web_validation,
    matcher.recommend,
)

EMPTY_INFERENCE = pd.DataFrame(columns=[
    "vehicle_type", "vehicle_model", "battery_code", "frequency",
    "last_sale_date", "vtype_n", "vmodel_n", "bcode_n",
])
EMPTY_WEB_VALIDATION = pd.DataFrame(columns=["make_n", "model_n", "year", "battery_code", "ah", "technology"])
EMPTY_ALIASES = pd.DataFrame(columns=["make_n", "intl_model_n", "jdm_model_n", "priority"])


@pytest.fixture(autouse=True)
def _clear_matcher_caches():
    # matcher.py's @lru_cache loaders are process-global; clear before and
    # after every test so monkeypatched fixture data never leaks between tests.
    for fn in _CACHED_FNS:
        fn.cache_clear()
    yield
    for fn in _CACHED_FNS:
        fn.cache_clear()


def _vehicles_df(rows):
    df = pd.DataFrame(rows, columns=["make", "model", "year", "engine_capacity", "fuel"])
    df["engine_capacity"] = pd.to_numeric(df["engine_capacity"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["make_n"] = df["make"].astype(str).str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
    df["model_n"] = df["model"].astype(str).apply(matcher._norm_model_key)
    df["fuel_n"] = df["fuel"].apply(matcher._norm_fuel)
    return df


def _batteries_df(rows):
    df = pd.DataFrame(rows, columns=["Battery Code", "Model Key", "Ah", "CCA (A EN)", "Technology", "Origin", "Brand"])
    df["Ah"] = pd.to_numeric(df["Ah"], errors="coerce")
    df["CCA (A EN)"] = pd.to_numeric(df["CCA (A EN)"], errors="coerce")
    return df


@pytest.fixture()
def wire_matcher(monkeypatch):
    """Wire synthetic vehicle/battery/alias tables into matcher.py's module-level loaders."""
    def _wire(vehicle_rows, battery_rows, alias_rows=None):
        vdf = _vehicles_df(vehicle_rows)
        bdf = _batteries_df(battery_rows)
        monkeypatch.setattr(matcher, "_vehicles", lambda: vdf.copy())
        monkeypatch.setattr(matcher, "_batteries", lambda: bdf.copy())
        if alias_rows:
            raw = pd.DataFrame(alias_rows, columns=["make", "international_model", "jdm_model", "priority"])
            out = pd.DataFrame()
            out["make_n"] = raw["make"].astype(str).str.upper().str.strip()
            out["intl_model_n"] = raw["international_model"].astype(str).str.upper().str.strip()
            out["jdm_model_n"] = raw["jdm_model"].astype(str).str.upper().str.strip()
            out["priority"] = raw["priority"].astype(int)
            monkeypatch.setattr(matcher, "_model_aliases", lambda: out.copy())
        else:
            monkeypatch.setattr(matcher, "_model_aliases", lambda: EMPTY_ALIASES.copy())
        monkeypatch.setattr(matcher, "_inference", lambda: EMPTY_INFERENCE.copy())
        monkeypatch.setattr(matcher, "_web_validation", lambda: EMPTY_WEB_VALIDATION.copy())
    return _wire


BATTERY_CATALOG = [
    ("NS40",  "NS40",  35,  330, "MF",  "Local",    "Exide"),
    ("NS60",  "NS60",  45,  400, "EFB", "Local",    "Exide"),
    ("NS70",  "NS70",  55,  480, "AGM", "Imported", "Exide"),
    ("NS70B", "NS70",  55,  480, "AGM", "Local",    "Exide"),
    ("DIN44", "DIN44", 45,  400, "EFB", "Local",    "Exide"),
    ("DIN55", "DIN55", 55,  480, "AGM", "Imported", "Exide"),
    ("DIN70", "DIN70", 70,  620, "AGM", "Imported", "Exide"),
    ("DIN80", "DIN80", 80,  700, "AGM", "Imported", "Exide"),
    ("DIN95", "DIN95", 95,  800, "AGM", "Imported", "Exide"),
]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("CX5", "CX 5"),
    ("CX-5", "CX 5"),
    ("CX 5", "CX 5"),
    ("corolla-axio", "COROLLA AXIO"),
    ("a4  quattro", "A 4 QUATTRO"),  # letter/digit boundary also gets a space, same as CX5 -> CX 5
])
def test_norm_model_key(raw, expected):
    assert matcher._norm_model_key(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Gasoline", "PETROL"),
    ("DEISEL", "DIESEL"),
    ("ELECCTRIC", "EV"),
    ("Plug-In Hybrid", "HYBRID"),
    ("Unknown Fuel Type", "PETROL"),
    (None, "PETROL"),
])
def test_norm_fuel(raw, expected):
    assert matcher._norm_fuel(raw) == expected


# ---------------------------------------------------------------------------
# Ah bracket + technology preference
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cc,fuel,year,expected", [
    (900,  "PETROL", 2015, 40),   # 35 base + 5 (2012-2017 modifier)
    (1500, "DIESEL", 2020, 60),   # 50 base + 10 (2018+)
    (3500, "PETROL", 1995, 85),   # 90 base - 5 (pre-2000)
])
def test_target_ah_brackets(cc, fuel, year, expected):
    assert matcher._target_ah(cc, fuel, year) == expected


def test_target_ah_ev_ignores_engine_cc():
    assert matcher._target_ah(0, "EV", 2022) == 55  # 45 base + 10 (2018+)


@pytest.mark.parametrize("make,expected", [
    ("BMW", "AGM"),        # luxury make always AGM
    ("MERCEDES-BENZ", "AGM"),
])
def test_preferred_tech_luxury_always_agm(make, expected):
    assert matcher._preferred_tech(1000, "PETROL", 2015, make, stop_start=False) == expected


def test_preferred_tech_ev_is_mf():
    assert matcher._preferred_tech(0, "EV", 2022, "NISSAN", stop_start=True) == "MF"


def test_preferred_tech_hybrid_is_efb():
    assert matcher._preferred_tech(1500, "HYBRID", 2018, "TOYOTA", stop_start=True) == "EFB"


def test_preferred_tech_stop_start_off_is_mf():
    assert matcher._preferred_tech(1500, "PETROL", 2018, "TOYOTA", stop_start=False) == "MF"


def test_preferred_tech_stop_start_diesel_is_agm():
    assert matcher._preferred_tech(2000, "DIESEL", 2018, "TOYOTA", stop_start=True) == "AGM"


# ---------------------------------------------------------------------------
# Region detection
# ---------------------------------------------------------------------------

def test_make_region_ns_for_japanese_make():
    assert matcher._make_region("TOYOTA") == "NS"


def test_make_region_din_default_for_unknown_make():
    assert matcher._make_region("SOME UNKNOWN MAKE") == "DIN"


# ---------------------------------------------------------------------------
# recommend() — three matching layers
# ---------------------------------------------------------------------------

def test_recommend_exact_match(wire_matcher):
    wire_matcher(
        vehicle_rows=[("TOYOTA", "COROLLA", 2015, 1500, "PETROL")],
        battery_rows=BATTERY_CATALOG,
    )
    result = matcher.recommend("TOYOTA", "COROLLA", 2015)
    assert result["match_type"] == "Exact Match"
    assert result["confidence"] == 100
    assert result["matched_year"] == 2015


def test_recommend_soft_match_within_three_years(wire_matcher):
    wire_matcher(
        vehicle_rows=[("TOYOTA", "COROLLA", 2015, 1500, "PETROL")],
        battery_rows=BATTERY_CATALOG,
    )
    result = matcher.recommend("TOYOTA", "COROLLA", 2017)
    assert result["match_type"] == "Close Match"
    assert result["matched_year"] == 2015
    assert 60 <= result["confidence"] < 100


def test_recommend_falls_back_to_rule_based_for_unknown_make(wire_matcher):
    wire_matcher(
        vehicle_rows=[("TOYOTA", "COROLLA", 2015, 1500, "PETROL")],
        battery_rows=BATTERY_CATALOG,
    )
    result = matcher.recommend("NONEXISTENT MAKE", "SOME MODEL", 2020, engine_cc=1500, fuel_type="PETROL")
    assert result["match_type"] == "Estimated (Rule-Based)"
    assert result["confidence"] == 40
    assert result["matched_year"] is None


def test_recommend_prefix_tie_break_prefers_year_proximity(wire_matcher):
    # Two trims share the "COROLLA AXIO" prefix; the correct pick depends on
    # which one actually has a row near the requested year, not just fuzzy score.
    wire_matcher(
        vehicle_rows=[
            ("TOYOTA", "COROLLA AXIO G", 2010, 1500, "PETROL"),
            ("TOYOTA", "COROLLA AXIO X", 2018, 1500, "PETROL"),
        ],
        battery_rows=BATTERY_CATALOG,
    )
    near_g = matcher.recommend("TOYOTA", "COROLLA AXIO", 2011)
    assert near_g["matched_model"] == "COROLLA AXIO G"

    near_x = matcher.recommend("TOYOTA", "COROLLA AXIO", 2019)
    assert near_x["matched_model"] == "COROLLA AXIO X"


def test_recommend_alias_resolves_international_model_name(wire_matcher):
    wire_matcher(
        vehicle_rows=[("TOYOTA", "COROLLA AXIO G", 2010, 1500, "PETROL")],
        battery_rows=BATTERY_CATALOG,
        alias_rows=[("TOYOTA", "SPRINTER", "COROLLA AXIO G", 1)],
    )
    result = matcher.recommend("TOYOTA", "SPRINTER", 2011)
    assert result["matched_model"] == "COROLLA AXIO G"
    assert result["matched_year"] == 2010


def test_recommend_year_outside_window_falls_back_to_rule_based(wire_matcher):
    # "FIT" only has a 2012 row — 8 years outside the +/-3 window of the 2020
    # query. Even though the model name matches perfectly, recommend() must
    # not report a matched_model/matched_year for a year this far off; it
    # should degrade all the way to the rule-based Ah estimate instead.
    wire_matcher(
        vehicle_rows=[("HONDA", "FIT", 2012, 1300, "PETROL")],
        battery_rows=BATTERY_CATALOG,
    )
    result = matcher.recommend("HONDA", "FIT", 2020, engine_cc=1300, fuel_type="PETROL")
    assert result["match_type"] == "Estimated (Rule-Based)"
    assert result["confidence"] == 40
    assert result["matched_model"] is None
    assert result["matched_year"] is None


# ---------------------------------------------------------------------------
# _make_index() — per-make cache helper
# ---------------------------------------------------------------------------

def test_make_index_precomputes_years_by_model(wire_matcher):
    wire_matcher(
        vehicle_rows=[
            ("TOYOTA", "COROLLA", 2015, 1500, "PETROL"),
            ("TOYOTA", "COROLLA", 2016, 1500, "PETROL"),
            ("TOYOTA", "HIACE",   2005, 2500, "DIESEL"),
            ("HONDA",  "FIT",     2012, 1300, "PETROL"),
        ],
        battery_rows=BATTERY_CATALOG,
    )
    make_df, years_by_model = matcher._make_index("TOYOTA")
    assert set(make_df["make_n"]) == {"TOYOTA"}
    assert years_by_model["COROLLA"] == (2015, 2016)
    assert years_by_model["HIACE"] == (2005,)
    assert "FIT" not in years_by_model


def test_make_index_cache_cleared_reflects_new_data(wire_matcher):
    wire_matcher(
        vehicle_rows=[("TOYOTA", "COROLLA", 2015, 1500, "PETROL")],
        battery_rows=BATTERY_CATALOG,
    )
    first_df, _ = matcher._make_index("TOYOTA")
    assert len(first_df) == 1

    # Simulate a pipeline commit adding a new row, followed by the admin
    # "refresh cache" action clearing both _vehicles and _make_index.
    wire_matcher(
        vehicle_rows=[
            ("TOYOTA", "COROLLA", 2015, 1500, "PETROL"),
            ("TOYOTA", "COROLLA", 2016, 1500, "PETROL"),
        ],
        battery_rows=BATTERY_CATALOG,
    )
    matcher._make_index.cache_clear()
    second_df, second_years = matcher._make_index("TOYOTA")
    assert len(second_df) == 2
    assert second_years["COROLLA"] == (2015, 2016)
