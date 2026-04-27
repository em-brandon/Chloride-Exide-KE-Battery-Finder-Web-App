import re

import pandas as pd

import matcher


def _parse_range(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = re.match(r"^(\d+)\s*[\-\u2013\u2014]\s*(\d+)$", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def main() -> int:
    df = pd.read_excel("accuracy_analysis.xlsx", sheet_name="28-Case Audit")

    tech_ok = 0
    ah_ok = 0
    n = 0
    failures: list[str] = []

    for _, row in df.iterrows():
        make = row.get("Make")
        model = row.get("Model")
        year = row.get("Year")
        if pd.isna(make) or pd.isna(model) or pd.isna(year):
            continue

        fuel = row.get("Fuel")
        stop_start = bool(row.get("Stop-Start")) if "Stop-Start" in row else False

        rec = matcher.recommend(
            str(make),
            str(model),
            int(year),
            fuel_type=None if pd.isna(fuel) else str(fuel),
            has_stop_start=stop_start,
        )

        expected_tech = row.get("Expected Tech")
        expected_ah_range = row.get("Expected Ah Range")
        ah_range = _parse_range(expected_ah_range)

        tech_pass = None if pd.isna(expected_tech) else (rec["preferred_tech"] == str(expected_tech))
        ah_pass = None
        if ah_range is not None:
            lo, hi = ah_range
            ah_pass = lo <= int(rec["recommended_ah"]) <= hi

        if tech_pass is not None:
            tech_ok += int(tech_pass)
        if ah_pass is not None:
            ah_ok += int(ah_pass)

        n += 1

        if (tech_pass is False) or (ah_pass is False):
            failures.append(
                f"- {str(make).upper()} {str(model).upper()} {int(year)}: "
                f"expTech={expected_tech} actTech={rec['preferred_tech']}; "
                f"expAh={expected_ah_range} actAh={rec['recommended_ah']}; "
                f"fuel={rec['fuel_type']}; conf={rec['confidence']}"
            )

    print(f"Cases evaluated: {n}")
    print(f"Tech accuracy: {tech_ok}/{n} = {tech_ok / n:.1%}")
    print(f"Ah-in-range:   {ah_ok}/{n} = {ah_ok / n:.1%}")
    print(f"Failures: {len(failures)}")
    for line in failures[:25]:
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

