from __future__ import annotations

import argparse
import csv
import re
import tempfile
from collections import defaultdict
from pathlib import Path

import requests
from pypdf import PdfReader


HERE = Path(__file__).resolve().parents[1]
TOWN_DENSITY = HERE / "data" / "vermont_town_population_density.csv"
OUTPUT = HERE / "data" / "vermont_primary_turnout_2024.csv"
PRIMARY_TURNOUT_URL = (
    "https://outside.vermont.gov/dept/sos/Elections_Division/"
    "election_info_resources/elections_results_data/"
    "2024_primary_election_voter_turnout.pdf"
)
SOURCE_LABEL = "Vermont SOS 2024 August Primary Voter Turnout"


def normalize_text(value: str) -> str:
    value = value.upper().replace("&", " AND ")
    value = re.sub(r"\bST[.]?\b", "SAINT", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return " ".join(value.split())


def parse_int(value: str) -> int:
    return int(str(value).replace(",", ""))


def fetch_pdf(url: str) -> Path:
    response = requests.get(url, timeout=90)
    response.raise_for_status()

    temporary = tempfile.NamedTemporaryFile(
        suffix=".pdf",
        prefix="vermont_primary_turnout_",
        delete=False,
    )
    with temporary:
        temporary.write(response.content)
    return Path(temporary.name)


def load_towns() -> list[dict[str, str]]:
    with TOWN_DENSITY.open(newline="", encoding="utf-8") as file:
        towns = list(csv.DictReader(file))

    for town in towns:
        town["town_normalized"] = normalize_text(town["town"])

    return sorted(
        towns,
        key=lambda item: len(item["town_normalized"]),
        reverse=True,
    )


def town_for_label(label: str, towns: list[dict[str, str]]):
    normalized_label = normalize_text(label)
    if not normalized_label:
        return None

    for town in towns:
        town_name = town["town_normalized"]
        if normalized_label == town_name:
            return town
        if normalized_label.startswith(f"{town_name} "):
            return town
    return None


def extract_turnout_rows(pdf_path: Path) -> list[dict[str, object]]:
    towns = load_towns()
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = re.sub(
        r"Page \d+ of \d+Office.*?\d{2}/\d{2}/\d{4}",
        " ",
        text,
    )

    row_pattern = re.compile(
        r"(?P<registered>\d[\d,]*)\s+"
        r"(?P<voted>\d[\d,]*)\s+"
        r"(?P<absentee>\d[\d,]*)\s+"
        r"(?P<turnout>\d+\.\d+)%"
        r"(?P<label>.*?)"
        r"(?P<absentee_pct>\d+\.\d+)%",
        re.S,
    )

    aggregated = defaultdict(
        lambda: {
            "registered_voters_2024_primary": 0,
            "primary_votes_cast_2024": 0,
            "primary_absentee_votes_2024": 0,
            "town": "",
            "county": "",
        }
    )

    for match in row_pattern.finditer(text):
        label = " ".join(match.group("label").split())
        town = town_for_label(label, towns)
        if not town:
            continue

        bucket = aggregated[town["town_geoid"]]
        bucket["town"] = town["town"]
        bucket["county"] = town["county"]
        bucket["registered_voters_2024_primary"] += parse_int(
            match.group("registered")
        )
        bucket["primary_votes_cast_2024"] += parse_int(match.group("voted"))
        bucket["primary_absentee_votes_2024"] += parse_int(
            match.group("absentee")
        )

    rows = []
    for geoid, values in aggregated.items():
        registered = values["registered_voters_2024_primary"]
        votes = values["primary_votes_cast_2024"]
        absentee = values["primary_absentee_votes_2024"]
        rows.append(
            {
                "town_geoid": geoid,
                "town": values["town"],
                "county": values["county"],
                "registered_voters_2024_primary": registered,
                "primary_votes_cast_2024": votes,
                "primary_turnout_pct_2024": (
                    round(votes / registered, 4) if registered else 0
                ),
                "primary_absentee_votes_2024": absentee,
                "primary_absentee_pct_2024": (
                    round(absentee / votes, 4) if votes else 0
                ),
                "source": SOURCE_LABEL,
            }
        )

    return sorted(rows, key=lambda item: (item["county"], item["town"]))


def write_rows(rows: list[dict[str, object]]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pdf",
        type=Path,
        help="Use a previously downloaded 2024 primary turnout PDF.",
    )
    args = parser.parse_args()

    pdf_path = args.pdf if args.pdf else fetch_pdf(PRIMARY_TURNOUT_URL)
    rows = extract_turnout_rows(pdf_path)
    write_rows(rows)
    print(f"Wrote {len(rows):,} town primary turnout rows to {OUTPUT}")


if __name__ == "__main__":
    main()
