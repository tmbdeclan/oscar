from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .api import fetch_all
from .db import ensure_schema, store_candidate, store_records
from .verify import verify_profile

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "candidates.csv"
DATA_DIR = ROOT / "data"
RAW_DIR = ROOT / "raw_json"
DB = DATA_DIR / "campaign_finance.sqlite"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_candidates() -> list[dict[str, str]]:
    with ROSTER.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def safe_name(value: str) -> str:
    import re
    import unicodedata

    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def save_raw(
    row: dict[str, str],
    kind: str,
    records: list[dict],
    meta: dict,
) -> str:
    folder = RAW_DIR / safe_name(row["candidate"])
    folder.mkdir(parents=True, exist_ok=True)

    text = json.dumps(
        {"meta": meta, "records": records},
        ensure_ascii=False,
        indent=2,
    )
    path = folder / f"{kind}.json"
    path.write_text(text, encoding="utf-8")

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(delay: float = 0.5) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)

    roster = load_candidates()
    session = requests.Session()
    conn = sqlite3.connect(DB)
    ensure_schema(conn)

    run_started = now_utc()

    for index, row in enumerate(roster, 1):
        name = row["candidate"]
        print(f"[{index}/{len(roster)}] {name}")

        if row.get("profile_status") == "no_profile_found":
            verification = {
                "status": "no_profile_found",
                "candidate_name_returned": "",
                "reason": "No candidate profile/GUID found",
            }
            store_candidate(conn, row, verification, now_utc())
            for kind in ("contributions", "loans"):
                conn.execute(
                    "INSERT INTO ingestion_status VALUES(?,?,?,?,?,?,?,?)",
                    (
                        run_started,
                        name,
                        kind,
                        "not_queried",
                        0,
                        0,
                        0,
                        "No profile/GUID found",
                    ),
                )
            conn.commit()
            print("  no profile/GUID found; not queried")
            continue

        try:
            if row.get("profile_guid", "").strip():
                verification = verify_profile(session, row)
            else:
                verification = {
                    "verified": False,
                    "status": "name_fallback",
                    "candidate_name_returned": "",
                    "reason": "No GUID; using name fallback",
                }
        except Exception as exc:
            verification = {
                "verified": False,
                "status": "verification_error",
                "candidate_name_returned": "",
                "reason": str(exc),
            }

        store_candidate(conn, row, verification, now_utc())
        conn.commit()

        if (
            row.get("profile_guid", "").strip()
            and not verification.get("verified")
        ):
            for kind in ("contributions", "loans"):
                conn.execute(
                    "INSERT INTO ingestion_status VALUES(?,?,?,?,?,?,?,?)",
                    (
                        run_started,
                        name,
                        kind,
                        "identity_not_verified",
                        0,
                        0,
                        0,
                        verification.get("reason", ""),
                    ),
                )
            conn.commit()
            print(
                "  identity not verified:",
                verification.get("reason", ""),
            )
            continue

        for kind, loan_only in (
            ("contributions", False),
            ("loans", True),
        ):
            try:
                records, meta = fetch_all(
                    session,
                    row,
                    loan_only=loan_only,
                    delay=delay,
                )
                save_raw(row, kind, records, meta)
                store_records(conn, row, kind, records)

                status = (
                    "ok"
                    if meta["complete"]
                    else "pagination_incomplete"
                )

                conn.execute(
                    "INSERT INTO ingestion_status VALUES(?,?,?,?,?,?,?,?)",
                    (
                        run_started,
                        name,
                        kind,
                        status,
                        len(records),
                        len(meta["pages"]),
                        1 if meta["complete"] else 0,
                        "",
                    ),
                )
                conn.commit()

                print(
                    f"  {kind}: {len(records)} records "
                    f"({len(meta['pages'])} page(s))"
                )
            except Exception as exc:
                conn.execute(
                    "INSERT INTO ingestion_status VALUES(?,?,?,?,?,?,?,?)",
                    (
                        run_started,
                        name,
                        kind,
                        "api_error",
                        0,
                        0,
                        0,
                        str(exc),
                    ),
                )
                conn.commit()
                print(f"  {kind}: ERROR {exc}")

        time.sleep(delay)

    conn.close()
    print(f"\nDone. Database: {DB}")


if __name__ == "__main__":
    run()
