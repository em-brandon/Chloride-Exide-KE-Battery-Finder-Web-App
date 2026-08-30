"""
report_to_docx.py
-----------------
Build an editable Word version of the fitment audit report.

WHY NOT CONVERT THE PDF
-----------------------
A PDF-to-Word conversion produces a page of floating text boxes positioned to
imitate the original layout. It looks right and is miserable to edit: paragraphs
do not reflow, headings are not headings, and tables are pictures of tables.

This reads the same HTML the PDF is printed from and emits real Word structures
— Heading 1/2/3, body paragraphs, and native tables — so the document behaves
the way a Word document should: text reflows, the navigation pane works, and
tables can be sorted and edited.

CHARTS
------
The report's charts are CSS bars, which have no Word equivalent. Rather than
paste them as flat images into a document whose whole purpose is editing, their
underlying figures are emitted as ordinary Word tables. The numbers are the
content; the bars were only ever a way of reading them quickly, and a reader who
wants the visual has the PDF.

Usage (run from backend/)
-------------------------
    python scripts/report_to_docx.py --html <path to fitment_audit.html>
                                     --out ../Battery-Fitment-Audit.docx
"""

from __future__ import annotations

import argparse
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from bs4 import BeautifulSoup
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

ACCENT = RGBColor(0x0E, 0x6B, 0x70)
MUTED = RGBColor(0x68, 0x78, 0x74)


def _txt(el) -> str:
    """Collapsed visible text, with the HTML entities already decoded by bs4."""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def add_kv_table(doc, pairs, headers):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
    for row in pairs:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
            if i:
                cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph()
    return t


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--html", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    soup = BeautifulSoup(open(args.html, encoding="utf-8").read(), "lxml")
    doc = Document()
    doc.core_properties.title = "Battery Fitment Audit"

    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)

    # ---- masthead ----------------------------------------------------------
    eyebrow = soup.select_one(".eyebrow")
    if eyebrow:
        r = doc.add_paragraph().add_run(_txt(eyebrow).upper())
        r.font.size = Pt(8.5)
        r.font.color.rgb = ACCENT
        r.bold = True
    doc.add_heading(_txt(soup.select_one("h1")), level=0)
    stand = soup.select_one(".standfirst")
    if stand:
        r = doc.add_paragraph().add_run(_txt(stand))
        r.italic = True
        r.font.color.rgb = MUTED

    def emit_headline(block):
        rows = [(_txt(c.select_one(".k")), _txt(c.select_one(".v")),
                 _txt(c.select_one(".sub")) if c.select_one(".sub") else "")
                for c in block.select(".hcell")]
        t = doc.add_table(rows=0, cols=3)
        t.style = "Light List Accent 1"
        for k, v, sub in rows:
            cells = t.add_row().cells
            cells[0].paragraphs[0].add_run(k).bold = True
            cells[1].paragraphs[0].add_run(v).bold = True
            cells[2].text = sub
        doc.add_paragraph()

    first_headline = soup.select_one("header .headline")
    if first_headline:
        emit_headline(first_headline)

    # ---- sections ----------------------------------------------------------
    for sec in soup.select("div.wrap > section"):
        h2 = sec.find("h2")
        if h2:
            doc.add_heading(_txt(h2), level=1)

        for el in sec.children:
            if getattr(el, "name", None) is None:
                continue
            name = el.name
            cls = el.get("class") or []

            if name == "h2":
                continue
            if name == "h3":
                doc.add_heading(_txt(el), level=2)
            elif name == "p":
                para = doc.add_paragraph(_txt(el))
                if "note" in cls:
                    for r in para.runs:
                        r.font.size = Pt(9.5)
                        r.font.color.rgb = MUTED
            elif name == "div" and "headline" in cls:
                emit_headline(el)
            elif name == "div" and "checks" in cls:
                rows = []
                for c in el.select(".check"):
                    detail = c.select_one(".detail")
                    rows.append((_txt(c.select_one(".what")),
                                 _txt(c.select_one(".chip")),
                                 _txt(detail) if detail else ""))
                add_kv_table(doc, rows, ["Check", "Result", "Detail"])
            elif name == "div" and "ledger" in cls:
                rows = [(_txt(r.select_one(".cnt")),
                         _txt(r.select_one("b")),
                         _txt(r.select_one("span")))
                        for r in el.select(".lrow")]
                add_kv_table(doc, [(b, c, a) for a, b, c in rows],
                             ["Item", "Detail", "Count"])
            elif name == "div" and "open" in cls:
                for item in el.select(".item"):
                    doc.add_heading(_txt(item.find("h3")), level=2)
                    doc.add_paragraph(_txt(item.find("p")))
            elif name == "div" and "split" in cls:
                add_kv_table(doc, [(_txt(d),) for d in el.find_all("div")],
                             ["Split"])
            elif name == "div" and "glossary" in cls:
                for dt, dd in zip(el.select("dt"), el.select("dd")):
                    para = doc.add_paragraph()
                    para.add_run(_txt(dt) + " — ").bold = True
                    para.add_run(_txt(dd))
            elif name == "figure":
                # Charts become tables; see module docstring.
                keys = el.select(".keys span")
                if keys:
                    add_kv_table(doc, [(_txt(k),) for k in keys], ["Battery type"])
                bars = el.select(".bars")
                if bars:
                    cells = list(bars[0].children)
                    labels = [_txt(x) for x in bars[0].select(".lb")]
                    values = [_txt(x) for x in bars[0].select(".vl")]
                    add_kv_table(doc, list(zip(labels, values)),
                                 ["Reason", "Vehicles"])
                cap = el.find("figcaption")
                if cap:
                    para = doc.add_paragraph(_txt(cap))
                    for r in para.runs:
                        r.font.size = Pt(9.5)
                        r.font.color.rgb = MUTED
            elif name == "div" and "scroll" in cls:
                tbl = el.find("table")
                if not tbl:
                    continue
                heads = [_txt(th) for th in tbl.select("thead th")]
                body = []
                for tr in tbl.select("tbody tr"):
                    body.append([_txt(td) for td in tr.find_all("td")])
                add_kv_table(doc, body, heads)

    # ---- footer ------------------------------------------------------------
    foot = soup.select_one("footer")
    if foot:
        doc.add_paragraph()
        para = doc.add_paragraph(" · ".join(_txt(s) for s in foot.find_all("span")))
        for r in para.runs:
            r.font.size = Pt(9)
            r.font.color.rgb = MUTED

    out = os.path.abspath(args.out)
    doc.save(out)
    print(f"  DONE — {out}  ({os.path.getsize(out) / 1024:.0f} KB)")
    print(f"  {len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
