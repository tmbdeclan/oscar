from __future__ import annotations

import time
from typing import Any

import requests

API_BASE = "https://api.campaignfinance.vermont.gov/api"
PROFILE_API = f"{API_BASE}/PublicFilerDetails/GetFilerDetailsById"
CONTRIB_API = f"{API_BASE}/PublicTransactionDetails/GetContributionsDetails"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://campaignfinance.vermont.gov",
    "Referer": "https://campaignfinance.vermont.gov/",
    "User-Agent": "Mozilla/5.0 Vermont campaign finance public-data research",
}

PAGE_SIZE = 100


def request_json(
    session: requests.Session,
    url: str,
    payload: dict[str, Any],
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = session.post(
                url,
                headers=HEADERS,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            body = response.json()

            if isinstance(body, dict) and body.get("succeeded") is False:
                raise RuntimeError(body.get("error") or "API reported failure")

            return body
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(attempt * 2)

    raise RuntimeError(str(last_error))


def unwrap(body: dict[str, Any]) -> Any:
    if isinstance(body, dict):
        return body.get("data", body)
    return body


def contribution_payload(
    row: dict[str, str],
    page: int,
    loan_only: bool = False,
) -> dict[str, Any]:
    guid = row.get("profile_guid", "").strip()
    official = row.get("official_filer_name", "").strip()

    return {
        "pageNumber": page,
        "pageSize": PAGE_SIZE,
        "sortBy": "TransactionDate",
        "sortType": "desc",
        "transactionTypeCode": "TCON",
        "filerName": official or row["candidate"],
        "sourceName": "",
        "transactionAmountMax": None,
        "transactionAmountMin": None,
        "sourceTypeCode": "",
        "committeeType": "",
        "transactionSubTypeCode": "TLOAN" if loan_only else "ITMY,INKIND,TLOAN",
        "reportName": "",
        "toDate": None,
        "fromDate": None,
        "byState": None,
        "electionID": "",
        "electionYear": None if guid else 2026,
        "filingYear": None,
        "officeSought": "",
        "officeType": "",
        "filerRegistrationGuid": guid or None,
    }


def fetch_all(
    session: requests.Session,
    row: dict[str, str],
    *,
    loan_only: bool,
    delay: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    pages: list[dict[str, int]] = []
    page = 1

    while True:
        body = request_json(
            session,
            CONTRIB_API,
            contribution_payload(row, page, loan_only),
        )
        data = unwrap(body) or {}
        items = data.get("items") or []
        total = int(
            data.get("totalItems")
            or data.get("totalCount")
            or data.get("totalRows")
            or 0
        )

        pages.append(
            {"page": page, "count": len(items), "reported_total": total}
        )
        all_items.extend(items)

        if not items:
            break
        if total and len(all_items) >= total:
            break
        if len(items) < PAGE_SIZE:
            break

        page += 1
        time.sleep(delay)

    seen: set[tuple] = set()
    deduped: list[dict[str, Any]] = []

    for item in all_items:
        key = (
            item.get("transactionID"),
            item.get("transactionVersionID"),
            item.get("guid"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    reported = max((p["reported_total"] for p in pages), default=0)
    complete = (
        pages[-1]["count"] < PAGE_SIZE
        or (reported > 0 and len(deduped) >= reported)
    )

    return deduped, {
        "pages": pages,
        "raw_count": len(all_items),
        "deduped_count": len(deduped),
        "reported_total": reported,
        "complete": bool(complete),
    }
