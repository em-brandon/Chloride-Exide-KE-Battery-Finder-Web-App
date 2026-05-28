import sys, copy
sys.stdout.reconfigure(encoding='utf-8')
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc_path = r'c:\Users\Brandon Mwavua\Documents\Battery Finder Project\CSRP data set 2025\TECHNICAL_DOCUMENTATION.docx'
doc = Document(doc_path)

def find_para(text_fragment):
    for p in doc.paragraphs:
        if text_fragment in p.text:
            return p
    return None

def append_to_para(para, extra):
    if para.runs:
        para.runs[-1].text += extra
    else:
        para.add_run(extra)

def replace_para_text(para, new_text):
    for run in para.runs:
        run.text = ''
    if para.runs:
        para.runs[0].text = new_text
    else:
        para.add_run(new_text)

def insert_para_after(ref_para, text, copy_style_from=None):
    """Insert a Normal paragraph with text immediately after ref_para."""
    new_p = OxmlElement('w:p')
    if copy_style_from is not None:
        existing_pPr = copy_style_from._element.find(qn('w:pPr'))
        if existing_pPr is not None:
            new_p.append(copy.deepcopy(existing_pPr))
    new_r = OxmlElement('w:r')
    new_t = OxmlElement('w:t')
    new_t.text = text
    new_t.set(qn('xml:space'), 'preserve')
    new_r.append(new_t)
    new_p.append(new_r)
    ref_para._element.addnext(new_p)

# 1. Layer 0 return confidence — append AccuracyBar note
p = find_para('Return confidence: 80 (fuzzy model match)')
if p:
    append_to_para(p, ' The frontend AccuracyBar awards full scores for both Car Found and Data Quality segments when this layer fires.')
    print('✓ Layer 0 return confidence updated')

# 2. Layer 1 Step 3a — insert AccuracyBar bullet after "resolved_cc and resolved_fuel" bullet
p = find_para('resolved_cc and resolved_fuel taken from this row')
if p:
    insert_para_after(p, 'AccuracyBar: Car Found fills to 50/50; Year fills to 25/25 (zero delta).', copy_style_from=p)
    print('✓ Layer 1 AccuracyBar bullet inserted')

# 3. Layer 2 example — insert AccuracyBar note after the example sentence
p = find_para('Example: model score 85, year delta 2')
if p:
    insert_para_after(p, 'AccuracyBar Year segment: delta 0 → 25 pts, delta 1 → 20, delta 2 → 13, delta 3 → 8. Car Found segment fills proportionally to the model_score (20–40 out of 50 pts in close-match range).')
    print('✓ Layer 2 AccuracyBar note inserted')

# 4. Layer 3 opening — append AccuracyBar note
p = find_para('Reached if all matching layers failed (confidence remains 40)')
if p:
    append_to_para(p, ' AccuracyBar: Car Found = 0, Data Quality = 4 (minimum), Engine Info proportional to whether the CC was non-default. An amber warning banner is shown above the result card when this layer fires (matched_make is null in the response).')
    print('✓ Layer 3 AccuracyBar note appended')

# 5. ResultPanel bullet — replace with AccuracyBar description
p = find_para('ResultPanel — displays primary battery')
if p:
    replace_para_text(p,
        'ResultPanel — displays primary battery (Ah, CCA, technology, battery code), '
        'segmented Result Accuracy bar (AccuracyBar.tsx), same-technology alternatives grid, '
        'an amber fallback warning when no model was matched (matched_make is null), '
        'and “Rate this result” feedback trigger.')
    print('✓ ResultPanel bullet updated')

# 6. Insert AccuracyBar.tsx paragraph after the ResultPanel bullet, before ResultCard
p_resultpanel = find_para('ResultPanel — displays primary battery')
if p_resultpanel:
    insert_para_after(p_resultpanel,
        '`AccuracyBar.tsx` (frontend/src/components/) — Four-segment colour-coded accuracy bar rendered below every recommendation. '
        'Segment widths are proportional to their maximum contribution (Car Found 50 pts, Year 25 pts, Data Quality 15 pts, Engine Info 10 pts). '
        'Each segment fills with an animated colour (green / blue / purple / amber) based on match quality computed from match_type, confidence, '
        'matched_year, and matched_make. Total score (0–100) is shown as a percentage alongside the bar. '
        'Uses inline styles for compatibility with both Tailwind and legacy CSS contexts.')
    print('✓ AccuracyBar.tsx paragraph inserted')

# 7. ResultCard.tsx — update description
p = find_para('ResultCard.tsx')
if p:
    replace_para_text(p,
        '`ResultCard.tsx` (frontend/src/components/) — An alternate result display used in other parts of the app. '
        'Renders the same data with Tailwind classes, includes AccuracyBar, the amber fallback warning, '
        'and supports the Exide Maxx logo badge for Powerlast/Spark battery codes.')
    print('✓ ResultCard.tsx description updated')

out_path = doc_path.replace('.docx', '_updated.docx')
doc.save(out_path)
print(f'\nSaved to: {out_path}')
print('Close TECHNICAL_DOCUMENTATION.docx in Word, then rename _updated to replace it.')
