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
        return {"battery_code": "NS70MFL POWERLAST", "technology": preferred_tech}, []

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
        return {"battery_code": "DIN060 EXIDE", "technology": preferred_tech}, []

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
        return {"battery_code": "NS40 EXIDE", "technology": preferred_tech}, []

    monkeypatch.setattr(wbv, "_select_batteries", _fake_select_batteries)

    parsed = {"ah": 40, "technology": "MF"}
    wbv._resolve_battery_code(parsed, "HONDA")

    assert seen_regions == ["NS"]


def test_resolve_battery_code_reports_the_selected_batterys_technology(monkeypatch):
    """
    The stored technology must describe the battery actually chosen, not the
    one scraped from search text and passed in as a preference.

    _select_batteries() falls back when the preferred technology isn't stocked
    at the target Ah, so the battery it returns is frequently a different
    technology. Returning the requested value alongside the resolved
    battery_code made the two columns contradict each other on ~40% of
    web_battery_validation rows (AGM 8,508 of 11,781, EFB 500 of 792), which
    is what the client saw in the exported fitment guide.
    """
    def _fake_select_batteries(target_ah, preferred_tech, region="NS"):
        # Whatever technology was preferred, nothing is stocked in it at this
        # Ah, so an MF battery comes back instead.
        return {"battery_code": "NS70MFL POWERLAST", "technology": "MF"}, []

    monkeypatch.setattr(wbv, "_select_batteries", _fake_select_batteries)

    parsed = {"ah": 65, "technology": "AGM"}
    result = wbv._resolve_battery_code(parsed, "TOYOTA")

    assert result == ("NS70MFL POWERLAST", 65, "MF")


def test_resolve_battery_code_ignores_the_scraped_technology(monkeypatch):
    """
    Ah is the ONLY figure taken from the web; technology is decided by our own
    rules and what is actually in stock.

    Search snippets name a technology far less reliably than they name a
    capacity — a listing for an AGM upgrade part reads as "AGM" for a car that
    was never built with one. Passing that scraped word through as the
    preference let a retailer's product page decide a fitment, so
    _resolve_battery_code() now derives the preference from _preferred_tech()
    (engine size, fuel, year, make, inferred stop-start) and never consults
    parsed["technology"].
    """
    seen: list[str] = []

    def _fake_select_batteries(target_ah, preferred_tech, region="NS"):
        seen.append(preferred_tech)
        return {"battery_code": "NS60 EXIDE", "technology": "MF"}, []

    monkeypatch.setattr(wbv, "_select_batteries", _fake_select_batteries)

    # A small petrol Toyota: the rules say nothing exotic, whatever the scrape
    # claims. "AGM" appearing in parsed must not reach _select_batteries.
    parsed = {"ah": 45, "technology": "AGM"}
    wbv._resolve_battery_code(parsed, "TOYOTA", engine_cc=1300,
                              fuel_type="PETROL", year=2005)

    assert seen and "AGM" not in seen
