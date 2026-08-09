from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[1]
DB = HERE / "data" / "campaign_finance.sqlite"
ALIASES = HERE / "town_aliases.csv"
OUT = HERE / "data" / "windsor_address_geocodes.csv"

VT_TOWNS_QUERY = (
    "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/"
    "FS_VCGI_OPENDATA_Boundary_BNDHASH_poly_towns_SP_v1/FeatureServer/0/query"
)
CENSUS_GEOCODER = (
    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
)

PO_BOX_RE = re.compile(
    r"(^|\b)(P\.?\s*O\.?|POST\s+OFFICE|PO)\s*BOX\b|^P\.?O\.?BOX\b",
    re.IGNORECASE,
)


def normalize_place(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value or "").strip().upper().split())


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value or "").strip()


def load_town_sets() -> tuple[set[str], set[str]]:
    params = {
        "where": "1=1",
        "outFields": "TOWNNAME,TOWNNAMEMC,CNTY",
        "returnGeometry": "false",
        "f": "json",
    }
    url = VT_TOWNS_QUERY + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = json.load(response)

    valid_towns: set[str] = set()
    windsor_towns: set[str] = set()
    for feature in data.get("features", []):
        attrs = feature.get("attributes", {})
        town = normalize_place(
            attrs.get("TOWNNAME")
            or attrs.get("TOWNNAMEMC")
            or ""
        )
        if not town:
            continue
        valid_towns.add(town)
        if attrs.get("CNTY") == 27:
            windsor_towns.add(town)

    return valid_towns, windsor_towns


def load_aliases(valid_towns: set[str]) -> dict[str, str]:
    if not ALIASES.exists():
        return {}

    aliases: dict[str, str] = {}
    with ALIASES.open(newline="") as alias_file:
        for row in csv.DictReader(alias_file):
            reported_city = normalize_place(row.get("reported_city"))
            municipality = normalize_place(row.get("municipality"))
            if reported_city and municipality in valid_towns:
                aliases[reported_city] = municipality
    return aliases


def resolve_municipality(
    city: object,
    valid_towns: set[str],
    aliases: dict[str, str],
) -> str:
    normalized_city = normalize_place(city)
    if normalized_city in aliases:
        return aliases[normalized_city]
    if normalized_city in valid_towns:
        return normalized_city
    return ""


def read_existing_cache() -> dict[str, dict[str, str]]:
    if not OUT.exists():
        return {}

    with OUT.open(newline="") as geocode_file:
        return {
            row["address_key"]: row
            for row in csv.DictReader(geocode_file)
            if row.get("address_key")
        }


def address_key(parts: list[object]) -> str:
    normalized = "|".join(normalize_place(part) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def is_physical_address(address_line1: object) -> bool:
    address = str(address_line1 or "").strip()
    return bool(address) and not PO_BOX_RE.search(address)


def geocode(address: str) -> dict[str, str]:
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    url = CENSUS_GEOCODER + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.load(response)

    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        return {
            "geocode_status": "unmatched",
            "matched_address": "",
            "latitude": "",
            "longitude": "",
        }

    match = matches[0]
    coordinates = match.get("coordinates", {})
    return {
        "geocode_status": "matched",
        "matched_address": match.get("matchedAddress", ""),
        "latitude": str(coordinates.get("y", "")),
        "longitude": str(coordinates.get("x", "")),
    }


def main() -> None:
    valid_towns, windsor_towns = load_town_sets()
    aliases = load_aliases(valid_towns)

    conn = sqlite3.connect(DB)
    frame = pd.read_sql_query(
        """
        SELECT
            roster_name,
            transaction_id,
            transaction_guid,
            amount,
            name,
            city,
            state,
            zip,
            raw_json
        FROM transactions
        WHERE kind = 'contributions'
          AND UPPER(TRIM(COALESCE(state, ''))) = 'VT'
        """,
        conn,
    )
    conn.close()

    frame["address_line1"] = frame["raw_json"].map(
        lambda value: (json.loads(value).get("addressLine1") if value else "")
    )
    frame["address_line2"] = frame["raw_json"].map(
        lambda value: (json.loads(value).get("addressLine2") if value else "")
    )
    for col in ["address_line1", "address_line2", "city", "state", "zip"]:
        frame[col] = frame[col].map(clean_text)

    frame["municipality"] = frame["city"].map(
        lambda city: resolve_municipality(city, valid_towns, aliases)
    )

    windsor = frame[
        frame["municipality"].isin(windsor_towns)
        & frame["address_line1"].map(is_physical_address)
    ].copy()
    windsor["address_key"] = windsor.apply(
        lambda row: address_key(
            [
                row["address_line1"],
                row["address_line2"],
                row["city"],
                row["state"],
                row["zip"],
            ]
        ),
        axis=1,
    )

    grouped = (
        windsor.groupby(
            [
                "address_key",
                "address_line1",
                "address_line2",
                "city",
                "state",
                "zip",
                "municipality",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            records=("amount", "size"),
            amount=("amount", "sum"),
            contributors=("name", "nunique"),
            candidates=("roster_name", "nunique"),
        )
        .sort_values("amount", ascending=False)
    )

    existing = read_existing_cache()
    rows: list[dict[str, object]] = []
    for row in grouped.to_dict("records"):
        one_line_address = ", ".join(
            clean_text(part)
            for part in [
                row["address_line1"],
                row["address_line2"],
                row["city"],
                row["state"],
                row["zip"],
            ]
            if clean_text(part)
        )
        cached = existing.get(str(row["address_key"]))
        if cached:
            geocode_result = {
                "geocode_status": cached.get("geocode_status", ""),
                "matched_address": cached.get("matched_address", ""),
                "latitude": cached.get("latitude", ""),
                "longitude": cached.get("longitude", ""),
            }
        else:
            geocode_result = geocode(one_line_address)
            time.sleep(0.2)

        rows.append(
            {
                **row,
                "one_line_address": one_line_address,
                **geocode_result,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)

    output = pd.DataFrame(rows)
    matched = output[output["geocode_status"] == "matched"]
    print(f"wrote {OUT}")
    print(f"physical Windsor addresses: {len(output):,}")
    print(f"geocoded addresses: {len(matched):,}")
    print(f"geocoded amount: ${matched['amount'].sum():,.2f}")


if __name__ == "__main__":
    main()
