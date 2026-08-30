"""
export_fitment_workbook.py
--------------------------
Build the Excel workbook handed to the business: our battery recommendations on
one sheet, the manufacturer's own fitment guide on another.

SHEETS
------
  Web Validated Fitments   web_battery_validation — one row per make/model/year,
                           with the battery we recommend and where its capacity
                           came from.
  OEM Fitment Guide        oem_fitment — the raw Exide reference data, unaltered.
                           It is the evidence behind the "Capacity source" column
                           on the first sheet, so shipping both lets a reader
                           check any single row themselves.
  Summary                  Counts per make, so the workbook opens on something
                           readable rather than 20,000 rows.

NAMING
------
"Web Validated Fitments" and "OEM Fitment Guide" are the names the business
already uses for these two datasets — they are the headings on the guide the
client reviewed previously. Renaming them to something more descriptive was
tried and reverted: a reader who knows the old names has to work out that the
new ones mean the same thing, which is the opposite of helpful. Plain language
belongs in the explanations, not in relabelling things people can already name.

The "Capacity source" column is computed with the same make/model/year prefix
match the correction scripts use (apply_oem_to_staging.oem_head), so the
workbook cannot claim a row is OEM-backed on a looser test than the one that
actually set its value.

Column headers otherwise avoid database names: a reader should not need to know
what `ah` or `model_n` means.

Usage (run from backend/)
-------------------------
    python scripts/export_fitment_workbook.py
    python scripts/export_fitment_workbook.py --out ../Battery-Fitment-Data.xlsx
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from db import engine
from scripts.apply_oem_to_staging import (MAKE_ALIASES, _compact, oem_head,
                                         oem_prefixes)

HEAD_FILL = PatternFill("solid", fgColor="0E6B70")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=13)
NOTE_FONT = Font(italic=True, size=9, color="606060")
THIN = Side(style="thin", color="D0D8D6")


def style_sheet(ws, ncols: int, widths: list[int], header_row: int = 1) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=header_row, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = widths[c - 1]
    ws.row_dimensions[header_row].height = 28
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = (f"A{header_row}:"
                          f"{get_column_letter(ncols)}{ws.max_row}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=os.path.join(ROOT, "..",
                                                 "Battery-Fitment-Data.xlsx"))
    args = p.parse_args()

    print("reading tables...")
    with engine.connect() as conn:
        w = pd.read_sql(
            "SELECT make_n, model_n, year, engine_cc, fuel_type, battery_code,"
            " ah, technology FROM web_battery_validation"
            " ORDER BY make_n, model_n, year", conn)
        oem = pd.read_sql(
            "SELECT make, model, vehicle_category, year_from, year_to, ah,"
            " technology, dimensions, cylinder_capacity_cc FROM oem_fitment"
            " ORDER BY make, model, year_from", conn)

    # Same matcher the correction scripts used, so "confirmed" means the same
    # thing in the workbook as it did when the value was set.
    idx: dict[str, list] = defaultdict(list)
    for r in oem.itertuples():
        mk = str(r.make).upper().strip()
        idx[mk].append((_compact(oem_head(r.model, mk)), r.year_from, r.year_to))

    def confirmed(mk: str, model: str, year: int) -> bool:
        cands = idx.get(MAKE_ALIASES.get(mk, mk)) or idx.get(mk) or []
        for key, exact_only in oem_prefixes(mk, model):
            for ch, yf, yt in cands:
                matched = (ch == key) if exact_only else ch.startswith(key)
                if (matched and (pd.isna(yf) or yf <= year)
                        and (pd.isna(yt) or year <= yt)):
                    return True
        return False

    print(f"  recommendations {len(w):,} | manufacturer guide {len(oem):,}")
    w["src"] = ["OEM Fitment" if confirmed(str(r.make_n).upper(),
                                                 str(r.model_n), int(r.year))
                else "Web Validated" for r in w.itertuples()]

    # Whole numbers as nullable integers, not floats. A plain float column
    # renders every capacity as "45.0" in Excel, and a column holding NaN is
    # promoted to float automatically, so this has to be explicit.
    def whole(series):
        return pd.to_numeric(series, errors="coerce").astype("Int64")

    rec = pd.DataFrame({
        "Make": w.make_n.str.upper(),
        "Model": w.model_n,
        "Year": w.year,
        "Engine size (cc)": whole(w.engine_cc),
        "Fuel": w.fuel_type,
        "Recommended battery": w.battery_code,
        "Capacity (Ah)": whole(w.ah),
        "Battery type": w.technology,
        "Capacity source": w.src,
    })

    # The guide covers 76 makes and reaches back to 1900 — most of it is for
    # marques we do not sell (MAN, Citroen, Opel, Skoda) or years we do not
    # trade in. Rather than delete those rows, which would break the "check any
    # recommendation against its source" purpose, flag them so the sheet can be
    # filtered to the 43,332 entries that actually apply to us.
    serve = set(w.make_n.str.upper().str.strip()) | {
        MAKE_ALIASES.get(m, m) for m in w.make_n.str.upper().str.strip()}
    relevant = [("Yes" if (str(mk).upper().strip() in serve
                           and (pd.isna(yt) or yt >= 2000) and yf <= 2026)
                 else "No")
                for mk, yf, yt in zip(oem.make, oem.year_from, oem.year_to)]

    guide = pd.DataFrame({
        "Make": oem.make.str.upper(),
        "Model": oem.model,
        "Vehicle type": oem.vehicle_category,
        "Fits from": whole(oem.year_from),
        # Left EMPTY where the entry is open-ended, not filled with a word.
        # Writing "still current" into 13,089 of these mixed text into a number
        # column, which makes Excel treat the whole column as text — sorting by
        # year and filtering "after 2015" both stop working. A blank sorts and
        # filters correctly, and the sheet note explains what it means.
        "Fits until": whole(oem.year_to),
        "Capacity (Ah)": whole(oem.ah),
        "Battery type": oem.technology,
        "Dimensions": oem.dimensions,
        "Engine size (cc)": whole(oem.cylinder_capacity_cc),
        "Applies to our makes/years": relevant,
    })

    # Make / Vehicles / Models only. The per-make year range and OEM share were
    # dropped deliberately: every make starts at 2000 because that is the floor
    # for the whole dataset, so an "Earliest year" column repeated 2000 down all
    # 33 rows and read as data when it was really one fact about the workbook —
    # now stated once in the notes above the table. The OEM share belongs with
    # the fitments themselves, where the "Capacity source" column gives it per
    # vehicle rather than as an average that hides which vehicles are which.
    summary = (rec.groupby("Make")
               .agg(**{"Vehicles covered": ("Year", "size"),
                       "Models": ("Model", "nunique")})
               .reset_index()
               .sort_values("Vehicles covered", ascending=False))

    n_oem = int((rec["Capacity source"] == "OEM Fitment").sum())
    n_web = len(rec) - n_oem
    n_rel = int(sum(1 for x in relevant if x == "Yes"))

    # The Summary opens the workbook, so it has to explain the other two sheets
    # before showing any numbers. Each line is a separate cell rather than one
    # wrapped paragraph so Excel does not need row-height juggling to show it.
    intro = [
        ("What this workbook contains", TITLE_FONT),
        ("", None),
        (f"Sheet 2  —  Web Validated Fitments: {len(rec):,} lines, one for each "
         f"make, model and year we can advise on. Each line names the battery to "
         f"fit.", None),
        (f"Sheet 3  —  OEM Fitment Guide: Exide's official global fitment guide, "
         f"{len(guide):,} entries, reproduced unaltered. It is the evidence behind "
         f"sheet 2.", None),
        ("", None),
        ("Where each battery size comes from", TITLE_FONT),
        ("", None),
        (f"OEM Fitment  —  {n_oem:,} lines ({n_oem / len(rec) * 100:.0f}%). The "
         f"battery size is taken from Exide's own global fitment guide. Exide is an "
         f"original-equipment battery manufacturer, so this is our strongest "
         f"evidence.", None),
        (f"Web Validated  —  {n_web:,} lines ({n_web / len(rec) * 100:.0f}%). "
         f"Exide's guide does not cover the vehicle, so the size was researched "
         f"online and then checked against our own sizing rules before being "
         f"accepted.", None),
        ("The 'Capacity source' column on sheet 2 shows which of the two applies to "
         "any given vehicle.", None),
        ("", None),
        ("Points to note", TITLE_FONT),
        ("", None),
        ("Every make below starts at the year 2000. Older vehicles are excluded "
         "from the whole workbook, so no make has data before then.", None),
        (f"Only {n_rel:,} of the {len(guide):,} entries on sheet 3 apply to the makes "
         f"and years we trade in — the rest cover marques we do not sell, or "
         f"pre-2000 vehicles. Filter its last column to 'Yes' for the relevant "
         f"part.", None),
        ("A make with few OEM Fitment lines is usually not a gap in our work: it "
         "means Exide's guide holds little or nothing for that make. Maruti Suzuki "
         "does not appear in it at all.", None),
        ("", None),
    ]

    out = os.path.abspath(args.out)
    print(f"writing {out} ...")
    header_row = len(intro) + 1
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        summary.to_excel(xl, sheet_name="Summary", index=False,
                         startrow=header_row - 1)
        rec.to_excel(xl, sheet_name="Web Validated Fitments", index=False,
                     startrow=2)
        guide.to_excel(xl, sheet_name="OEM Fitment Guide", index=False,
                       startrow=2)

        ws = xl.sheets["Summary"]
        for i, (line, font) in enumerate(intro, start=1):
            cell = ws.cell(row=i, column=1, value=line or None)
            if font is not None:
                cell.font = font
            elif line:
                cell.font = NOTE_FONT
        style_sheet(ws, 3, [26, 18, 12], header_row=header_row)

        ws = xl.sheets["Web Validated Fitments"]
        ws["A1"] = "Web Validated Fitments"
        ws["A1"].font = TITLE_FONT
        ws["A2"] = (f"{len(rec):,} vehicles, {rec.Make.nunique()} makes, "
                    f"{int(rec.Year.min())}-{int(rec.Year.max())}. "
                    "Capacity comes from the OEM Fitment Guide where it covers "
                    "the vehicle, otherwise it is web validated and checked "
                    "against our own sizing rules.")
        ws["A2"].font = NOTE_FONT
        style_sheet(ws, 9, [15, 40, 8, 15, 14, 30, 13, 12, 17], header_row=3)

        ws = xl.sheets["OEM Fitment Guide"]
        ws["A1"] = "OEM Fitment Guide — Exide's official global fitment guide"
        ws["A1"].font = TITLE_FONT
        ws["A2"] = (f"{len(guide):,} entries, {guide.Make.nunique()} makes. "
                    "Exide is an original-equipment battery manufacturer; this "
                    "is its own published global guide, included "
                    "so any fitment on the previous sheet can be checked "
                    "against its source. An empty 'Fits until' means the entry "
                    "is open-ended. Filter the last column to 'Yes' for "
                    "the 43,332 entries covering the makes and years we trade "
                    "in; the rest are marques we do not sell or pre-2000.")
        ws["A2"].font = NOTE_FONT
        style_sheet(ws, 10, [16, 44, 12, 10, 12, 12, 12, 15, 14, 22], header_row=3)

    size = os.path.getsize(out) / 1e6
    print(f"  DONE — {out}  ({size:.1f} MB)")
    print(f"  Summary {len(summary)} rows | Web Validated Fitments {len(rec):,}"
          f" | OEM Fitment Guide {len(guide):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
