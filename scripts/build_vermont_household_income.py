from __future__ import annotations

import csv
import re
from pathlib import Path

import requests


HERE = Path(__file__).resolve().parents[1]
OUTPUT = HERE / "data" / "vermont_household_income_2024.csv"
CENSUS_REPORTER_URL = (
    "https://api.censusreporter.org/1.0/data/show/latest"
    "?table_ids=B19013&geo_ids=060|04000US50"
)
SOURCE_LABEL = "Census Reporter ACS 2024 5-year B19013"


def parse_geoid(value: str) -> str:
    match = re.search(r"US(\d{10})$", value)
    return match.group(1) if match else ""


def parse_name(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in str(value or "").split(",")]
    town = re.sub(r"\s+(town|city|gores?|grant)$", "", parts[0], flags=re.I)
    county = re.sub(r"\s+County$", "", parts[1], flags=re.I) if len(parts) > 1 else ""
    return town, county


def parse_number(value):
    return "" if value is None else int(round(float(value)))


def build_income_rows() -> list[dict[str, object]]:
    response = requests.get(
        CENSUS_REPORTER_URL,
        headers={"User-Agent": "vt-campaign-finance/1.0"},
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()

    rows = []
    for census_geoid, table_data in payload.get("data", {}).items():
        town_geoid = parse_geoid(census_geoid)
        if not town_geoid:
            continue

        geography = payload.get("geography", {}).get(census_geoid, {})
        town, county = parse_name(geography.get("name", ""))
        table = table_data.get("B19013", {})
        estimate = table.get("estimate", {}).get("B19013001")
        error = table.get("error", {}).get("B19013001")

        rows.append(
            {
                "town_geoid": town_geoid,
                "town": town,
                "county": county,
                "median_household_income_2024": parse_number(estimate),
                "median_household_income_moe_2024": parse_number(error),
                "acs_release": payload.get("release", {}).get("name", ""),
                "source": SOURCE_LABEL,
            }
        )

    return sorted(rows, key=lambda item: (item["county"], item["town"]))


def main() -> None:
    rows = build_income_rows()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} town household income rows to {OUTPUT}")


if __name__ == "__main__":
    main()
