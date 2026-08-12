from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BASE_URL = "https://static.electionresults.vermont.gov"
ELECTIONS_URL = f"{BASE_URL}/elections/elections.json"
RESULTS_CSV = DATA / "vermont_primary_results_2026.csv"
TURNOUT_CSV = DATA / "vermont_primary_turnout_2026.csv"


def normalize_place(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def get_json(url: str) -> dict | list:
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def static_url(path: str) -> str:
    return f"{BASE_URL}/{path.replace(chr(92), '/')}"


def pick_2026_primary(elections: list[dict]) -> dict:
    candidates = [
        election
        for election in elections
        if election.get("electionYear") == 2026
        and election.get("electionTypeCode") == "P"
        and election.get("electionCategoryCode") == "S"
    ]
    if not candidates:
        raise RuntimeError("Could not find the 2026 statewide primary election")
    defaults = [election for election in candidates if election.get("isDefault")]
    return (defaults or candidates)[0]


def load_town_geoids() -> dict[str, str]:
    density_path = DATA / "vermont_town_population_density.csv"
    with density_path.open(newline="") as handle:
        return {
            normalize_place(row["town"]): row["town_geoid"]
            for row in csv.DictReader(handle)
        }


def load_windsor_town_ids(manifest: dict) -> set[int]:
    return {
        int(row["townId"])
        for row in manifest.get("townDistricts", [])
        if row.get("countyName") == "WINDSOR" and row.get("townId")
    }


def result_rows(
    label: str,
    payload: dict,
    town_geoids: dict[str, str],
    windsor_town_ids: set[int],
) -> list[dict]:
    rows = []
    for party in payload.get("d", []):
        party_name = party.get("pn", "")
        party_code = party.get("pc", "")
        for office in party.get("o", []):
            office_name = office.get("on", "")
            district_code = office.get("dc", "")
            district_name = office.get("dn", "")
            for town_summary in office.get("cs", []):
                town_id = int(town_summary.get("tid") or 0)
                if town_id == 0 or town_id not in windsor_town_ids:
                    continue
                town = normalize_place(town_summary.get("tn", ""))
                for candidate in town_summary.get("rc", []):
                    rows.append(
                        {
                            "town_geoid": town_geoids.get(town, ""),
                            "municipality": town,
                            "office": office_name,
                            "office_group": label,
                            "district": district_name,
                            "district_code": district_code,
                            "party": party_name,
                            "party_code": party_code,
                            "candidate": candidate.get("cn", ""),
                            "candidate_id": candidate.get("cid", ""),
                            "votes": int(candidate.get("vc") or 0),
                            "is_write_in": candidate.get("isWriteIn", False),
                            "is_winner": candidate.get("isWinner", False),
                        }
                    )
    return rows


def turnout_rows(
    payload: dict,
    town_geoids: dict[str, str],
    windsor_town_ids: set[int],
) -> list[dict]:
    rows = []
    for row in payload.get("d", []):
        town_id = int(row.get("tid") or 0)
        if town_id == 0 or town_id not in windsor_town_ids:
            continue
        town = normalize_place(row.get("tn", ""))
        registered = int(row.get("tvr") or 0)
        votes_cast = int(row.get("tvc") or 0)
        rows.append(
            {
                "town_geoid": town_geoids.get(town, ""),
                "municipality": town,
                "registered_voters_2026_primary": registered,
                "primary_votes_cast_2026": votes_cast,
                "primary_turnout_pct_2026": (
                    votes_cast / registered if registered else 0
                ),
                "primary_absentee_votes_2026": int(row.get("tabs") or 0),
                "districts_reporting_2026": int(row.get("tdisr") or 0),
                "districts_total_2026": int(row.get("tdis") or 0),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    election = pick_2026_primary(get_json(ELECTIONS_URL))
    manifest = get_json(static_url(f"elections/{election['electionGuid']}.json"))
    town_geoids = load_town_geoids()
    windsor_town_ids = load_windsor_town_ids(manifest)

    result_data = []
    for label, key in [
        ("Federal", "federal"),
        ("Statewide", "stateWide"),
        ("Senate", "senate"),
        ("House", "house"),
        ("County", "county"),
    ]:
        config = manifest.get(key, {})
        if config.get("isEnable") and config.get("path"):
            result_data.extend(
                result_rows(
                    label,
                    get_json(static_url(config["path"])),
                    town_geoids,
                    windsor_town_ids,
                )
            )

    turnout_config = manifest.get("turnOut", {})
    turnout_data = []
    if turnout_config.get("isEnable") and turnout_config.get("path"):
        turnout_data = turnout_rows(
            get_json(static_url(turnout_config["path"])),
            town_geoids,
            windsor_town_ids,
        )

    write_csv(
        RESULTS_CSV,
        result_data,
        [
            "town_geoid",
            "municipality",
            "office",
            "office_group",
            "district",
            "district_code",
            "party",
            "party_code",
            "candidate",
            "candidate_id",
            "votes",
            "is_write_in",
            "is_winner",
        ],
    )
    write_csv(
        TURNOUT_CSV,
        turnout_data,
        [
            "town_geoid",
            "municipality",
            "registered_voters_2026_primary",
            "primary_votes_cast_2026",
            "primary_turnout_pct_2026",
            "primary_absentee_votes_2026",
            "districts_reporting_2026",
            "districts_total_2026",
        ],
    )

    print(
        f"Fetched {len(result_data):,} Windsor result rows and "
        f"{len(turnout_data):,} Windsor turnout rows from "
        f"{election['electionDateWithName']}."
    )
    print(f"Election last updated: {manifest.get('lastUpdatedDate')}")
    print(f"Towns reporting: {manifest.get('townsReportingFormat')}")


if __name__ == "__main__":
    main()
