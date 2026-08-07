from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS candidates(
      roster_name TEXT PRIMARY KEY,
      office TEXT,
      district TEXT,
      profile_guid TEXT,
      profile_status TEXT,
      verification_status TEXT,
      verified_name TEXT,
      verification_reason TEXT,
      last_verified_at TEXT
    );

    CREATE TABLE IF NOT EXISTS transactions(
      roster_name TEXT,
      kind TEXT,
      transaction_id TEXT,
      transaction_version_id TEXT,
      transaction_guid TEXT,
      transaction_date TEXT,
      amount REAL,
      name TEXT,
      city TEXT,
      state TEXT,
      zip TEXT,
      subtype TEXT,
      report_name TEXT,
      election_cycle TEXT,
      raw_json TEXT,
      UNIQUE(
        roster_name,
        kind,
        transaction_id,
        transaction_version_id,
        transaction_guid
      )
    );

    CREATE TABLE IF NOT EXISTS ingestion_status(
      run_started_at TEXT,
      roster_name TEXT,
      kind TEXT,
      status TEXT,
      record_count INTEGER,
      pages INTEGER,
      complete INTEGER,
      error TEXT
    );
    """)


def store_candidate(
    conn: sqlite3.Connection,
    row: dict[str, str],
    verification: dict,
    verified_at: str,
) -> None:
    conn.execute("""
    INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?)
    ON CONFLICT(roster_name) DO UPDATE SET
      office=excluded.office,
      district=excluded.district,
      profile_guid=excluded.profile_guid,
      profile_status=excluded.profile_status,
      verification_status=excluded.verification_status,
      verified_name=excluded.verified_name,
      verification_reason=excluded.verification_reason,
      last_verified_at=excluded.last_verified_at
    """, (
        row["candidate"],
        row["office"],
        row["district"],
        row.get("profile_guid", ""),
        row.get("profile_status", ""),
        verification.get("status", ""),
        verification.get("candidate_name_returned", ""),
        verification.get("reason", ""),
        verified_at,
    ))


def store_records(
    conn: sqlite3.Connection,
    row: dict[str, str],
    kind: str,
    records: list[dict],
) -> None:
    for record in records:
        name = (
            record.get("sourceName")
            or record.get("sourceFirstMiddleLastName")
            or ""
        )
        amount = pd.to_numeric(
            record.get("transactionAmount"),
            errors="coerce",
        )

        conn.execute("""
        INSERT OR REPLACE INTO transactions VALUES(
          ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """, (
            row["candidate"],
            kind,
            record.get("transactionID"),
            record.get("transactionVersionID"),
            record.get("guid"),
            record.get("transactionDate"),
            amount,
            name,
            record.get("city"),
            record.get("stateCode"),
            record.get("zipCode"),
            record.get("transactionSubTypeDescription"),
            record.get("reportName"),
            record.get("electionCycle"),
            json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ))
