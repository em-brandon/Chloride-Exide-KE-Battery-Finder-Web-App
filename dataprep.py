import pandas as pd
import re
import time

# =========================
# CONFIG
# =========================
INPUT_FILE = "New-CRSP---July-2025.xlsx"
OUTPUT_CSV = "battery_lookup_dataset.csv"
OUTPUT_EXCEL = "battery_lookup_dataset.xlsx"
LOG_EVERY_N_ROWS = 500  # adjust depending on dataset size

# =========================
# TIMER UTILITY
# =========================
def log_section(title):
    print(f"\n[START] {title}")
    return time.time()

def end_section(start_time, title):
    elapsed = time.time() - start_time
    print(f"[END] {title} | Time taken: {elapsed:.2f}s")


# =========================
# LOAD DATA
# =========================
start = log_section("Loading dataset")
df = pd.read_excel(INPUT_FILE)
end_section(start, "Loading dataset")

# =========================
# CLEAN COLUMN NAMES
# =========================
start = log_section("Cleaning column names")
df.columns = df.columns.str.strip().str.lower().str.replace(r'[\s\n]+', '_', regex=True)
print("Columns detected:", df.columns.tolist())
end_section(start, "Cleaning column names")

# =========================
# HELPER FUNCTIONS
# =========================

def extract_years(year_value):
    if pd.isna(year_value):
        return []

    year_value = str(year_value)
    match = re.findall(r"\d{4}", year_value)

    return [int(y) for y in match] if match else []


def split_batteries(battery_value):
    if pd.isna(battery_value):
        return []

    battery_value = str(battery_value).upper()
    parts = re.split(r"[\/,;]", battery_value)

    return [
        p.strip().replace(" ", "")
        for p in parts if p.strip()
    ]


def normalize_battery(battery):
    return battery.upper().replace(" ", "") if battery else ""


# =========================
# REQUIRED COLUMNS CHECK
# =========================
start = log_section("Validating required columns")

required_cols = ["make", "model"]
missing = [col for col in required_cols if col not in df.columns]

if missing:
    raise Exception(f"Missing required columns: {missing}")

end_section(start, "Validating required columns")

# =========================
# DATA PREPARATION
# =========================
start = log_section("Preparing dataset")

output_cols = ["make", "model", "model_number", "engine_capacity", "fuel"]
present_cols = [c for c in output_cols if c in df.columns]

rows = []
total_rows = len(df)

for idx, (_, row) in enumerate(df.iterrows(), start=1):
    record = {c: str(row.get(c, "")).strip() for c in present_cols}
    # Skip completely empty rows
    if not record.get("make") or record["make"].lower() == "nan":
        continue
    rows.append(record)

    if idx % LOG_EVERY_N_ROWS == 0 or idx == total_rows:
        print(f"Processed {idx}/{total_rows} rows ({(idx/total_rows)*100:.2f}%)")

end_section(start, "Preparing dataset")

# =========================
# FINAL DATAFRAME
# =========================
start = log_section("Building final dataset")

final_df = pd.DataFrame(rows, columns=present_cols)
print(f"Initial records generated: {len(final_df)}")

final_df = final_df.drop_duplicates()
print(f"After removing duplicates: {len(final_df)}")

final_df = final_df.sort_values(by=["make", "model"])

end_section(start, "Building final dataset")

# =========================
# SAVE OUTPUT
# =========================
start = log_section("Saving output files")

final_df.to_csv(OUTPUT_CSV, index=False)
print(f"CSV saved: {OUTPUT_CSV}")

final_df.to_excel(OUTPUT_EXCEL, index=False)
print(f"Excel saved: {OUTPUT_EXCEL}")

end_section(start, "Saving output files")

print("\nProcess complete")
print(f"Final record count: {len(final_df)}")
