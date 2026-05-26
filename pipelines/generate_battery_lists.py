import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

thin_border = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)

def style_title(ws, row, text, color):
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(bold=True, size=13, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=color)
    cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.merge_cells(f'A{row}:B{row}')
    ws.row_dimensions[row].height = 20

def add_section(ws, section_name, data, start_row, hdr_color, col_hdr_color):
    # Section header row
    cell = ws.cell(row=start_row, column=1, value=section_name)
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor=hdr_color)
    cell.alignment = Alignment(horizontal='center')
    ws.merge_cells(f'A{start_row}:B{start_row}')
    start_row += 1

    # Column headers
    for col, label in enumerate(["Battery Type", "Amps/Capacity"], start=1):
        c = ws.cell(row=start_row, column=col, value=label)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor=col_hdr_color)
        c.border = thin_border
        c.alignment = Alignment(horizontal='center')
    start_row += 1

    for battery, amps in data:
        ws.cell(row=start_row, column=1, value=battery).border = thin_border
        amp_cell = ws.cell(row=start_row, column=2, value=amps)
        amp_cell.border = thin_border
        amp_cell.alignment = Alignment(horizontal='center')
        start_row += 1

    return start_row + 1  # blank gap


# ============================================================
# LOCAL BATTERIES
# ============================================================
wb_local = openpyxl.Workbook()
wb_local.remove(wb_local.active)

# ---------- Sheet: Powerlast ----------
ws = wb_local.create_sheet("Powerlast")
style_title(ws, 1, "POWERLAST BATTERIES — LOCAL", "1F4E79")
row = 3

powerlast_auto = [
    ("035MF NSL POWERLAST", 35),
    ("035MF NSL POWERLAST (SHRINK WRAPPED)", 35),
    ("045MF NSL POWERLAST", 45),
    ("045MF NSL POWERLAST (SHRINK WRAPPED)", 45),
    ("N50 L MF POWERLAST (SHORT BOX)", 50),
    ("N50MFL CHLORIDE EXIDE MAXX", 50),
    ("NS70MFL POWERLAST", 65),
    ("N70MFL POWERLAST", 70),
    ("N70MFL CHLORIDE EXIDE MAXX", 75),
    ("N70ZLMF POWERLAST", 80),
    ("090 MFL POWERLAST", 90),
    ("N100MFR POWERLAST", 100),
    ("N120ME L POWERLAST", 120),
    ("N150 MFL POWERLAST", 150),
    ("N180 MFL POWERLAST", 180),
    ("N200 MFL POWERLAST", 200),
    ("N220 MFL POWERLAST", 220),
    ("DIN55 MF POWERLAST", 55),
    ("DIN66 MF POWERLAST", 66),
    ("DIN75 MF POWERLAST", 75),
    ("DIN80 MF POWERLAST", 80),
    ("DIN88 MF POWERLAST", 88),
    ("DIN100 MF POWERLAST", 100),
    ("045 L MF POWERLAST EFB TECHNOLOGY BATTERY", 45),
    ("NS70 L MF POWERLAST EFB TECHNOLOGY BATTERY", 65),
    ("N70 L MF POWERLAST EFB TECHNOLOGY BATTERY", 70),
]
row = add_section(ws, "POWERLAST AUTOMOTIVE", powerlast_auto, row, "2E74B5", "BDD7EE")
ws.column_dimensions['A'].width = 48
ws.column_dimensions['B'].width = 16

# ---------- Sheet: Spark ----------
ws = wb_local.create_sheet("Spark")
style_title(ws, 1, "SPARK BATTERIES — LOCAL", "843C0C")
row = 3

spark_auto = [
    ("035MF NSL SPARK", 35),
    ("045MF NSL SPARK", 45),
    ("NS70MFL SPARK", 65),
    ("N70 MFL SPARK", 70),
    ("N120 L MF SPARK", 120),
    ("N150 MFL SPARK", 150),
    ("N200 MFL SPARK", 200),
]
row = add_section(ws, "SPARK AUTOMOTIVE", spark_auto, row, "C55A11", "FCE4D6")
ws.column_dimensions['A'].width = 42
ws.column_dimensions['B'].width = 16

# ---------- Sheet: Chloride Exide (Vented) ----------
ws = wb_local.create_sheet("Chloride Exide")
style_title(ws, 1, "CHLORIDE EXIDE BATTERIES — LOCAL", "375623")
row = 3

chloride_auto = [
    ("N50 SBR CHLORIDE EXIDE", 50),
    ("NS70 SBL CHLORIDE EXIDE", 65),
    ("N70 SBL CHLORIDE EXIDE", 70),
    ("N705BR CHLORIDE EXIDE MAXX MATATU", 72),
    ("N100 SBR CHLORIDE EXIDE", 100),
    ("120/12/SBR PP LOCAL", 120),
    ("N150 SBR CHLORIDE EXIDE", 150),
    ("N200 SBR CHLORIDE EXIDE", 200),
]
row = add_section(ws, "VENTED AUTOMOTIVE", chloride_auto, row, "538135", "E2EFDA")
ws.column_dimensions['A'].width = 46
ws.column_dimensions['B'].width = 16

wb_local.save("Local_Batteries.xlsx")
print("Local_Batteries.xlsx saved.")


# ============================================================
# IMPORTED BATTERIES
# ============================================================
wb_imp = openpyxl.Workbook()
wb_imp.remove(wb_imp.active)

# ---------- Sheet: Exide Matrix ----------
ws = wb_imp.create_sheet("Exide Matrix")
style_title(ws, 1, "EXIDE MATRIX BATTERIES — IMPORTED", "7B0000")
row = 3

exide_smf = [
    ("045L MF EXIDE MATRIX", 45),
    ("N570L MF EXIDE MATRIX", 65),
    ("N70L MF EXIDE MATRIX", 70),
    ("N70R MF EXIDE MATRIX", 70),
    ("090MFL EXIDE MATRIX", 90),
    ("090MFR EXIDE MATRIX", 90),
    ("N180 MF EXIDE", 180),
]
exide_din_smf = [
    ("DIN 43MF L EXIDE MATRIX", 43),
    ("DIN 66MF L EXIDE MATRIX PLUS", 66),
    ("DIN 74MF L EXIDE MATRIX PLUS", 74),
    ("DIN 80MF L EXIDE MATRIX PLUS", 80),
    ("DIN 100MF L EXIDE MATRIX PLUS", 100),
]
exide_din_agm = [
    ("DIN 060MF L EXIDE AGM", 60),
    ("DIN 070MF L EXIDE AGM", 70),
    ("DIN 80 MF L EXIDE AGM", 80),
    ("DIN 095MF L EXIDE AGM", 95),
]
exide_efb = [
    ("035MF L EXIDE COMPACT - 40 AMPS", 40),
    ("045MF L EFB EXIDE COMPACT - 50 AMPS", 50),
    ("Q85MF L EFB EXIDE - 70 AMPS", 70),
    ("Q85MF R EFB EXIDE - 70 AMPS", 70),
    ("070MF L EFB EXIDE COMPACT 80 AMPS", 80),
    ("090MFL EXIDE EFB", 90),
    ("090MFR EXIDE EFB", 90),
]

row = add_section(ws, "EXIDE MATRIX SMF", exide_smf, row, "C00000", "FFCCCC")
row = add_section(ws, "EXIDE MATRIX DIN SERIES SMF", exide_din_smf, row, "C00000", "FFCCCC")
row = add_section(ws, "EXIDE MATRIX DIN SERIES AGM", exide_din_agm, row, "C00000", "FFCCCC")
row = add_section(ws, "EXIDE MATRIX EFB", exide_efb, row, "C00000", "FFCCCC")
ws.column_dimensions['A'].width = 46
ws.column_dimensions['B'].width = 16

# ---------- Sheet: Supreme ----------
ws = wb_imp.create_sheet("Supreme")
style_title(ws, 1, "SUPREME BATTERIES — IMPORTED", "1F4E79")
row = 3

supreme_smf = [
    ("035L MF SUPREME", 35),
    ("045L MF SUPREME", 45),
    ("N50 SHORT MFL SUPREME - 65AH", 50),
    ("NS70MFL SUPREME", 65),
    ("NS70MFR SUPREME", 65),
    ("N70L MF SUPREME", 70),
    ("N70Z MF SUPREME", 70),
    ("090L MFSUPREME", 90),
    ("090R MF SUPREME", 90),
    ("120MF SUPREME", 120),
    ("N150R MFSUPREME", 150),
    ("N180 MF R SUPREME", 180),
    ("N200L MFSUPREME", 200),
]
supreme_din_smf = [
    ("DIN 55 MF SUPREME", 55),
    ("DIN 66 MF SUPREME", 66),
    ("DIN 72 MF SUPREME", 72),
    ("DIN 80 MF SUPREME", 80),
    ("DIN 88 MF SUPREME", 88),
    ("DIN100MF SUPREME", 100),
]

row = add_section(ws, "SUPREME SMF", supreme_smf, row, "2E74B5", "BDD7EE")
row = add_section(ws, "SUPREME DIN SERIES SMF", supreme_din_smf, row, "2E74B5", "BDD7EE")
ws.column_dimensions['A'].width = 42
ws.column_dimensions['B'].width = 16

# ---------- Sheet: Sebang ----------
ws = wb_imp.create_sheet("Sebang")
style_title(ws, 1, "SEBANG BATTERIES — IMPORTED", "375623")
row = 3

sebang_agm = [
    ("DIN 60 MF SEBANG AGM", 60),
    ("DIN 70MF SEBANG AGM", 70),
    ("DIN 80 MF SEBANG AGM", 80),
    ("DIN 95MF SEBANG AGM", 95),
    ("DIN 105MF SEBANG AGM", 105),
]
sebang_efb = [
    ("045MF L SEBANG EFB COMPACT - 55 AMPS", 55),
    ("065MF L (Q85) SEBANG EFB", 65),
    ("070MFL SEBANG EFB", 70),
    ("095MFL SEBANG EFB", 95),
    ("095MFR SEBANG EFB", 95),
]

row = add_section(ws, "SEBANG DIN SERIES AGM", sebang_agm, row, "538135", "E2EFDA")
row = add_section(ws, "SEBANG EFB", sebang_efb, row, "538135", "E2EFDA")
ws.column_dimensions['A'].width = 46
ws.column_dimensions['B'].width = 16

wb_imp.save("Imported_Batteries.xlsx")
print("Imported_Batteries.xlsx saved.")
