from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

from .api import PROFILE_API, request_json, unwrap

ALIASES = {
    "charles": {"charles", "charlie", "chuck"},
    "charlie": {"charles", "charlie", "chuck"},
    "william": {"william", "will", "bill", "billy"},
    "will": {"william", "will", "bill", "billy"},
    "james": {"james", "jim", "jimmy"},
    "jim": {"james", "jim", "jimmy"},
    "jimmy": {"james", "jim", "jimmy"},
    "michael": {"michael", "mike"},
    "mike": {"michael", "mike"},
    "robert": {"robert", "rob", "bob"},
    "john": {"john", "jon", "johnny"},
    "christopher": {"christopher", "chris"},
    "chris": {"christopher", "chris"},
    "elizabeth": {"elizabeth", "liz", "beth"},
    "diedre": {"diedre", "dee"},
    "dee": {"diedre", "dee"},
    "voranus": {"voranus", "vl"},
    "vl": {"voranus", "vl"},
}


def normalize(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return " ".join(value.split())


def split_name(value: str) -> list[str]:
    return [part for part in normalize(value).split() if part]


def first_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    return (
        b in ALIASES.get(a, {a})
        or a in ALIASES.get(b, {b})
    )


def verify_names(roster_name: str, api_name: str) -> tuple[bool, str]:
    roster = split_name(roster_name)
    api = split_name(api_name)

    if not roster or not api:
        return False, "Missing roster or API name"

    roster_first = roster[0]
    roster_last = roster[-1]

    if api[0] == roster_last and len(api) >= 2:
        api_last = api[0]
        api_first = api[1]
    else:
        api_last = api[-1]
        api_first = api[0]

    if api_last != roster_last:
        return False, f"Last name mismatch: {roster_last} vs {api_last}"

    if not first_compatible(roster_first, api_first):
        return False, f"First name mismatch: {roster_first} vs {api_first}"

    return True, ""


def verify_profile(
    session: requests.Session,
    row: dict[str, str],
) -> dict[str, Any]:
    guid = row.get("profile_guid", "").strip()

    if not guid:
        return {
            "verified": False,
            "status": "no_guid",
            "candidate_name_returned": "",
            "reason": "No profile GUID configured",
        }

    data = unwrap(
        request_json(
            session,
            PROFILE_API,
            {"filerRegistrationGuid": guid},
        )
    ) or {}

    api_name = (
        data.get("filerName")
        or data.get("candidateName")
        or data.get("fullName")
        or " ".join(
            value
            for value in [
                data.get("firstName"),
                data.get("middleName"),
                data.get("lastName"),
            ]
            if value
        )
    )

    ok, reason = verify_names(row["candidate"], api_name)

    return {
        "verified": ok,
        "status": "verified" if ok else "identity_mismatch",
        "candidate_name_returned": api_name,
        "reason": reason,
        "profile": data,
    }
