"""
md_to_docx.py
-------------
Render TECHNICAL_DOCUMENTATION.md into the Word document the client reads.

WHY THIS EXISTS
---------------
The .docx was originally produced by a converter that is no longer in the repo,
and was then patched in place by one-off scripts (backend/update_docx.py being
the last of them). Patching a binary document by string-matching its paragraphs
does not survive real editing: a heading that gets reworded silently stops
matching, and the edit is skipped without an error.

The markdown file is the source of truth. This regenerates the whole document
from it, so the two can never drift, and emits real Word structures — Heading
1/2/3, native tables, List Number / List Bullet — rather than a wall of
formatted body text. The navigation pane works, tables can be sorted and
edited, and text reflows.

STYLING
-------
Deliberately reproduces the existing document's look rather than inventing a
new one, so a regenerated file drops into the same place as its predecessor:

    Normal        Calibri 10pt
    Heading 1     20pt   Heading 2  15pt   Heading 3  12pt
    inline code   Courier New 9pt
    code blocks   Courier New 8pt, one paragraph, newline-separated runs
    tables        Table Grid, bold header row
    margins       2.5cm left/right, 2cm top/bottom (Letter)

One thing it does NOT reproduce: the old converter emitted `**bold text with
`backticks`**` with the backticks left in, because it matched bold before
inline code and never re-scanned the result. Inline spans are tokenised here in
one pass, so code inside bold renders as monospace bold.

Usage (run from backend/)
-------------------------
    python scripts/md_to_docx.py --md ../TECHNICAL_DOCUMENTATION.md \
                                 --out ../TECHNICAL_DOCUMENTATION_updated.docx
"""

from __future__ import annotations

import argparse
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

BODY_FONT = "Calibri"
MONO_FONT = "Courier New"

BODY_PT = Pt(10)
CODE_INLINE_PT = Pt(9)
CODE_BLOCK_PT = Pt(8)
HEADING_PT = {1: Pt(20), 2: Pt(15), 3: Pt(12), 4: Pt(11)}

# Paragraph geometry, measured off the document this replaces so a regenerated
# file sits on the page exactly like its predecessor. These are set per
# paragraph rather than on the styles because that is how the original did it.
BODY_SPACE_AFTER = Pt(4)
BLOCK_SPACE = Pt(4)          # code blocks: before and after
BLOCK_INDENT = Cm(0.5)       # code blocks and list items: 14.15pt

# Inline spans, matched in one pass so nesting resolves correctly.
_INLINE_RE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<bold>\*\*[^*]+\*\*)"
    r"|(?P<italic>(?<!\*)\*(?!\*)[^*]+\*(?!\*))"
)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_ORDERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?[\s:-]*-[\s|:-]*\|?\s*$")


def add_inline(paragraph, text: str, *, bold: bool = False, italic: bool = False,
               mono_ok: bool = True):
    """Add `text` to `paragraph`, honouring markdown inline code/bold/italic.

    `mono_ok=False` strips code markers without switching font — headings in
    the source document are set in one face throughout, and a monospace run
    inside a heading reads as a mistake rather than as emphasis.
    """
    text = _LINK_RE.sub(r"\1", text)
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            _run(paragraph, text[pos:m.start()], bold=bold, italic=italic)
        if m.group("code"):
            _run(paragraph, m.group("code")[1:-1], bold=bold, italic=italic, mono=mono_ok)
        elif m.group("bold"):
            add_inline(paragraph, m.group("bold")[2:-2], bold=True, italic=italic,
                       mono_ok=mono_ok)
        else:
            add_inline(paragraph, m.group("italic")[1:-1], bold=bold, italic=True,
                       mono_ok=mono_ok)
        pos = m.end()
    if pos < len(text):
        _run(paragraph, text[pos:], bold=bold, italic=italic)


def _run(paragraph, text: str, *, bold=False, italic=False, mono=False):
    if not text:
        return
    run = paragraph.add_run(text)
    run.bold = bold or None
    run.italic = italic or None
    if mono:
        run.font.name = MONO_FONT
        run.font.size = CODE_INLINE_PT
    return run


def add_code_block(doc, lines: list[str]) -> None:
    """One paragraph holding the whole block, newline-separated runs.

    Kept as a single paragraph so Word treats the block as one unit when
    selecting or moving it, and so no paragraph spacing opens up between
    lines of what is meant to read as contiguous output.

    `keep_together` is what stops a diagram being split down the middle by a
    page break: Word keeps every line of a single paragraph on one page when
    it can. A block taller than the text area still has to break somewhere —
    check_blocks() in this file reports any that are at risk.
    """
    para = doc.add_paragraph()
    fmt = para.paragraph_format
    fmt.space_before = BLOCK_SPACE
    fmt.space_after = BLOCK_SPACE
    fmt.left_indent = BLOCK_INDENT
    fmt.keep_together = True
    for i, line in enumerate(lines):
        run = para.add_run(("\n" if i else "") + line)
        run.font.name = MONO_FONT
        run.font.size = CODE_BLOCK_PT


def _list_number_abstract_id(doc) -> str | None:
    """The abstract numbering definition the built-in List Number style uses."""
    pPr = doc.styles["List Number"].element.find(qn("w:pPr"))
    if pPr is None:
        return None
    num_pr = pPr.find(qn("w:numPr"))
    if num_pr is None:
        return None
    num_id = num_pr.find(qn("w:numId")).get(qn("w:val"))
    for num in doc.part.numbering_part.element.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            return num.find(qn("w:abstractNumId")).get(qn("w:val"))
    return None


def restart_numbering(doc, abstract_id: str) -> int:
    """Register a fresh numbering instance that starts again at 1.

    Every `List Number` paragraph in a document shares one counter by default,
    so the second numbered list carries on from where the first stopped — the
    steps under "Backend Architecture" came out numbered 15-19 because the
    table of contents above them had already used 1-14. Each list gets its own
    w:num pointing at the same abstract definition, with a startOverride.
    """
    numbering = doc.part.numbering_part.element
    used = [int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))]
    new_id = (max(used) if used else 0) + 1

    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(new_id))
    abstract = OxmlElement("w:abstractNumId")
    abstract.set(qn("w:val"), abstract_id)
    num.append(abstract)
    override = OxmlElement("w:lvlOverride")
    override.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:startOverride")
    start.set(qn("w:val"), "1")
    override.append(start)
    num.append(override)
    numbering.append(num)
    return new_id


def apply_numbering(paragraph, num_id: int) -> None:
    num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = 0
    num_pr.get_or_add_numId().val = num_id


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _repeat_header_row(row) -> None:
    """Mark a table row as a header so Word repeats it on every page."""
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def _no_row_split(row) -> None:
    """Stop a single row being broken across a page boundary."""
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def add_table(doc, rows: list[list[str]]) -> None:
    header, body = rows[0], rows[1:]
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for i, text in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.paragraphs[0].text = ""
        add_inline(cell.paragraphs[0], text, bold=True)
    _repeat_header_row(table.rows[0])
    _no_row_split(table.rows[0])
    for row in body:
        cells = table.add_row().cells
        _no_row_split(table.rows[-1])
        for i in range(len(header)):
            value = row[i] if i < len(row) else ""
            para = cells[i].paragraphs[0]
            para.text = ""
            add_inline(para, value)
    doc.add_paragraph()


def convert(md_path: str, out_path: str) -> Document:
    lines = open(md_path, encoding="utf-8").read().splitlines()

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = BODY_PT
    for section in doc.sections:
        section.left_margin = section.right_margin = Cm(2.5)
        section.top_margin = section.bottom_margin = Cm(2)

    try:
        list_abstract_id = _list_number_abstract_id(doc)
    except (KeyError, NotImplementedError, AttributeError):
        # No numbering part in the template — lists still render, they just
        # share one running counter, which is the pre-fix behaviour.
        list_abstract_id = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── fenced code block ───────────────────────────────────────────────
        if stripped.startswith("```"):
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            add_code_block(doc, block)
            continue

        # ── table ───────────────────────────────────────────────────────────
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and _TABLE_DIVIDER_RE.match(lines[i + 1])
        ):
            rows = [_split_row(stripped)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i].strip()))
                i += 1
            add_table(doc, rows)
            continue

        # ── heading ─────────────────────────────────────────────────────────
        heading = _HEADING_RE.match(stripped)
        if heading:
            level = min(len(heading.group(1)), 4)
            para = doc.add_heading("", level=level)
            add_inline(para, heading.group(2), mono_ok=False)
            for run in para.runs:
                run.font.size = HEADING_PT.get(level, Pt(11))
            # Never leave a heading stranded at the foot of a page.
            para.paragraph_format.keep_with_next = True
            i += 1
            continue

        # ── horizontal rule ─────────────────────────────────────────────────
        if stripped in ("---", "***", "___"):
            doc.add_paragraph()
            i += 1
            continue

        # ── blockquote ──────────────────────────────────────────────────────
        # Rendered as an indented body paragraph rather than Word's Intense
        # Quote, which introduces a colour and rule this document does not use
        # anywhere else.
        if stripped.startswith(">"):
            quoted = [stripped.lstrip("> ").strip()]
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                quoted.append(lines[i].strip().lstrip("> ").strip())
                i += 1
            para = doc.add_paragraph()
            fmt = para.paragraph_format
            fmt.left_indent = BLOCK_INDENT
            fmt.space_before = BLOCK_SPACE
            fmt.space_after = BLOCK_SPACE
            fmt.keep_together = True
            add_inline(para, " ".join(q for q in quoted if q))
            continue

        # ── lists ───────────────────────────────────────────────────────────
        ordered = _ORDERED_RE.match(stripped)
        bullet = _BULLET_RE.match(stripped)
        if ordered or bullet:
            style = "List Number" if ordered else "List Bullet"
            num_id = (
                restart_numbering(doc, list_abstract_id)
                if ordered and list_abstract_id is not None
                else None
            )
            while i < len(lines):
                current = lines[i].strip()
                m_o = _ORDERED_RE.match(current)
                m_b = _BULLET_RE.match(current)
                if m_o and style == "List Number":
                    text = m_o.group(2)
                elif m_b and style == "List Bullet":
                    text = m_b.group(1)
                else:
                    break
                para = doc.add_paragraph(style=style)
                para.paragraph_format.left_indent = BLOCK_INDENT
                if num_id is not None:
                    apply_numbering(para, num_id)
                add_inline(para, text)
                i += 1
            continue

        # ── blank ───────────────────────────────────────────────────────────
        if not stripped:
            i += 1
            continue

        # ── body paragraph (soft-wrapped lines join into one) ───────────────
        buf = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt.startswith(("#", "|", "```", ">", "---"))
                or _ORDERED_RE.match(nxt)
                or _BULLET_RE.match(nxt)
            ):
                break
            buf.append(nxt)
            i += 1
        para = doc.add_paragraph()
        para.paragraph_format.space_after = BODY_SPACE_AFTER
        add_inline(para, " ".join(buf))

    doc.core_properties.title = "Chloride Exide KE — Battery Finder: Technical Documentation"
    doc.save(os.path.abspath(out_path))
    return doc


def check_blocks(md_path: str) -> list[tuple[int, int, int]]:
    """Report fenced blocks that cannot fit on one page.

    `keep_together` only helps a paragraph that fits in the text area to begin
    with; a taller one is broken wherever it lands. Text height is the page
    less its margins. The 1.29 line factor is Word's actual line box for
    Courier New, calibrated against a 66-line block that split despite
    keepLines: 66 lines exactly overran the 678pt text area, putting the real
    figure at ~10.3pt for an 8pt font, not the ~9.6pt a naive 1.2 would give.
    The block's own before/after spacing is charged against the same budget.

    Returns (line_no, height_lines, limit) per offender.
    """
    text_height_pt = (11.0 - 2 * 2.0 / 2.54) * 72          # Letter, 2cm margins
    usable_pt = text_height_pt - 2 * BLOCK_SPACE.pt
    line_pt = CODE_BLOCK_PT.pt * 1.29
    limit = int(usable_pt / line_pt)

    offenders, in_block, start, count = [], False, 0, 0
    for n, line in enumerate(open(md_path, encoding="utf-8").read().splitlines(), 1):
        if line.strip().startswith("```"):
            if in_block:
                if count > limit:
                    offenders.append((start, count, limit))
                in_block = False
            else:
                in_block, start, count = True, n, 0
            continue
        if in_block:
            count += 1
    return offenders


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--md", required=True, help="source markdown file")
    p.add_argument("--out", required=True, help="destination .docx")
    args = p.parse_args()

    offenders = check_blocks(args.md)
    for line_no, height, limit in offenders:
        print(f"  WARNING — code block at line {line_no} is {height} lines; "
              f"only {limit} fit on a page, so it will be split.")

    doc = convert(args.md, args.out)
    out = os.path.abspath(args.out)
    print(f"  DONE — {out}  ({os.path.getsize(out) / 1024:.0f} KB)")
    print(f"  {len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables")
    if not offenders:
        print("  all fenced blocks fit on a single page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
