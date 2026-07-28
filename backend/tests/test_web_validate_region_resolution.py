"""
Regression test for the DIN/NS region-resolution bug in
_resolve_battery_code() (pipelines/web_battery_validate.py).

The pipeline used to trust a scraped "region" keyword hit over the
vehicle's own make-based region, which could pick a battery_code from the
wrong region pool (e.g. a DIN-coded battery for an NS-market make like
Toyota) — pointless as well as wrong, since recommend() always
independently recomputes region = _make_region(make_n) at request time
and ignores whatever the pipeline stored. The fix: always use
_make_region(make_n), never parsed.get("region").
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipelines.web_battery_validate as wbv


def test_resolve_battery_code_ignores_scraped_region_for_ns_make(monkeypatch):
    seen_regions = []

    def _fake_select_batteries(target_ah, preferred_tech, region="NS"):
        seen_regions.append(region)
        return {"battery_code": "NS70MFL POWERLAST"}, []

    monkeypatch.setattr(wbv, "_select_batteries", _fake_select_batteries)

    # TOYOTA is an NS-region make (matcher._NS_MAKES) — a scraped "DIN" hit
    # must not override that.
    parsed = {"ah": 65, "technology": "MF", "region": "DIN"}
    result = wbv._resolve_battery_code(parsed, "TOYOTA")

    assert result == ("NS70MFL POWERLAST", 65, "MF")
    assert seen_regions == ["NS"]


def test_resolve_battery_code_ignores_scraped_region_for_din_make(monkeypatch):
    seen_regions = []

    def _fake_select_batteries(target_ah, preferred_tech, region="NS"):
        seen_regions.append(region)
        return {"battery_code": "DIN060 EXIDE"}, []

    monkeypatch.setattr(wbv, "_select_batteries", _fake_select_batteries)

    # VOLKSWAGEN is a DIN-region make (matcher._DIN_MAKES) — a scraped "NS"
    # hit must not override that either (the symmetric case).
    parsed = {"ah": 60, "technology": "MF", "region": "NS"}
    result = wbv._resolve_battery_code(parsed, "VOLKSWAGEN")

    assert result == ("DIN060 EXIDE", 60, "MF")
    assert seen_regions == ["DIN"]


def test_resolve_battery_code_uses_make_region_when_parsed_region_absent(monkeypatch):
    seen_regions = []

    def _fake_select_batteries(target_ah, preferred_tech, region="NS"):
        seen_regions.append(region)
        return {"battery_code": "NS40 EXIDE"}, []

    monkeypatch.setattr(wbv, "_select_batteries", _fake_select_batteries)

    parsed = {"ah": 40, "technology": "MF"}
    wbv._resolve_battery_code(parsed, "HONDA")

    assert seen_regions == ["NS"]
