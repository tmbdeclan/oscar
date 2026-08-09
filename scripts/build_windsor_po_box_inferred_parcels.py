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
OUT = HERE / "data" / "windsor_po_box_inferred_parcels.csv"

VT_TOWNS_QUERY = (
    "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/"
    "FS_VCGI_OPENDATA_Boundary_BNDHASH_poly_towns_SP_v1/FeatureServer/0/query"
)
PARCEL_QUERY = (
    "https://maps.vtrans.vermont.gov/arcgis/rest/services/"
    "ROW/Parcels/MapServer/8/query"
)

PO_BOX_RE = re.compile(
    r"(^|\b)(P\.?\s*O\.?|POST\s+OFFICE|PO)\s*BOX\b|^P\.?O\.?BOX\b",
    re.IGNORECASE,
)
NON_NAME_TOKENS = {
    "JR",
    "SR",
    "II",
    "III",
    "IV",
    "REVOCABLE",
    "TRUST",
    "TR",
    "TRUSTEE",
    "LIVING",
    "ESTATE",
    "LLC",
    "INC",
    "LTD",
    "CORP",
    "CO",
    "THE",
}


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value or "").strip()
    return "" if text.lower() == "nan" else text


def normalize_place(value: object) -> str:
    return " ".join(clean_text(value).upper().split())


def normalize_po_box(value: object) -> str:
    text = normalize_place(value)
    text = re.sub(r"\bP\s*\.?\s*O\s*\.?\s*BOX\b", "PO BOX", text)
    text = re.sub(r"\bPOST OFFICE BOX\b", "PO BOX", text)
    text = re.sub(r"^P\.?O\.?BOX\b", "PO BOX", text)
    text = re.sub(r"\s+", " ", text)
    return text


def is_po_box(value: object) -> bool:
    return bool(PO_BOX_RE.search(clean_text(value)))


def zip5(value: object) -> str:
    match = re.search(r"\d{5}", clean_text(value))
    return match.group(0) if match else ""


def stable_key(parts: list[object]) -> str:
    normalized = "|".join(normalize_place(part) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def name_tokens(value: object) -> set[str]:
    text = clean_text(value).upper()
    text = text.replace("&", " ")
    tokens = re.findall(r"[A-Z0-9]+", text)
    return {token for token in tokens if token and token not in NON_NAME_TOKENS}


def donor_name_variants(value: object) -> list[str]:
    text = clean_text(value).upper()
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) >= 2:
        last = parts[0]
        rest = " ".join(parts[1:])
        return [f"{rest} {last}", f"{last} {rest}", text]
    return [text]


def owner_matches_donor(donor: object, owner1: object, owner2: object) -> bool:
    donor_sets = [name_tokens(variant) for variant in donor_name_variants(donor)]
    owner_sets = [name_tokens(owner1), name_tokens(owner2)]
    owner_sets = [tokens for tokens in owner_sets if tokens]

    for donor_set in donor_sets:
        if len(donor_set) < 2:
            continue
        for owner_set in owner_sets:
            if donor_set.issubset(owner_set) or owner_set.issubset(donor_set):
                return True
            if len(donor_set & owner_set) >= min(2, len(donor_set)):
                return True
    return False


def load_town_sets() -> tuple[set[str], set[str]]:
    params = {
        "where": "1=1",
        "outFields": "TOWNNAME,TOWNNAMEMC,CNTY",
        "returnGeometry": "false",
        "f": "json",
    }
    with urllib.request.urlopen(
        VT_TOWNS_QUERY + "?" + urllib.parse.urlencode(params),
        timeout=60,
    ) as response:
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
    with ALIASES.open(newline="") as alias_file:
        return {
            normalize_place(row["reported_city"]): normalize_place(
                row["municipality"]
            )
            for row in csv.DictReader(alias_file)
            if normalize_place(row.get("reported_city"))
            and normalize_place(row.get("municipality")) in valid_towns
        }


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


def ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    if len(ring) < 3:
        xs = [point[0] for point in ring]
        ys = [point[1] for point in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    area = 0.0
    cx = 0.0
    cy = 0.0
    for i, point in enumerate(ring):
        x1, y1 = point[:2]
        x2, y2 = ring[(i + 1) % len(ring)][:2]
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross

    area *= 0.5
    if abs(area) < 1e-12:
        xs = [point[0] for point in ring]
        ys = [point[1] for point in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return cx / (6 * area), cy / (6 * area)


def geometry_centroid(geometry: dict) -> tuple[float, float]:
    rings = geometry.get("rings") or []
    if not rings:
        return "", ""
    largest_ring = max(
        rings,
        key=lambda ring: (
            (max(point[0] for point in ring) - min(point[0] for point in ring))
            * (max(point[1] for point in ring) - min(point[1] for point in ring))
        ),
    )
    lon, lat = ring_centroid(largest_ring)
    return lat, lon


def query_parcels_for_town(town: str) -> list[dict]:
    out_fields = ",".join(
        [
            "OBJECTID",
            "TOWN",
            "SPAN",
            "OWNER1",
            "OWNER2",
            "ADDRGL1",
            "ADDRGL2",
            "CITYGL",
            "STGL",
            "ZIPGL",
            "LOCAPROP",
            "E911ADDR",
            "PropertyLocationStreet",
            "PropertyLocationCity",
        ]
    )
    rows: list[dict] = []
    offset = 0
    while True:
        escaped_town = town.replace("'", "''")
        params = {
            "where": f"TOWN='{escaped_town}'",
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": 1000,
        }
        with urllib.request.urlopen(
            PARCEL_QUERY + "?" + urllib.parse.urlencode(params),
            timeout=90,
        ) as response:
            data = json.load(response)
        features = data.get("features", [])
        for feature in features:
            attrs = feature.get("attributes", {})
            if normalize_place(attrs.get("OWNER1")) in {"", "NULL"}:
                continue
            lat, lon = geometry_centroid(feature.get("geometry", {}))
            rows.append({**attrs, "latitude": lat, "longitude": lon})
        if not data.get("exceededTransferLimit") or not features:
            break
        offset += len(features)
        time.sleep(0.2)
    return rows


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
        lambda value: clean_text(
            json.loads(value).get("addressLine1") if value else ""
        )
    )
    frame["address_line2"] = frame["raw_json"].map(
        lambda value: clean_text(
            json.loads(value).get("addressLine2") if value else ""
        )
    )
    frame["municipality"] = frame["city"].map(
        lambda city: resolve_municipality(city, valid_towns, aliases)
    )

    po_boxes = frame[
        frame["municipality"].isin(windsor_towns)
        & frame["address_line1"].map(is_po_box)
    ].copy()
    po_boxes["po_box_key"] = po_boxes.apply(
        lambda row: stable_key(
            [
                row["name"],
                row["address_line1"],
                row["city"],
                row["state"],
                row["zip"],
                row["municipality"],
            ]
        ),
        axis=1,
    )
    grouped = (
        po_boxes.groupby(
            [
                "po_box_key",
                "name",
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
            candidates=("roster_name", "nunique"),
        )
        .sort_values("amount", ascending=False)
    )

    parcel_rows: dict[str, list[dict]] = {}
    for town in sorted(grouped["municipality"].unique()):
        parcel_rows[town] = query_parcels_for_town(town)
        time.sleep(0.2)

    output: list[dict[str, object]] = []
    for row in grouped.to_dict("records"):
        filed_po_box = normalize_po_box(row["address_line1"])
        filed_zip = zip5(row["zip"])
        candidates = []
        for parcel in parcel_rows.get(row["municipality"], []):
            if normalize_po_box(parcel.get("ADDRGL1")) != filed_po_box:
                continue
            if zip5(parcel.get("ZIPGL")) != filed_zip:
                continue
            if not owner_matches_donor(
                row["name"],
                parcel.get("OWNER1"),
                parcel.get("OWNER2"),
            ):
                continue
            candidates.append(parcel)

        if len(candidates) == 1:
            parcel = candidates[0]
            status = "matched"
            confidence = "high"
        elif len(candidates) > 1:
            parcel = candidates[0]
            status = "ambiguous"
            confidence = "review"
        else:
            parcel = {}
            status = "unmatched"
            confidence = ""

        output.append(
            {
                **row,
                "match_status": status,
                "match_confidence": confidence,
                "candidate_parcel_matches": len(candidates),
                "parcel_objectid": parcel.get("OBJECTID", ""),
                "parcel_span": parcel.get("SPAN", ""),
                "owner1": parcel.get("OWNER1", ""),
                "owner2": parcel.get("OWNER2", ""),
                "grand_list_mailing_address": parcel.get("ADDRGL1", ""),
                "grand_list_mailing_city": parcel.get("CITYGL", ""),
                "grand_list_mailing_state": parcel.get("STGL", ""),
                "grand_list_mailing_zip": parcel.get("ZIPGL", ""),
                "parcel_location": (
                    parcel.get("E911ADDR")
                    or parcel.get("PropertyLocationStreet")
                    or parcel.get("LOCAPROP")
                    or ""
                ),
                "parcel_location_city": parcel.get(
                    "PropertyLocationCity",
                    "",
                ),
                "latitude": parcel.get("latitude", ""),
                "longitude": parcel.get("longitude", ""),
                "source": "VTrans ROW Parcels MapServer/8",
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(output).to_csv(OUT, index=False)

    result = pd.DataFrame(output)
    matched = result[result["match_status"] == "matched"]
    print(f"wrote {OUT}")
    print(f"Windsor P.O. box groups: {len(result):,}")
    print(f"high-confidence inferred parcels: {len(matched):,}")
    print(f"inferred amount: ${matched['amount'].sum():,.2f}")


if __name__ == "__main__":
    main()
