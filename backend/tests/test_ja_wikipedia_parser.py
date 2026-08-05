"""
Unit tests for pipelines/ja_wikipedia_years.py's pure parsing functions.

No network calls, no mocking of the transport layer — matches this repo's
existing convention (see test_web_validate_region_resolution.py): monkeypatch
is only ever used on internal function references, never HTTP. Wikitext
fixtures here are real excerpts copied from live ja.wikipedia articles
(Toyota Land Cruiser, Toyota Crown, Mazda Demio, Daihatsu Hijet) fetched
during this module's development — not invented examples — except where
explicitly noted as a synthetic case (e.g. imperial-era-calendar coverage,
since no real heading in the sampled articles happened to use era notation).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipelines.ja_wikipedia_years as jwy


# =========================
# Generation-heading parsing
# =========================

def test_parse_generation_heading_with_ordinal_and_chassis_code():
    # Real Mazda Demio heading.
    parsed = jwy.parse_generation_heading("初代 DW系（1996年 - 2002年）")
    assert parsed["ordinal"] == "初代"
    assert parsed["chassis_code"] == "DW系"
    assert parsed["year_from"] == 1996
    assert parsed["year_to"] == 2002


def test_parse_generation_heading_without_ordinal():
    # Real Toyota Land Cruiser heading — no ordinal marker at all. A parser
    # requiring the ordinal would miss this and most of Land Cruiser's own
    # generations, which is the whole reason this case is tested explicitly.
    parsed = jwy.parse_generation_heading("40系（1960年 - 1984年）")
    assert parsed["ordinal"] is None
    assert parsed["chassis_code"] == "40系"
    assert parsed["year_from"] == 1960
    assert parsed["year_to"] == 1984


def test_parse_generation_heading_multiple_date_clusters():
    # Real Land Cruiser "70系" heading — production stopped and resumed
    # twice. year_from is the earliest start; year_to is None because the
    # last cluster is open-ended (still in production).
    parsed = jwy.parse_generation_heading("70系（1984年 - 2004年、2014年 - 2015年、2023年 -）")
    assert parsed["year_from"] == 1984
    assert parsed["year_to"] is None
    assert len(parsed["clusters"]) == 3
    assert parsed["clusters"][-1]["open_ended"] is True


def test_parse_generation_heading_open_ended():
    parsed = jwy.parse_generation_heading("300系（2021年 - ）")
    assert parsed["year_from"] == 2021
    assert parsed["year_to"] is None


def test_parse_generation_heading_multi_chassis_code_joined_by_slash():
    # Real Toyota Crown heading.
    parsed = jwy.parse_generation_heading("初代 RS型/S2#型/S3#型（1955年 - 1962年）")
    assert parsed["ordinal"] == "初代"
    assert parsed["chassis_code"] == "RS型/S2#型/S3#型"
    assert parsed["year_from"] == 1955
    assert parsed["year_to"] == 1962


def test_parse_generation_heading_rejects_non_generation_sections():
    for title in ["概要", "系譜", "前史", "モータースポーツ", "取扱店の変遷", "脚注", "関連項目", "外部リンク"]:
        assert jwy.parse_generation_heading(title) is None


def test_parse_generation_heading_era_calendar():
    # Synthetic — no real heading in the sampled articles used era notation,
    # but the conversion table (明治=1867/大正=1911/昭和=1925/平成=1988/令和=2018)
    # is well-defined and worth verifying directly at its boundaries.
    parsed = jwy.parse_generation_heading("初代 XX型（昭和35年 - 昭和59年）")
    assert parsed["year_from"] == 1960   # 昭和35年 = 1925 + 35
    assert parsed["year_to"] == 1984     # 昭和59年 = 1925 + 59

    parsed2 = jwy.parse_generation_heading("2代目 YY型（平成1年 - 令和5年）")
    assert parsed2["year_from"] == 1989  # 平成1年 = 1988 + 1
    assert parsed2["year_to"] == 2023    # 令和5年 = 2018 + 5


def test_extract_generations_from_headings_land_cruiser_excerpt():
    # Real excerpt: a non-generation section followed by two generation
    # headings, each with its own body text and a level-3 subsection that
    # must NOT be treated as its own generation.
    wikitext = """
== 概要 ==
世界的に有名なクロスカントリー車のひとつである。

== 40系（1960年 - 1984年） ==
40系の説明本文がここに入る。
=== 第1期 ===
40系の第1期についての詳細。

== 60系（1980年 - 1990年） ==
60系の説明本文。
"""
    gens = jwy.extract_generations_from_headings(wikitext, log=lambda m: None)
    assert [g["chassis_code"] for g in gens] == ["40系", "60系"]
    assert gens[0]["year_from"] == 1960 and gens[0]["year_to"] == 1984
    assert "第1期" in gens[0]["section_body"]  # level-3 subsection stays part of the parent generation's body
    assert gens[1]["year_from"] == 1980 and gens[1]["year_to"] == 1990


# =========================
# Infobox 販売期間 parsing
# =========================

def test_infobox_plain_text():
    wikitext = """
{{Infobox_自動車のスペック表
| 車種 = 普通自動車
| 販売期間=1962年9月 - 1967年9月
}}
"""
    gens = jwy.extract_generations_from_infobox(wikitext, log=lambda m: None)
    assert len(gens) == 1
    assert gens[0]["year_from"] == 1962 and gens[0]["year_to"] == 1967


def test_infobox_wikilinked_year():
    # Real Toyota Crown infobox value: "[[1955年]] -"
    wikitext = """
{{Infobox 自動車のスペック表
| 販売期間= [[1955年]] -
}}
"""
    gens = jwy.extract_generations_from_infobox(wikitext, log=lambda m: None)
    assert len(gens) == 1
    assert gens[0]["year_from"] == 1955 and gens[0]["year_to"] is None


def test_infobox_basic_info_template_is_excluded():
    # Infobox_自動車基本情報 is the ONE-per-article nameplate-level summary —
    # its 販売期間 field on the real Land Cruiser page literally reads
    # "[[1951年]] -", the exact same wrong nameplate-level span that caused
    # the original 1951 bug via Wikidata. It must never be extracted here.
    wikitext = """
{{Infobox_自動車基本情報
| 販売期間= [[1951年]] -
}}
"""
    gens = jwy.extract_generations_from_infobox(wikitext, log=lambda m: None)
    assert gens == []


def test_infobox_br_separated_multi_value_splits_correctly():
    # Real Land Cruiser 40系 infobox — regression test for the bug where
    # splitting on <br/> after strip_code() silently matched nothing
    # because strip_code() had already dropped the tag, collapsing two
    # distinct production runs (including a secondary Brazil-market one)
    # into a single wrong cluster.
    wikitext = """
{{Infobox_自動車のスペック表
| 販売期間 = 1960年 - 1984年<br />1968年 - 2001年 (ブラジル)
}}
"""
    gens = jwy.extract_generations_from_infobox(wikitext, log=lambda m: None)
    assert len(gens) == 2
    assert (gens[0]["year_from"], gens[0]["year_to"]) == (1960, 1984)
    assert (gens[1]["year_from"], gens[1]["year_to"]) == (1968, 2001)


def test_infobox_br_separated_labelled_multi_value():
    # Real Daihatsu Hijet-style shape: leading "label：" per <br/>-separated segment.
    wikitext = """
{{Infobox_自動車基本情報
| 販売期間 = トラック：1964年4月-1968年4月<br/>バン：1965年1月-1968年4月
}}
"""
    # basic_info is excluded by name, so use the spec-table template name
    # here purely to exercise the <br/>+label splitting logic in isolation.
    wikitext = wikitext.replace("Infobox_自動車基本情報", "Infobox_自動車のスペック表")
    gens = jwy.extract_generations_from_infobox(wikitext, log=lambda m: None)
    assert len(gens) == 2
    assert gens[0]["chassis_code"] == "トラック"
    assert (gens[0]["year_from"], gens[0]["year_to"]) == (1964, 1968)
    assert gens[1]["chassis_code"] == "バン"
    assert (gens[1]["year_from"], gens[1]["year_to"]) == (1965, 1968)


def test_infobox_nested_ublist_template():
    # Real Toyota Crown infobox value.
    wikitext = """
{{Infobox_自動車のスペック表
| 販売期間={{Ublist| 日本：2012年12月 - 2018年6月 | 中国：2015年3月 - }}
}}
"""
    gens = jwy.extract_generations_from_infobox(wikitext, log=lambda m: None)
    by_label = {g["chassis_code"]: g for g in gens}
    assert (by_label["日本"]["year_from"], by_label["日本"]["year_to"]) == (2012, 2018)
    assert (by_label["中国"]["year_from"], by_label["中国"]["year_to"]) == (2015, None)


def test_infobox_nested_dl2_template_strips_announcement_asides():
    # Real Toyota Crown infobox value — each announcement-date aside
    # "（発表:...）" must not be misread as a second production date.
    wikitext = """
{{Infobox_自動車のスペック表
| 販売期間={{dl2|クロスオーバー|2022年9月1日 - <br />（発表:2022年7月15日）|スポーツ|2023年11月 -<br />（発表:2023年10月6日）}}
}}
"""
    gens = jwy.extract_generations_from_infobox(wikitext, log=lambda m: None)
    by_label = {g["chassis_code"]: g for g in gens}
    assert (by_label["クロスオーバー"]["year_from"], by_label["クロスオーバー"]["year_to"]) == (2022, None)
    assert (by_label["スポーツ"]["year_from"], by_label["スポーツ"]["year_to"]) == (2023, None)


def test_infobox_unknown_nested_template_is_skipped_not_guessed():
    logged = []
    wikitext = """
{{Infobox_自動車のスペック表
| 販売期間={{efn|some footnote text with no date}}
}}
"""
    gens = jwy.extract_generations_from_infobox(wikitext, log=logged.append)
    assert gens == []
    assert any("efn" in msg for msg in logged)


# =========================
# Trim matching
# =========================

def _gen(chassis_code, year_from, year_to, body=""):
    return {
        "raw_title": chassis_code, "ordinal": None, "chassis_code": chassis_code,
        "year_from": year_from, "year_to": year_to, "clusters": [], "shape": "heading",
        "section_body": body,
    }


def test_match_trim_single_generation_auto_matches():
    gens = [_gen("40系", 1960, 1984)]
    result = jwy.match_trim_to_generation(gens, None, log=lambda m: None)
    assert result["status"] == "matched"
    assert result["matched"] is gens[0]


def test_match_trim_no_hint_multiple_generations_is_ambiguous():
    gens = [_gen("40系", 1960, 1984), _gen("60系", 1980, 1990)]
    result = jwy.match_trim_to_generation(gens, None, log=lambda m: None)
    assert result["status"] == "ambiguous"
    assert result["matched"] is None


def test_match_trim_exact_chassis_code_preferred_over_body_mention():
    # Regression case: a broad generation's own prose mentions the trim
    # string too (e.g. a later Crown generation's body text mentioning
    # "クロスオーバー" as one of its body styles), but an infobox generation's
    # label is an EXACT match — the exact tier must win, not "ambiguous".
    broad = _gen("S3#型", 2022, None, body="この世代はクロスオーバーやセダンなど複数のボディタイプを展開した。")
    exact = _gen("クロスオーバー", 2022, None, body="クロスオーバー")
    result = jwy.match_trim_to_generation([broad, exact], "クロスオーバー", log=lambda m: None)
    assert result["status"] == "matched"
    assert result["matched"] is exact


def test_match_trim_unique_substring_match():
    gens = [
        _gen("DE系", 2007, 2014, body="このモデルはガソリンのみ。"),
        _gen("DJ系", 2014, 2019, body="XDというディーゼルグレードが追加された。"),
    ]
    result = jwy.match_trim_to_generation(gens, "XD", log=lambda m: None)
    assert result["status"] == "matched"
    assert result["matched"]["chassis_code"] == "DJ系"


def test_match_trim_multiple_substring_matches_is_ambiguous():
    gens = [
        _gen("DE系", 2007, 2014, body="XD グレード設定。"),
        _gen("DJ系", 2014, 2019, body="XD グレード設定。"),
    ]
    result = jwy.match_trim_to_generation(gens, "XD", log=lambda m: None)
    assert result["status"] == "ambiguous"
    assert result["matched"] is None
    assert len(result["candidates"]) == 2


def test_match_trim_no_match_is_ambiguous_not_a_guess():
    gens = [_gen("DE系", 2007, 2014, body="ガソリン。"), _gen("DJ系", 2014, 2019, body="ガソリン。")]
    result = jwy.match_trim_to_generation(gens, "NOTFOUND", log=lambda m: None)
    assert result["status"] == "ambiguous"
    assert result["matched"] is None


def test_match_trim_empty_generations():
    result = jwy.match_trim_to_generation([], "XD", log=lambda m: None)
    assert result["status"] == "no_generations_found"
    assert result["matched"] is None


# =========================
# Throttle detection (pure function, no transport mocking)
# =========================

class _FakeResponse:
    def __init__(self, status_code=200, content_type="application/json; charset=utf-8", json_ok=True):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self._json_ok = json_ok

    def json(self):
        if not self._json_ok:
            raise ValueError("not valid json")
        return {}


def test_is_throttled_response_non_200_is_throttled():
    assert jwy._is_throttled_response(_FakeResponse(status_code=429)) is True


def test_is_throttled_response_wrong_content_type_is_throttled():
    assert jwy._is_throttled_response(_FakeResponse(content_type="text/html")) is True


def test_is_throttled_response_invalid_json_is_throttled():
    assert jwy._is_throttled_response(_FakeResponse(json_ok=False)) is True


def test_is_throttled_response_valid_json_is_not_throttled():
    assert jwy._is_throttled_response(_FakeResponse()) is False


# =========================
# get_ja_years() orchestrator — internal functions monkeypatched, no HTTP
# =========================

def test_get_ja_years_throttled_resolution_returns_throttled_status(monkeypatch, tmp_path):
    monkeypatch.setattr(jwy, "CACHE_FILE", str(tmp_path / "ja_wikipedia_cache.json"))

    def _raise_throttled(make, model_name, log=print):
        raise jwy.ThrottledError("simulated throttle")

    monkeypatch.setattr(jwy, "resolve_ja_title", _raise_throttled)

    result = jwy.get_ja_years("TOYOTA", "LAND CRUISER", log=lambda m: None)
    assert result["status"] == "throttled"
    assert result["year_from"] is None and result["year_to"] is None
    assert not (tmp_path / "ja_wikipedia_cache.json").exists()  # never cached


def test_get_ja_years_title_not_resolved(monkeypatch, tmp_path):
    monkeypatch.setattr(jwy, "CACHE_FILE", str(tmp_path / "ja_wikipedia_cache.json"))
    monkeypatch.setattr(
        jwy, "resolve_ja_title",
        lambda make, model_name, log=print: {"title": None, "method": None, "match_score": None},
    )
    result = jwy.get_ja_years("HINO", "DUTRO", log=lambda m: None)
    assert result["status"] == "title_not_resolved"


def test_get_ja_years_matched_and_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(jwy, "CACHE_FILE", str(tmp_path / "ja_wikipedia_cache.json"))
    calls = {"resolve": 0, "fetch": 0}

    def _resolve(make, model_name, log=print):
        calls["resolve"] += 1
        return {"title": "マツダ・デミオ", "method": "langlink", "match_score": 100.0}

    def _fetch(title, log=print):
        calls["fetch"] += 1
        return "== 初代 DW系（1996年 - 2002年） ==\n本文"

    monkeypatch.setattr(jwy, "resolve_ja_title", _resolve)
    monkeypatch.setattr(jwy, "fetch_ja_wikitext", _fetch)

    result = jwy.get_ja_years("MAZDA", "DEMIO", log=lambda m: None)
    assert result["status"] == "matched"
    assert result["year_from"] == 1996 and result["year_to"] == 2002
    assert calls == {"resolve": 1, "fetch": 1}

    # Second call for the same pair should hit the cache, not call either function again.
    result2 = jwy.get_ja_years("MAZDA", "DEMIO", log=lambda m: None)
    assert result2["year_from"] == 1996 and result2["year_to"] == 2002
    assert calls == {"resolve": 1, "fetch": 1}
