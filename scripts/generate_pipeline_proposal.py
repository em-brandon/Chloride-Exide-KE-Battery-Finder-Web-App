"""
generate_pipeline_proposal.py
------------------------------
Generates the Web Validation Pipeline Improvement Proposal as a Word document.

Usage:
    python scripts/generate_pipeline_proposal.py
"""

import os
import sys
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Pipeline_Improvement_Proposal.docx",
)

# Brand colours — Chloride Exide red + dark grey
RED   = RGBColor(0xC0, 0x00, 0x00)
GREY  = RGBColor(0x40, 0x40, 0x40)
BLACK = RGBColor(0x00, 0x00, 0x00)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_cell_bg(cell, hex_color: str):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def add_heading(doc, text, level=1, color=RED):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        run.font.color.rgb = color
        run.font.bold = True
    return p


def add_paragraph(doc, text, bold=False, indent=False):
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.left_indent = Inches(0.3)
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.bold = bold
    run.font.color.rgb = GREY
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.3 + level * 0.2)
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.color.rgb = GREY
    return p


def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT

    # Header row
    hdr = table.rows[0]
    for i, h in enumerate(headers):
        cell = hdr.cells[i]
        cell.text = h
        set_cell_bg(cell, "C00000")
        for run in cell.paragraphs[0].runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            run.font.size = Pt(10)

    # Data rows
    for r_idx, row in enumerate(rows):
        tr = table.rows[r_idx + 1]
        bg = "F2F2F2" if r_idx % 2 == 0 else "FFFFFF"
        for c_idx, cell_text in enumerate(row):
            cell = tr.cells[c_idx]
            cell.text = str(cell_text)
            set_cell_bg(cell, bg)
            for run in cell.paragraphs[0].runs:
                run.font.size = Pt(10)
                run.font.color.rgb = GREY

    # Column widths
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Inches(w)

    return table


# ---------------------------------------------------------------------------
# Document build
# ---------------------------------------------------------------------------

def build():
    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin    = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # ── Title block ─────────────────────────────────────────────────────────
    title = doc.add_heading("Web Validation Pipeline — Improvement Proposal", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.color.rgb = RED
        run.font.size = Pt(20)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("Chloride Exide Kenya — Battery Finder Platform   |   June 2026")
    r.font.size = Pt(11)
    r.font.color.rgb = GREY
    r.font.italic = True

    doc.add_paragraph()

    # ── 1. Executive Summary ────────────────────────────────────────────────
    add_heading(doc, "1. Executive Summary")
    add_paragraph(doc,
        "The web battery validation pipeline currently processes approximately 14,000 "
        "unique (make, model, 5-year) search buckets to build the battery recommendation "
        "data layer. Two bottlenecks limit throughput: (a) the primary search provider "
        "(DuckDuckGo) applies IP-level rate limiting, causing silent misses and extended "
        "pauses; and (b) the dataset contains a large number of European and American "
        "vehicle makes that have negligible real-world presence in the Kenyan market."
    )
    add_paragraph(doc,
        "This proposal recommends two complementary improvements: upgrading the search "
        "provider cascade to include SearXNG and Brave Search, and pruning the vehicle "
        "dataset of non-Kenyan makes. Together these changes are estimated to reduce "
        "active pipeline workload by 15–20% and virtually eliminate rate-limit pauses "
        "during local development runs."
    )

    # ── 2. Problem Statement ────────────────────────────────────────────────
    add_heading(doc, "2. Problem Statement")

    add_heading(doc, "2.1  Rate Limiting", level=2, color=GREY)
    add_paragraph(doc,
        "The pipeline's primary provider, DuckDuckGo (DDG), applies IP-level throttling "
        "that manifests as silent empty results rather than HTTP 429 errors. With three "
        "concurrent workers all making requests from the same IP address, the throttle "
        "is triggered earlier and more frequently. When hit, the pipeline pauses for "
        "30–90 seconds per occurrence. Over a full 14,000-bucket run this can add hours "
        "to total runtime."
    )

    add_heading(doc, "2.2  Dataset Size", level=2, color=GREY)
    add_paragraph(doc,
        "The vehicle_years table is populated from the CRSP global dataset, which "
        "includes makes rarely or never seen on Kenyan roads — Bentley, Ferrari, "
        "Brabus, Cadillac, Chrysler, and others. Of the current ~14,000 pipeline "
        "buckets, an estimated 1,500–2,500 correspond to makes with fewer than 25 "
        "confirmed Kenyan battery orders over three years of sales data. Processing "
        "these wastes quota, time, and money."
    )

    # ── 3. Market Analysis ──────────────────────────────────────────────────
    add_heading(doc, "3. Kenya Vehicle Market Analysis")

    add_heading(doc, "3.1  External Research", level=2, color=GREY)
    add_paragraph(doc,
        "The following data was gathered from Statista, Focus2move, AutoMag.co.ke, "
        "Zawya, and BestSellingCarsBlog (2023–2025):"
    )
    add_bullet(doc, "94.3% of Kenya's used car imports originate from Japan")
    add_bullet(doc, "Isuzu holds ~47.8% of the new vehicle market (D-Max is #1 seller)")
    add_bullet(doc, "Toyota accounts for 23–32% market share")
    add_bullet(doc, "Nissan is consistently top 3–5 nationally")
    add_bullet(doc, "Mitsubishi: ~6.7% | Ford: ~3.1% | Others: <3% combined")
    add_bullet(doc, "European luxury and American brands appear in no market share statistics")

    add_heading(doc, "3.2  Internal Ground Truth (Dial-A-Battery Orders)", level=2, color=GREY)
    add_paragraph(doc,
        "Cross-referencing 57,816 Kenyan battery orders from the Dial-A-Battery dataset "
        "(2023–2026) confirms the following market tiers:"
    )

    add_table(doc,
        ["Make", "Orders (3 yrs)", "Pipeline Decision"],
        [
            ("Toyota",      "~26,292",  "Core — keep"),
            ("Nissan",      "~7,030",   "Core — keep"),
            ("Subaru",      "~2,874",   "Core — keep"),
            ("Mitsubishi",  "~2,598",   "Core — keep"),
            ("Mazda",       "~2,595",   "Core — keep"),
            ("Isuzu",       "~1,999",   "Core — keep"),
            ("Volkswagen",  "~1,571",   "Core — keep"),
            ("Suzuki",      "~1,518",   "Core — keep"),
            ("Mercedes",    "~1,356",   "Keep"),
            ("Daihatsu",    "~905",     "Keep"),
            ("Land Rover",  "~559",     "Keep"),
            ("BMW",         "~467",     "Keep"),
            ("Audi",        "~177",     "Keep (2010+ only)"),
            ("Bentley",     "~2",       "REMOVE"),
            ("Ferrari",     "0",        "REMOVE"),
            ("Brabus",      "0",        "REMOVE"),
            ("Cadillac",    "~1",       "REMOVE"),
            ("Chrysler",    "~4",       "REMOVE"),
            ("Citroën",     "~1",       "REMOVE"),
            ("Skoda",       "~8",       "REMOVE"),
            ("Opel",        "~11",      "REMOVE"),
            ("Proton",      "~19",      "REMOVE"),
            ("FAW",         "~23",      "REMOVE"),
        ],
        col_widths=[1.8, 1.8, 2.2],
    )

    doc.add_paragraph()

    # ── 4. Proposed Solutions ───────────────────────────────────────────────
    add_heading(doc, "4. Proposed Solutions")

    add_heading(doc, "4.1  Upgraded Search Provider Cascade", level=2, color=GREY)
    add_paragraph(doc,
        "The current cascade (DuckDuckGo → Google CSE → Tavily) is replaced with a "
        "four-provider cascade. Google CSE has been removed as it is not available for "
        "this use case."
    )

    add_table(doc,
        ["Position", "Provider", "Type", "Quota", "Benefit"],
        [
            ("1st", "SearXNG",  "Self-hosted (localhost)", "Unlimited",      "No rate limits; aggregates DDG, Bing + 70 others"),
            ("2nd", "DuckDuckGo", "Scraper",             "Unlimited*",     "Free; handles bulk in production (* rate-limited)"),
            ("3rd", "Brave Search", "Paid API",          "2,000 free/mo",  "Independent index; catches DDG misses"),
            ("4th", "Tavily",   "Paid API",               "1,000 free/mo",  "AI-powered; last-resort fallback"),
        ],
        col_widths=[0.7, 1.4, 1.6, 1.5, 2.6],
    )
    doc.add_paragraph()
    add_paragraph(doc,
        "SearXNG runs as a Docker container on the local development machine "
        "(docker run -d -p 8888:8080 searxng/searxng). It is activated by setting "
        "SEARXNG_URL=http://localhost:8888 in the .env file and is automatically "
        "skipped when the variable is absent, making it transparent in production."
    )

    add_heading(doc, "4.2  Dataset Cleanup — Non-Kenya Makes", level=2, color=GREY)
    add_paragraph(doc,
        "A standalone script (scripts/cleanup_non_kenya_makes.py) removes the "
        "following makes from vehicle_years and web_battery_validation:"
    )

    add_heading(doc, "Definite Removes (0–4 orders in 3 years)", level=3, color=GREY)
    for make in ["Bentley", "Ferrari", "Brabus", "Cadillac", "Chrysler",
                 "Citroën", "Geely", "Iveco Daily", "Alfa Romeo"]:
        add_bullet(doc, make, level=1)

    add_heading(doc, "Strong Removes (5–25 orders — negligible presence)", level=3, color=GREY)
    for make in ["Foton", "Skoda", "Opel", "Proton", "FAW"]:
        add_bullet(doc, make, level=1)

    add_heading(doc, "Partial Remove", level=3, color=GREY)
    add_bullet(doc, "Audi — retain 2010 and later only (removes pre-2010 entries)", level=1)

    add_paragraph(doc,
        "The script runs as a dry-run by default (shows row counts without changing "
        "anything) and requires --execute to apply. All deletes execute in a single "
        "database transaction and roll back automatically on any error."
    )

    # ── 5. Cost Analysis ────────────────────────────────────────────────────
    add_heading(doc, "5. API Cost Analysis")

    add_heading(doc, "5.1  Dataset After Cleanup", level=2, color=GREY)
    add_table(doc,
        ["Metric", "Before", "After Cleanup"],
        [
            ("Total Phase 1 buckets",       "~14,000",  "~12,000–12,500"),
            ("Already cached",              "~1,834",   "~1,834"),
            ("Buckets to fetch (first run)", "~12,166",  "~10,166–10,666"),
        ],
        col_widths=[3.0, 1.8, 2.0],
    )
    doc.add_paragraph()

    add_heading(doc, "5.2  Estimated Cost for One Full Pipeline Run", level=2, color=GREY)
    add_paragraph(doc,
        "Assumes DDG handles ~60% of uncached buckets before throttling kicks in. "
        "Remaining ~40% (~4,000 buckets) covered by paid providers."
    )

    add_table(doc,
        ["Provider", "Buckets handled", "Free tier covers?", "Estimated cost"],
        [
            ("DuckDuckGo",   "~6,100 (60%)",  "Yes — unlimited",        "$0"),
            ("SearXNG",      "Handles all (localhost dev)", "Yes — self-hosted", "$0"),
            ("Brave Search", "~2,000",         "Yes — 2,000/mo free",    "$0"),
            ("Brave Search", "~1,000 overflow","No — paid tier",         "~$3"),
            ("Tavily",       "~1,000",         "Yes — 1,000/mo free",    "$0"),
            ("Total",        "~10,100",        "",                       "~$3"),
        ],
        col_widths=[1.6, 2.0, 1.8, 1.4],
    )
    doc.add_paragraph()

    add_heading(doc, "5.3  Monthly Subscription Comparison", level=2, color=GREY)
    add_table(doc,
        ["Provider", "Free", "Starter plan", "Standard plan"],
        [
            ("Brave Search", "2,000 queries/mo",  "$5/mo — 20,000 queries",  "$40/mo — 200,000 queries"),
            ("Tavily",       "1,000 queries/mo",  "$9/mo — 10,000 queries",  "$29/mo — 100,000 queries"),
            ("SearXNG",      "Unlimited (self-hosted)", "N/A",               "N/A"),
        ],
        col_widths=[1.6, 2.0, 2.2, 2.4],
    )
    doc.add_paragraph()
    add_paragraph(doc,
        "For full guaranteed coverage of ~10,000 uncached buckets per month without "
        "depending on DDG at all: Brave Standard ($40/mo) + Tavily Starter ($9/mo) = "
        "$49/month. In practice, DDG and SearXNG (localhost) will handle the majority, "
        "making the effective monthly cost $0–$14 for most runs."
    )

    # ── 6. Expected Outcomes ────────────────────────────────────────────────
    add_heading(doc, "6. Expected Outcomes")

    add_table(doc,
        ["Improvement", "Current state", "After changes"],
        [
            ("Phase 1 bucket count",    "~14,000",           "~12,000–12,500"),
            ("Rate limit pauses (dev)", "Frequent (30–90s)", "None (SearXNG primary)"),
            ("Rate limit pauses (prod)","Frequent",          "Rare (Brave fallback)"),
            ("Monthly API cost",        "$0 (limited coverage)", "$0–$14 typical"),
            ("Full coverage cost",      "N/A (incomplete)",  "~$3/run or $49/mo flat"),
            ("Data accuracy",           "Kenya + global",    "Kenya-relevant only"),
        ],
        col_widths=[2.4, 2.0, 2.4],
    )
    doc.add_paragraph()

    # ── 7. Recommendations ──────────────────────────────────────────────────
    add_heading(doc, "7. Recommendations")

    add_paragraph(doc, "Immediate actions (already implemented):", bold=True)
    add_bullet(doc, "Search cascade updated: SearXNG → DDG → Brave → Tavily (Google CSE removed)")
    add_bullet(doc, "Cleanup script created at scripts/cleanup_non_kenya_makes.py")

    add_paragraph(doc, "Next steps:", bold=True)
    add_bullet(doc, "Install Docker Desktop and run: docker run -d -p 8888:8080 searxng/searxng")
    add_bullet(doc, "Register for a free Brave Search API key at api.search.brave.com")
    add_bullet(doc, "Add SEARXNG_URL and BRAVE_SEARCH_API_KEY to .env")
    add_bullet(doc, "Run cleanup script in dry-run mode to confirm row counts")
    add_bullet(doc, "Run cleanup script with --execute after confirming counts")
    add_bullet(doc, "Re-run the pipeline — first run processes ~10,000 buckets; subsequent runs use cache")

    # ── Footer ───────────────────────────────────────────────────────────────
    doc.add_paragraph()
    footer_p = doc.add_paragraph()
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = footer_p.add_run("Chloride Exide Kenya — Battery Finder Platform   |   Prepared June 2026")
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    r.font.italic = True

    doc.save(OUTPUT_PATH)
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
