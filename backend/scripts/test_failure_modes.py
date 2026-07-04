"""
50-case failure-mode study for the matcher engine.
Generates `accuracy_analysis_failure_modes.xlsx` in the repository root.

Usage:
  python scripts/test_failure_modes.py

This script samples real rows from `vehicle_years.csv` and constructs
mixed 'select' (exact) and 'type' (noisy/misspelled/partial) cases.
"""
from __future__ import annotations

import random
import os
import sys
from typing import Optional
import pandas as pd

# Ensure repository root is on sys.path so we can import local modules
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# Import the engine under test
from matcher import recommend, _vehicles, _model_aliases
OUT_XLSX = os.path.join(ROOT, "accuracy_analysis_failure_modes.xlsx")

random.seed(42)

VEH = _vehicles()
# Keep only rows with non-empty make/model/year
VEH = VEH.dropna(subset=["make", "model", "year"]).copy()
VEH = VEH.astype({"year": "int64"})

unique_rows = VEH[ ["make", "model", "year", "engine_capacity", "fuel"] ].drop_duplicates()

N = 50

cases = []

# Helpers to make noisy variants of model/make strings
def typo_insert(s: str) -> str:
    if not s: return s
    i = random.randrange(0, len(s))
    return s[:i] + random.choice('abcdefghijklmnopqrstuvwxyz') + s[i:]

def typo_swap(s: str) -> str:
    if len(s) < 2: return s
    i = random.randrange(0, len(s)-1)
    lst = list(s)
    lst[i], lst[i+1] = lst[i+1], lst[i]
    return ''.join(lst)

def truncate(s: str) -> str:
    if len(s) <= 4: return s
    cut = random.randint(3, max(3, len(s)-2))
    return s[:cut]

def remove_vowels(s: str) -> str:
    return ''.join([c for c in s if c.lower() not in 'aeiou'])

# Generate 25 select (exact) cases sampled from dataset
sampled = unique_rows.sample(n=25, random_state=42).to_dict(orient='records')
for r in sampled:
    cases.append({
        "case_id": f"S-{len(cases)+1}",
        "mode": "select",
        "input_make": r['make'],
        "input_model": r['model'],
        "input_year": int(r['year']),
        "engine_cc": int(r['engine_capacity']) if pd.notna(r['engine_capacity']) else None,
        "fuel_type": r['fuel'] if pd.notna(r['fuel']) else None,
        "expected_make": r['make'],
        "expected_model": r['model'],
        "expected_year": int(r['year']),
        "note": "exact sample",
    })

# For 25 type-mode cases, take rows and mutate model/make/year in various ways
sampled2 = unique_rows.sample(n=30, random_state=7).to_dict(orient='records')
mutators = [typo_insert, typo_swap, truncate, remove_vowels, lambda s: s.replace(' ', ''), lambda s: s.upper()]
for i, r in enumerate(sampled2[:25]):
    mut = random.choice(mutators)
    input_model = mut(r['model'])
    # Occasionally introduce a make typo
    if random.random() < 0.2:
        input_make = typo_swap(r['make'])
    else:
        input_make = r['make']

    # Occasionally perturb year slightly to create off-by-one/three errors
    year = int(r['year'])
    if random.random() < 0.3:
        year += random.choice([-4, -2, -1, 1, 2, 3])

    # Sometimes omit engine_cc / fuel_type to simulate type mode minimal input
    engine_cc = None if random.random() < 0.4 else (int(r['engine_capacity']) if pd.notna(r['engine_capacity']) else None)
    fuel_type = None if random.random() < 0.5 else (r['fuel'] if pd.notna(r['fuel']) else None)

    cases.append({
        "case_id": f"T-{len(cases)+1}",
        "mode": "type",
        "input_make": input_make,
        "input_model": input_model,
        "input_year": int(year),
        "engine_cc": engine_cc,
        "fuel_type": fuel_type,
        "expected_make": r['make'],
        "expected_model": r['model'],
        "expected_year": int(r['year']),
        "note": "noisy / typed",
    })

# Trim to exactly N cases
cases = cases[:N]

results = []
for c in cases:
    out = recommend(
        c['input_make'], c['input_model'], c['input_year'],
        engine_cc=c['engine_cc'], fuel_type=c['fuel_type'], enable_aliases=True
    )
    primary = out.get('primary') or {}
    results.append({
        'case_id': c['case_id'],
        'mode': c['mode'],
        'input_make': c['input_make'],
        'input_model': c['input_model'],
        'input_year': c['input_year'],
        'engine_cc': c['engine_cc'],
        'fuel_type': c['fuel_type'],
        'expected_make': c['expected_make'],
        'expected_model': c['expected_model'],
        'expected_year': c['expected_year'],
        'matched_make': out.get('matched_make'),
        'matched_model': out.get('matched_model'),
        'matched_year': out.get('matched_year'),
        'confidence': out.get('confidence'),
        'match_type': out.get('match_type'),
        'recommended_ah': out.get('recommended_ah'),
        'preferred_tech': out.get('preferred_tech'),
        'primary_battery_code': primary.get('battery_code'),
        'primary_model_key': primary.get('model_key'),
        'primary_ah': primary.get('ah'),
        'notes': c.get('note'),
        'correct_match': (str(out.get('matched_model') or '').upper().strip() == str(c['expected_model'] or '').upper().strip()) and (out.get('matched_year') == c['expected_year'])
    })

# Save to Excel with a summary sheet
df = pd.DataFrame(results)
# Basic summary
total = len(df)
correct = df['correct_match'].sum()
accuracy = correct / total * 100.0
summary = pd.DataFrame([{ 'total_cases': total, 'correct_matches': int(correct), 'accuracy_pct': accuracy }])

with pd.ExcelWriter(OUT_XLSX, engine='openpyxl') as writer:
    df.to_excel(writer, sheet_name='results', index=False)
    summary.to_excel(writer, sheet_name='summary', index=False)

print(f"Wrote {OUT_XLSX}")
print(summary.to_string(index=False))
