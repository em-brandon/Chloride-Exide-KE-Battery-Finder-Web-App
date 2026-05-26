"""
remove_ultrapower.py
--------------------
Removes any row in battery_specs_output.xlsx where any cell contains
'ULTRAPOWER' (case-insensitive). Saves the cleaned file in place and
prints a summary of what was removed.
"""

import pandas as pd

FILE = "battery_specs_output.xlsx"
KEYWORD = "ULTRAPOWER"

df = pd.read_excel(FILE)
original_count = len(df)

# Build a boolean mask: True for rows that contain the keyword in any column
mask = df.apply(
    lambda col: col.astype(str).str.contains(KEYWORD, case=False, na=False)
).any(axis=1)

removed = df[mask]
cleaned = df[~mask].reset_index(drop=True)

print(f"Rows scanned : {original_count}")
print(f"Rows removed : {len(removed)}")
print(f"Rows kept    : {len(cleaned)}")

if not removed.empty:
    print("\nRemoved rows:")
    print(removed.to_string(index=False))

cleaned.to_excel(FILE, index=False)
print(f"\nSaved cleaned file to: {FILE}")
