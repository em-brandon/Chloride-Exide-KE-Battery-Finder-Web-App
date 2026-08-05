"""
Regression tests for the enrich_years.py matching/normalisation defects
fixed on 2026-08-05 (CLAUDE.md's year-data remediation task list item 3):
a case-sensitivity bug that corrupted every rapidfuzz score in this module,
an untrimmed fueleconomy match query, too-permissive threshold, unbounded
open-ended-span defaulting, and Wikidata's removal from the source chain.

No network calls. Small hand-built DataFrames stand in for the real
fueleconomy_vehicles.csv (deterministic, fast) rather than depending on the
downloaded cache file — matches this repo's existing test convention of
inline fixtures over recorded external data.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipelines.enrich_years as ey
from pipelines.model_name_utils import extract_base_model, extract_search_model


def _fe_df(rows):
    return pd.DataFrame(rows, columns=["year", "make", "model"])


# =========================
# Case-sensitivity fix
# =========================

def test_fueleconomy_match_is_case_insensitive():
    # All-caps CRSP-style query against mixed-case EPA-style listing —
    # verified live this used to score 32 (false match to an unrelated
    # model) instead of 100 against the real "Land Cruiser" entry.
    df = _fe_df([
        (y, "Toyota", "Land Cruiser") for y in range(1990, 1995)
    ] + [
        (y, "Toyota", "RAV4 EV") for y in range(1997, 2000)
    ])
    years = ey.lookup_years_fueleconomy("TOYOTA", "TOYOTA LAND CRUISER 200 VX", df)
    assert years == list(range(1990, 1995))


def test_nhtsa_best_model_match_is_case_insensitive():
    nhtsa_models = [{"Model_Name": "Land Cruiser"}, {"Model_Name": "RAV4"}]
    matched, score = ey.best_model_match("LAND CRUISER", nhtsa_models)
    assert matched == "Land Cruiser"
    assert score >= ey.MATCH_SCORE_THRESHOLD


# =========================
# Trim-stripped fueleconomy query + raised threshold
# =========================

def test_fueleconomy_rejects_lutecia_gta_false_match():
    # The exact bug reproduced live in CLAUDE.md's investigation:
    # "RENAULT LUTECIA GT LINE" used to match EPA's unrelated "GTA" at
    # 46.15 (base_model "LUTECIA GT" against the old threshold of 45).
    # extract_search_model() strips "GT" (a real Renault Lutecia trim is
    # not a US-market Renault), leaving "LUTECIA" alone, which scores well
    # below the new threshold against "GTA" — correctly rejected as None.
    df = _fe_df([(y, "Renault", "GTA") for y in range(1984, 1988)])
    years = ey.lookup_years_fueleconomy("RENAULT", "RENAULT LUTECIA GT LINE", df)
    assert years is None


def test_fueleconomy_still_matches_genuine_trimmed_model():
    df = _fe_df([(y, "Toyota", "Camry") for y in range(2015, 2020)])
    years = ey.lookup_years_fueleconomy("TOYOTA", "TOYOTA CAMRY 2.5 LE AUTOMATIC", df)
    assert years == list(range(2015, 2020))


# =========================
# extract_base_model: numeric generation marker
# =========================

def test_extract_base_model_retains_numeric_generation_marker():
    assert extract_base_model("TOYOTA", "LAND CRUISER 250 VX") == "LAND CRUISER 250"
    assert extract_base_model("TOYOTA", "LAND CRUISER 300 GR SPORT") == "LAND CRUISER 300"


def test_extract_base_model_does_not_absorb_alphanumeric_engine_code():
    # "320D" contains a letter — not a bare generation number — must not
    # be captured as a 3rd base-model token.
    assert extract_base_model("BMW", "3 SERIES 320D X DRIVE") == "3 SERIES"


def test_extract_search_model_still_strips_numeric_marker_for_external_queries():
    # extract_base_model()'s new 3rd token must not leak into
    # extract_search_model()'s output — external sources like
    # fueleconomy.gov don't track per-generation numbers, so keeping "250"
    # in the search query would only hurt those matches.
    assert extract_search_model("TOYOTA", "LAND CRUISER 250 VX") == "LAND CRUISER"


def test_extract_base_model_two_tokens_when_no_third_or_non_numeric():
    assert extract_base_model("TOYOTA", "CAMRY") == "CAMRY"
    assert extract_base_model("RENAULT", "LUTECIA GT LINE") == "LUTECIA GT"


# =========================
# Open-ended span capping (not blindly defaulted to CURRENT_YEAR)
# =========================

def test_resolve_end_year_caps_open_ended_span_instead_of_current_year():
    # Regression case: CLAUDE.md found 243 variants incorrectly running to
    # CURRENT_YEAR (2026) via this exact defaulting, including
    # long-discontinued models whose source found no end date.
    result = ey._resolve_end_year(1964, None)
    assert result == 1964 + ey.MAX_OPEN_ENDED_SPAN_YEARS
    assert result != ey.CURRENT_YEAR


def test_resolve_end_year_recent_open_ended_span_still_bounded_by_current_year():
    result = ey._resolve_end_year(2021, None)
    assert result == ey.CURRENT_YEAR  # 2021 + 20 > CURRENT_YEAR, so clamps there


def test_resolve_end_year_known_end_capped_at_current_year():
    assert ey._resolve_end_year(2000, 2099) == ey.CURRENT_YEAR


def test_resolve_end_year_known_end_within_bounds_is_unchanged():
    assert ey._resolve_end_year(2000, 2010) == 2010


# =========================
# Wikidata removal
# =========================

def test_wikidata_source_no_longer_exists():
    assert not hasattr(ey, "get_years_from_wikidata")
    assert not hasattr(ey, "WIKIDATA_SPARQL")


def test_wikidata_not_in_bookkeeping_dicts():
    import inspect
    source = inspect.getsource(ey.main)
    assert "wikidata" not in source.lower()
