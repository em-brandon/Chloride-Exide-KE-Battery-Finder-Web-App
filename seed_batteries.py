"""
Clears battery_specs and reseeds it from the Chloride Exide price lists (Feb 2026).
Origins: local | imported
Brands:  Powerlast, Spark, Chloride Exide, Exide Matrix, Supreme, Sebang
"""

import re
from sqlalchemy import text
import db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def model_key(code: str) -> str:
    c = code.strip()
    if m := re.match(r'^DIN[\s\-]?(\d+)', c, re.IGNORECASE):
        return f"DIN{m.group(1)}"
    if m := re.match(r'^(Q\d+)', c, re.IGNORECASE):
        return m.group(1).upper()
    if m := re.match(r'^(NS\d+)', c, re.IGNORECASE):
        return m.group(1).upper()
    if m := re.match(r'^(N\d+)', c, re.IGNORECASE):
        return m.group(1).upper()
    if m := re.match(r'^(\d{3})', c):
        return m.group(1)
    return c.split()[0]


def technology(code: str) -> str:
    u = code.upper()
    if 'AGM' in u:
        return 'AGM'
    if 'EFB' in u:
        return 'EFB'
    if 'SBR' in u or 'SBL' in u or 'SBR' in u:
        return 'SB (Flooded)'
    return 'MF'


def row(code, ah, origin, brand):
    return {
        'battery_code': code,
        'model_key':    model_key(code),
        'ah':           float(ah),
        'cca_en':       None,
        'technology':   technology(code),
        'origin':       origin,
        'brand':        brand,
        'deleted_at':   None,
    }


# ---------------------------------------------------------------------------
# Data — LOCAL BATTERIES
# ---------------------------------------------------------------------------

LOCAL = 'local'
IMPORTED = 'imported'

batteries = []

# ---- Powerlast (local) ----
PL = 'Powerlast'
batteries += [
    row('035MF NSL POWERLAST',                          35, LOCAL, PL),
    row('035MF NSL POWERLAST (SHRINK WRAPPED)',         35, LOCAL, PL),
    row('045MF NSL POWERLAST',                          45, LOCAL, PL),
    row('045MF NSL POWERLAST (SHRINK WRAPPED)',         45, LOCAL, PL),
    row('N50 L MF POWERLAST (SHORT BOX)',               50, LOCAL, PL),
    row('N50MFL CHLORIDE EXIDE MAXX',                   50, LOCAL, PL),
    row('NS70MFL POWERLAST',                            65, LOCAL, PL),
    row('N70MFL POWERLAST',                             70, LOCAL, PL),
    row('N70MFL CHLORIDE EXIDE MAXX',                   75, LOCAL, PL),
    row('N70ZLMF POWERLAST',                            80, LOCAL, PL),
    row('090 MFL POWERLAST',                            90, LOCAL, PL),
    row('N100MFR POWERLAST',                           100, LOCAL, PL),
    row('N120ME L POWERLAST',                          120, LOCAL, PL),
    row('N150 MFL POWERLAST',                          150, LOCAL, PL),
    row('N180 MFL POWERLAST',                          180, LOCAL, PL),
    row('N200 MFL POWERLAST',                          200, LOCAL, PL),
    row('N220 MFL POWERLAST',                          220, LOCAL, PL),
    row('DIN55 MF POWERLAST',                           55, LOCAL, PL),
    row('DIN66 MF POWERLAST',                           66, LOCAL, PL),
    row('DIN75 MF POWERLAST',                           75, LOCAL, PL),
    row('DIN80 MF POWERLAST',                           80, LOCAL, PL),
    row('DIN88 MF POWERLAST',                           88, LOCAL, PL),
    row('DIN100 MF POWERLAST',                         100, LOCAL, PL),
    row('045 L MF POWERLAST EFB TECHNOLOGY BATTERY',    45, LOCAL, PL),
    row('NS70 L MF POWERLAST EFB TECHNOLOGY BATTERY',   65, LOCAL, PL),
    row('N70 L MF POWERLAST EFB TECHNOLOGY BATTERY',    70, LOCAL, PL),
]

# ---- Spark (local) ----
SP = 'Spark'
batteries += [
    row('035MF NSL SPARK',   35, LOCAL, SP),
    row('045MF NSL SPARK',   45, LOCAL, SP),
    row('NS70MFL SPARK',     65, LOCAL, SP),
    row('N70 MFL SPARK',     70, LOCAL, SP),
    row('N120 L MF SPARK',  120, LOCAL, SP),
    row('N150 MFL SPARK',   150, LOCAL, SP),
    row('N200 MFL SPARK',   200, LOCAL, SP),
]

# ---- Chloride Exide — Vented (local) ----
CE = 'Chloride Exide'
batteries += [
    row('N50 SBR CHLORIDE EXIDE',           50, LOCAL, CE),
    row('NS70 SBL CHLORIDE EXIDE',          65, LOCAL, CE),
    row('N70 SBL CHLORIDE EXIDE',           70, LOCAL, CE),
    row('N705BR CHLORIDE EXIDE MAXX MATATU',72, LOCAL, CE),
    row('N100 SBR CHLORIDE EXIDE',         100, LOCAL, CE),
    row('120/12/SBR PP LOCAL',             120, LOCAL, CE),
    row('N150 SBR CHLORIDE EXIDE',         150, LOCAL, CE),
    row('N200 SBR CHLORIDE EXIDE',         200, LOCAL, CE),
]

# ---------------------------------------------------------------------------
# Data — IMPORTED BATTERIES
# ---------------------------------------------------------------------------

# ---- Exide Matrix (imported) ----
EM = 'Exide Matrix'
batteries += [
    # SMF
    row('045L MF EXIDE MATRIX',              45, IMPORTED, EM),
    row('N570L MF EXIDE MATRIX',             65, IMPORTED, EM),
    row('N70L MF EXIDE MATRIX',              70, IMPORTED, EM),
    row('N70R MF EXIDE MATRIX',              70, IMPORTED, EM),
    row('090MFL EXIDE MATRIX',               90, IMPORTED, EM),
    row('090MFR EXIDE MATRIX',               90, IMPORTED, EM),
    row('N180 MF EXIDE',                    180, IMPORTED, EM),
    # DIN Series SMF
    row('DIN 43MF L EXIDE MATRIX',           43, IMPORTED, EM),
    row('DIN 66MF L EXIDE MATRIX PLUS',      66, IMPORTED, EM),
    row('DIN 74MF L EXIDE MATRIX PLUS',      74, IMPORTED, EM),
    row('DIN 80MF L EXIDE MATRIX PLUS',      80, IMPORTED, EM),
    row('DIN 100MF L EXIDE MATRIX PLUS',    100, IMPORTED, EM),
    # DIN Series AGM
    row('DIN 060MF L EXIDE AGM',             60, IMPORTED, EM),
    row('DIN 070MF L EXIDE AGM',             70, IMPORTED, EM),
    row('DIN 80 MF L EXIDE AGM',             80, IMPORTED, EM),
    row('DIN 095MF L EXIDE AGM',             95, IMPORTED, EM),
    # EFB
    {**row('035MF L EXIDE COMPACT - 40 AMPS', 40, IMPORTED, EM), 'technology': 'EFB'},
    row('045MF L EFB EXIDE COMPACT - 50 AMPS',50, IMPORTED, EM),
    row('Q85MF L EFB EXIDE - 70 AMPS',       70, IMPORTED, EM),
    row('Q85MF R EFB EXIDE - 70 AMPS',       70, IMPORTED, EM),
    row('070MF L EFB EXIDE COMPACT 80 AMPS', 80, IMPORTED, EM),
    row('090MFL EXIDE EFB',                  90, IMPORTED, EM),
    row('090MFR EXIDE EFB',                  90, IMPORTED, EM),
]

# ---- Supreme (imported) ----
SU = 'Supreme'
batteries += [
    # SMF
    row('035L MF SUPREME',              35, IMPORTED, SU),
    row('045L MF SUPREME',              45, IMPORTED, SU),
    row('N50 SHORT MFL SUPREME - 65AH', 50, IMPORTED, SU),
    row('NS70MFL SUPREME',              65, IMPORTED, SU),
    row('NS70MFR SUPREME',              65, IMPORTED, SU),
    row('N70L MF SUPREME',              70, IMPORTED, SU),
    row('N70Z MF SUPREME',              70, IMPORTED, SU),
    row('090L MFSUPREME',               90, IMPORTED, SU),
    row('090R MF SUPREME',              90, IMPORTED, SU),
    row('120MF SUPREME',               120, IMPORTED, SU),
    row('N150R MFSUPREME',             150, IMPORTED, SU),
    row('N180 MF R SUPREME',           180, IMPORTED, SU),
    row('N200L MFSUPREME',             200, IMPORTED, SU),
    # DIN Series SMF
    row('DIN 55 MF SUPREME',            55, IMPORTED, SU),
    row('DIN 66 MF SUPREME',            66, IMPORTED, SU),
    row('DIN 72 MF SUPREME',            72, IMPORTED, SU),
    row('DIN 80 MF SUPREME',            80, IMPORTED, SU),
    row('DIN 88 MF SUPREME',            88, IMPORTED, SU),
    row('DIN100MF SUPREME',            100, IMPORTED, SU),
]

# ---- Sebang (imported) ----
SE = 'Sebang'
batteries += [
    # DIN Series AGM
    row('DIN 60 MF SEBANG AGM',                    60, IMPORTED, SE),
    row('DIN 70MF SEBANG AGM',                     70, IMPORTED, SE),
    row('DIN 80 MF SEBANG AGM',                    80, IMPORTED, SE),
    row('DIN 95MF SEBANG AGM',                     95, IMPORTED, SE),
    row('DIN 105MF SEBANG AGM',                   105, IMPORTED, SE),
    # EFB
    row('045MF L SEBANG EFB COMPACT - 55 AMPS',    55, IMPORTED, SE),
    row('065MF L (Q85) SEBANG EFB',                65, IMPORTED, SE),
    row('070MFL SEBANG EFB',                        70, IMPORTED, SE),
    row('095MFL SEBANG EFB',                        95, IMPORTED, SE),
    row('095MFR SEBANG EFB',                        95, IMPORTED, SE),
]

# ---------------------------------------------------------------------------
# Execute — delete all, then insert
# ---------------------------------------------------------------------------

with db.engine.begin() as conn:
    deleted = conn.execute(text('DELETE FROM battery_specs')).rowcount
    print(f'Deleted {deleted} existing rows.')

    conn.execute(
        text("""
            INSERT INTO battery_specs
                (battery_code, model_key, ah, cca_en, technology, origin, brand, deleted_at)
            VALUES
                (:battery_code, :model_key, :ah, :cca_en, :technology, :origin, :brand, :deleted_at)
        """),
        batteries,
    )
    print(f'Inserted {len(batteries)} batteries.')

print('\nBreakdown:')
local_count    = sum(1 for b in batteries if b['origin'] == 'local')
imported_count = sum(1 for b in batteries if b['origin'] == 'imported')
print(f'  Local:    {local_count}')
print(f'  Imported: {imported_count}')

from collections import Counter
for brand, count in sorted(Counter(b['brand'] for b in batteries).items()):
    origin = next(b['origin'] for b in batteries if b['brand'] == brand)
    print(f'    {brand:20} {count:3} ({origin})')
