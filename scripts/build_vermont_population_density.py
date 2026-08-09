from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import requests


HERE = Path(__file__).resolve().parents[1]
OUTPUT = HERE / "data" / "vermont_town_population_density.csv"
POPULATION_URL = (
    "https://www.arcgis.com/sharing/rest/content/items/"
    "84a286c51ece48488273710e1f49834e/data"
)
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2020_Gazetteer/2020_Gaz_cousubs_national.zip"
)


def fetch_text(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def fetch_bytes(url: str) -> bytes:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def load_vermont_areas() -> dict[str, dict[str, float]]:
    zip_bytes = fetch_bytes(GAZETTEER_URL)
    areas = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        with archive.open(archive.namelist()[0]) as raw:
            lines = (line.decode("latin1") for line in raw)
            reader = csv.reader(lines, delimiter="\t")
            headers = [header.strip() for header in next(reader)]
            for values in reader:
                row = {
                    header: (values[index].strip() if index < len(values) else "")
                    for index, header in enumerate(headers)
                }
                if row.get("USPS") != "VT":
                    continue
                areas[row["GEOID"]] = {
                    "land_sqmi": float(row["ALAND_SQMI"]),
                    "water_sqmi": float(row["AWATER_SQMI"]),
                }
    return areas


def build_density_rows() -> list[dict[str, object]]:
    areas = load_vermont_areas()
    population_text = fetch_text(POPULATION_URL)
    rows = []

    reader = csv.DictReader(io.StringIO(population_text))
    for row in reader:
        geoid = row["_geoid"].strip()
        area = areas.get(geoid)
        if not area:
            continue

        population = int(row["year2020"] or 0)
        land_sqmi = area["land_sqmi"]
        rows.append(
            {
                "town_geoid": geoid,
                "town": row["Town"].strip(),
                "county": row["County"].strip(),
                "population_2020": population,
                "land_sqmi": land_sqmi,
                "water_sqmi": area["water_sqmi"],
                "population_density_sqmi": (
                    round(population / land_sqmi, 2) if land_sqmi else 0
                ),
                "source_population": "VCGI DemoCensus_HISTMUNIPOP year2020",
                "source_area": "US Census 2020 Gazetteer county subdivisions",
            }
        )

    return sorted(rows, key=lambda item: (item["county"], item["town"]))


def main() -> None:
    rows = build_density_rows()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} town density rows to {OUTPUT}")


if __name__ == "__main__":
    main()
