from __future__ import annotations

import io
import json
import hashlib
import base64
import re
import sqlite3
from pathlib import Path

import requests

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

HERE = Path(__file__).resolve().parent
DB = HERE / "data" / "campaign_finance.sqlite"

VT_TOWNS_QUERY = (
    "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/"
    "FS_VCGI_OPENDATA_Boundary_BNDHASH_poly_towns_SP_v1/FeatureServer/0/query"
)
TOWN_ALIASES = HERE / "town_aliases.csv"
ADDRESS_GEOCODES = HERE / "data" / "windsor_address_geocodes.csv"
PO_BOX_INFERRED_PARCELS = (
    HERE / "data" / "windsor_po_box_inferred_parcels.csv"
)
TOWN_POPULATION_DENSITY = HERE / "data" / "vermont_town_population_density.csv"
TOWN_PRIMARY_TURNOUT = HERE / "data" / "vermont_primary_turnout_2024.csv"
TOWN_HOUSEHOLD_INCOME = HERE / "data" / "vermont_household_income_2024.csv"
OSCAR_ICON = HERE / "assets" / "oscar_baby_icon_rose_crop.png"
PO_BOX_RE = re.compile(
    r"(^|\b)(P\.?\s*O\.?|POST\s+OFFICE|PO)\s*BOX\b|^P\.?O\.?BOX\b",
    re.IGNORECASE,
)
CANDIDATE_GRADIENTS = [
    ("#ffe2df", "#c1121f"),
    ("#d9ecff", "#005f99"),
    ("#e4f7dd", "#2d7d46"),
    ("#fff1c7", "#b77900"),
    ("#eadcff", "#6a3bc2"),
    ("#d8f5f0", "#087f8c"),
    ("#ffe0ef", "#b5176f"),
    ("#e6e6e6", "#4b5563"),
]

st.set_page_config(
    page_title="OSCAR - Windsor County Campaign Finance",
    page_icon=str(OSCAR_ICON),
    layout="wide",
)

encoded_icon = base64.b64encode(OSCAR_ICON.read_bytes()).decode("ascii")
st.markdown(
    f"""
    <div style="
        display: flex;
        align-items: center;
        gap: 18px;
        margin: 0 0 0.75rem 0;
    ">
        <img src="data:image/png;base64,{encoded_icon}" alt="OSCAR baby icon"
            style="width: 96px; height: 96px; border-radius: 14px; flex: 0 0 auto;">
        <div style="min-width: 0;">
            <h1 style="margin: 0 0 0.25rem 0;">
                2026 Windsor County Campaign Finance
            </h1>
            <div style="color: rgba(250, 250, 250, 0.72); font-size: 0.95rem;">
                Open-Source Campaign Analytics for Representation
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(
    "Reported contributions to Vermont House and Senate candidates in districts touching Windsor County."
)

if not DB.exists():
    st.error(
        "The campaign finance database does not exist yet. "
        "Run `python -m ingest.run` first."
    )
    st.stop()

@st.cache_data(ttl=86400, show_spinner=False)
def load_vermont_towns():
    """Load official VCGI town polygons as GeoJSON."""
    params = {
        "where": "1=1",
        "outFields": "TOWNNAME,TOWNNAMEMC,TOWNGEOID,CNTY",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    response = requests.get(VT_TOWNS_QUERY, params=params, timeout=60)
    response.raise_for_status()
    geojson = response.json()

    for feature in geojson.get("features", []):
        props = feature.setdefault("properties", {})
        props["JOIN_NAME"] = normalize_place(
            props.get("TOWNNAME")
            or props.get("TOWNNAMEMC")
            or ""
        )
        props["TOWNGEOID"] = str(props.get("TOWNGEOID") or "")

    return geojson


@st.cache_data(show_spinner=False)
def load_town_aliases(path: str, modified_at: float):
    alias_path = Path(path)
    if not alias_path.exists():
        return {}

    aliases = pd.read_csv(alias_path).fillna("")
    if not {"reported_city", "municipality"}.issubset(aliases.columns):
        return {}

    normalized_aliases = {}
    for row in aliases.itertuples():
        reported_city = normalize_place(row.reported_city)
        municipality = normalize_place(row.municipality)
        if (
            reported_city
            and municipality
            and reported_city != municipality
        ):
            normalized_aliases[reported_city] = municipality

    return normalized_aliases


def normalize_place(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def normalize_address_part(value: str) -> str:
    return normalize_place(value)


def address_key(*parts: str) -> str:
    normalized = "|".join(normalize_address_part(part) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def raw_json_field(payload: str, field: str) -> str:
    if not payload:
        return ""
    try:
        value = json.loads(payload).get(field)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    return "" if value is None else str(value)


def is_physical_address(address_line1: str) -> bool:
    address = str(address_line1 or "").strip()
    return bool(address) and not PO_BOX_RE.search(address)


def is_po_box_address(address_line1: str) -> bool:
    return bool(PO_BOX_RE.search(str(address_line1 or "").strip()))


def summarize_values(values, limit: int = 6) -> str:
    cleaned = sorted(
        {
            str(value).strip()
            for value in values
            if str(value or "").strip()
        }
    )
    if len(cleaned) <= limit:
        return ", ".join(cleaned)
    shown = ", ".join(cleaned[:limit])
    return f"{shown}, +{len(cleaned) - limit} more"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in rgb)


def blend_hex(start: str, end: str, fraction: float) -> str:
    start_rgb = hex_to_rgb(start)
    end_rgb = hex_to_rgb(end)
    fraction = max(0.0, min(1.0, float(fraction or 0)))
    return rgb_to_hex(
        tuple(
            round(start_rgb[i] + (end_rgb[i] - start_rgb[i]) * fraction)
            for i in range(3)
        )
    )


def gradient_values(
    values: pd.Series,
    start: str,
    end: str,
) -> list[str]:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0)
    max_value = float(numeric.max()) if len(numeric) else 0.0
    if max_value <= 0:
        return [start for _ in numeric]
    return [
        blend_hex(start, end, value / max_value)
        for value in numeric
    ]


def scale_marker_sizes(
    values: pd.Series,
    minimum: float = 11,
    maximum: float = 34,
) -> list[float]:
    numeric = pd.to_numeric(values, errors="coerce").fillna(0)
    max_value = float(numeric.max()) if len(numeric) else 0.0
    if max_value <= 0:
        return [minimum for _ in numeric]
    return [
        minimum + (maximum - minimum) * (value / max_value) ** 0.5
        for value in numeric
    ]


def add_population_density_overlay(
    fig: go.Figure,
    vt_geojson: dict,
    density_frame: pd.DataFrame,
    show_scale: bool = True,
) -> None:
    if density_frame.empty:
        return

    fig.add_trace(
        go.Choroplethmap(
            geojson=vt_geojson,
            locations=density_frame["town_geoid"],
            z=density_frame["population_density_sqmi"],
            featureidkey="properties.TOWNGEOID",
            name="Population density",
            colorscale=[
                [0.0, "rgba(247, 249, 247, 0.35)"],
                [0.25, "rgba(205, 224, 211, 0.42)"],
                [0.55, "rgba(132, 178, 151, 0.46)"],
                [1.0, "rgba(52, 112, 82, 0.52)"],
            ],
            marker={
                "opacity": 0.38,
                "line": {
                    "color": "rgba(74, 85, 92, 0.85)",
                    "width": 1.05,
                },
            },
            customdata=density_frame[
                ["town", "population_2020", "land_sqmi"]
            ].to_numpy(),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "2020 population: %{customdata[1]:,}<br>"
                "Land area: %{customdata[2]:,.1f} sq mi<br>"
                "Density: %{z:,.0f} people/sq mi"
                "<extra></extra>"
            ),
            colorbar={
                "title": "People/sq mi",
                "tickformat": ",.0f",
            },
            showscale=show_scale,
        )
    )


@st.cache_data(show_spinner=False)
def load_windsor_address_geocodes(path: str, modified_at: float):
    geocode_path = Path(path)
    if not geocode_path.exists():
        return pd.DataFrame()

    geocodes = pd.read_csv(geocode_path).fillna("")
    for col in ["latitude", "longitude", "amount", "records"]:
        if col in geocodes.columns:
            geocodes[col] = pd.to_numeric(geocodes[col], errors="coerce")
    if "address_key" in geocodes.columns:
        geocodes = geocodes.drop_duplicates("address_key", keep="first")
    return geocodes


@st.cache_data(show_spinner=False)
def load_windsor_po_box_inferred_parcels(path: str, modified_at: float):
    inferred_path = Path(path)
    if not inferred_path.exists():
        return pd.DataFrame()

    inferred = pd.read_csv(inferred_path).fillna("")
    for col in [
        "latitude",
        "longitude",
        "amount",
        "records",
        "candidate_parcel_matches",
    ]:
        if col in inferred.columns:
            inferred[col] = pd.to_numeric(inferred[col], errors="coerce")
    if "po_box_key" in inferred.columns:
        inferred = inferred.drop_duplicates("po_box_key", keep="first")
    return inferred


@st.cache_data(show_spinner=False)
def load_town_population_density(path: str, modified_at: float):
    density_path = Path(path)
    if not density_path.exists():
        return pd.DataFrame()

    density = pd.read_csv(density_path, dtype={"town_geoid": str}).fillna("")
    for col in [
        "population_2020",
        "land_sqmi",
        "water_sqmi",
        "population_density_sqmi",
    ]:
        if col in density.columns:
            density[col] = pd.to_numeric(density[col], errors="coerce")
    return density


@st.cache_data(show_spinner=False)
def load_town_primary_turnout(path: str, modified_at: float):
    turnout_path = Path(path)
    if not turnout_path.exists():
        return pd.DataFrame()

    turnout = pd.read_csv(turnout_path, dtype={"town_geoid": str}).fillna("")
    for col in [
        "registered_voters_2024_primary",
        "primary_votes_cast_2024",
        "primary_turnout_pct_2024",
        "primary_absentee_votes_2024",
        "primary_absentee_pct_2024",
    ]:
        if col in turnout.columns:
            turnout[col] = pd.to_numeric(turnout[col], errors="coerce")
    return turnout


@st.cache_data(show_spinner=False)
def load_town_household_income(path: str, modified_at: float):
    income_path = Path(path)
    if not income_path.exists():
        return pd.DataFrame()

    income = pd.read_csv(income_path, dtype={"town_geoid": str}).fillna("")
    for col in [
        "median_household_income_2024",
        "median_household_income_moe_2024",
    ]:
        if col in income.columns:
            income[col] = pd.to_numeric(income[col], errors="coerce")
    return income


def attach_vermont_municipality(
    frame: pd.DataFrame,
    valid_towns: set[str],
    aliases: dict[str, str],
) -> pd.DataFrame:
    result = frame.copy()
    result["reported_city_normalized"] = (
        result["city"].fillna("").map(normalize_place)
    )

    def resolve(city: str) -> str:
        if not city:
            return ""
        if city in aliases:
            return aliases[city]
        if city in valid_towns:
            return city
        return ""

    result["municipality"] = result["reported_city_normalized"].map(resolve)
    return result


@st.cache_data(show_spinner=False)
def load_data(db_path: str):
    conn = sqlite3.connect(db_path)

    contrib = pd.read_sql_query(
        """
        SELECT
            t.roster_name,
            c.office,
            c.district,
            c.profile_status,
            c.verification_status,
            c.verified_name,
            t.transaction_date,
            t.amount,
            t.name,
            t.city,
            t.state,
            t.zip,
            t.subtype,
            t.report_name,
            t.election_cycle,
            t.transaction_id,
            t.transaction_guid,
            t.raw_json
        FROM transactions t
        LEFT JOIN candidates c ON c.roster_name = t.roster_name
        WHERE t.kind = 'contributions'
        """,
        conn,
    )

    status = pd.read_sql_query(
        """
        SELECT
            roster_name,
            office,
            district,
            profile_guid,
            profile_status,
            verification_status,
            verified_name,
            verification_reason
        FROM candidates
        ORDER BY office, district, roster_name
        """,
        conn,
    )

    conn.close()

    contrib["amount"] = pd.to_numeric(contrib["amount"], errors="coerce").fillna(0)
    contrib["transaction_date"] = pd.to_datetime(
        contrib["transaction_date"], errors="coerce"
    )
    for col in [
        "roster_name", "office", "district", "profile_status",
        "verification_status", "verified_name", "name", "city", "state",
        "zip", "subtype", "report_name", "election_cycle",
        "transaction_id", "transaction_guid", "raw_json"
    ]:
        if col in contrib.columns:
            contrib[col] = contrib[col].fillna("").astype(str)

    contrib["address_line1"] = contrib["raw_json"].map(
        lambda payload: raw_json_field(payload, "addressLine1")
    )
    contrib["address_line2"] = contrib["raw_json"].map(
        lambda payload: raw_json_field(payload, "addressLine2")
    )

    for col in status.columns:
        status[col] = status[col].fillna("").astype(str)

    return contrib, status

contrib, status = load_data(str(DB))

# ---------- Sidebar filters ----------
st.sidebar.header("Filters")

office_options = ["All"] + sorted(x for x in contrib["office"].unique() if x)
office = st.sidebar.selectbox("Office", office_options)

district_pool = contrib
if office != "All":
    district_pool = district_pool[district_pool["office"] == office]
district_options = ["All"] + sorted(x for x in district_pool["district"].unique() if x)
district = st.sidebar.selectbox("District", district_options)

candidate_pool = district_pool
if district != "All":
    candidate_pool = candidate_pool[candidate_pool["district"] == district]
candidate_options = ["All"] + sorted(
    x for x in candidate_pool["roster_name"].unique() if x
)
candidate = st.sidebar.selectbox("Candidate", candidate_options)

search = st.sidebar.text_input("Donor / city / state / ZIP search")
min_amount = st.sidebar.number_input(
    "Minimum contribution",
    min_value=0.0,
    value=0.0,
    step=25.0,
)

location_mode = st.sidebar.selectbox(
    "Location",
    ["All locations", "Vermont", "Outside Vermont", "Unreported"],
)

valid_dates = contrib["transaction_date"].dropna()
if len(valid_dates):
    min_date = valid_dates.min().date()
    max_date = valid_dates.max().date()
    date_range = st.sidebar.date_input(
        "Date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
else:
    date_range = ()

filtered = contrib.copy()

if office != "All":
    filtered = filtered[filtered["office"] == office]
if district != "All":
    filtered = filtered[filtered["district"] == district]
if candidate != "All":
    filtered = filtered[filtered["roster_name"] == candidate]
if min_amount:
    filtered = filtered[filtered["amount"] >= min_amount]

if location_mode == "Vermont":
    filtered = filtered[filtered["state"] == "VT"]
elif location_mode == "Outside Vermont":
    filtered = filtered[(filtered["state"] != "") & (filtered["state"] != "VT")]
elif location_mode == "Unreported":
    filtered = filtered[filtered["state"] == ""]

if search:
    q = search.strip().lower()
    haystack = (
        filtered["name"] + " " +
        filtered["city"] + " " +
        filtered["state"] + " " +
        filtered["zip"] + " " +
        filtered["roster_name"]
    ).str.lower()
    filtered = filtered[haystack.str.contains(q, na=False)]

if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    filtered = filtered[
        (filtered["transaction_date"] >= start) &
        (filtered["transaction_date"] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    ]

# ---------- KPIs ----------
total = float(filtered["amount"].sum())
count = len(filtered)
median = float(filtered["amount"].median()) if count else 0.0
vt_total = float(filtered.loc[filtered["state"] == "VT", "amount"].sum())
vt_share = (vt_total / total) if total else 0.0
candidate_count = filtered["roster_name"].nunique()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Reported contributions", f"${total:,.0f}")
c2.metric("Contribution records", f"{count:,}")
c3.metric("Median contribution", f"${median:,.0f}")
c4.metric("Vermont share", f"{vt_share:.0%}")
c5.metric("Candidates represented", f"{candidate_count:,}")

# ---------- Geography ----------
st.subheader("Windsor contribution point map")
geo_mode = st.radio(
    "Map view",
    [
        "Windsor address points",
        "Interactive Vermont map",
        "By state",
        "Vermont town table",
    ],
    horizontal=True,
)

if geo_mode == "By state":
    geo = filtered.copy()
    geo["geo_label"] = geo["state"].replace("", "Unreported")
    geo = (
        geo.groupby("geo_label", as_index=False)
        .agg(amount=("amount", "sum"), records=("amount", "size"))
        .sort_values("amount", ascending=False)
    )
    geo["share"] = (
        geo["amount"] / geo["amount"].sum()
        if geo["amount"].sum()
        else 0
    )

    g1, g2 = st.columns([1.3, 1])
    with g1:
        if len(geo):
            fig = px.bar(
                geo.head(25).sort_values("amount"),
                x="amount",
                y="geo_label",
                orientation="h",
                labels={
                    "amount": "Contribution dollars",
                    "geo_label": "State",
                },
            )
            fig.update_layout(
                height=560,
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig, width="stretch")
    with g2:
        st.dataframe(
            geo.rename(
                columns={
                    "geo_label": "State",
                    "amount": "Amount",
                    "records": "Records",
                    "share": "Share",
                }
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
                "Share": st.column_config.NumberColumn(format="%.1%%"),
            },
        )

else:
    try:
        vt_geojson = load_vermont_towns()
    except Exception as exc:
        st.error(f"Could not load Vermont municipal boundaries: {exc}")
        vt_geojson = {"type": "FeatureCollection", "features": []}

    valid_towns = {
        normalize_place(feature.get("properties", {}).get("JOIN_NAME", ""))
        for feature in vt_geojson.get("features", [])
        if normalize_place(feature.get("properties", {}).get("JOIN_NAME", ""))
    }
    windsor_towns = {
        normalize_place(feature.get("properties", {}).get("JOIN_NAME", ""))
        for feature in vt_geojson.get("features", [])
        if feature.get("properties", {}).get("CNTY") == 27
        and normalize_place(feature.get("properties", {}).get("JOIN_NAME", ""))
    }
    windsor_town_geoids = {
        str(feature.get("properties", {}).get("TOWNGEOID") or "")
        for feature in vt_geojson.get("features", [])
        if feature.get("properties", {}).get("CNTY") == 27
        and str(feature.get("properties", {}).get("TOWNGEOID") or "")
    }
    town_geoids = pd.DataFrame(
        [
            {
                "municipality": normalize_place(
                    feature.get("properties", {}).get("JOIN_NAME", "")
                ),
                "town_geoid": str(
                    feature.get("properties", {}).get("TOWNGEOID") or ""
                ),
            }
            for feature in vt_geojson.get("features", [])
            if normalize_place(
                feature.get("properties", {}).get("JOIN_NAME", "")
            )
        ]
    )
    alias_modified_at = (
        TOWN_ALIASES.stat().st_mtime
        if TOWN_ALIASES.exists()
        else 0.0
    )
    aliases = load_town_aliases(str(TOWN_ALIASES), alias_modified_at)
    density_modified_at = (
        TOWN_POPULATION_DENSITY.stat().st_mtime
        if TOWN_POPULATION_DENSITY.exists()
        else 0.0
    )
    town_density = load_town_population_density(
        str(TOWN_POPULATION_DENSITY),
        density_modified_at,
    )
    turnout_modified_at = (
        TOWN_PRIMARY_TURNOUT.stat().st_mtime
        if TOWN_PRIMARY_TURNOUT.exists()
        else 0.0
    )
    town_turnout = load_town_primary_turnout(
        str(TOWN_PRIMARY_TURNOUT),
        turnout_modified_at,
    )
    income_modified_at = (
        TOWN_HOUSEHOLD_INCOME.stat().st_mtime
        if TOWN_HOUSEHOLD_INCOME.exists()
        else 0.0
    )
    town_income = load_town_household_income(
        str(TOWN_HOUSEHOLD_INCOME),
        income_modified_at,
    )

    vt = filtered[filtered["state"] == "VT"].copy()
    vt = attach_vermont_municipality(vt, valid_towns, aliases)

    matched = vt[vt["municipality"] != ""].copy()
    unmatched = vt[vt["municipality"] == ""].copy()

    municipal = (
        matched.groupby("municipality", as_index=False)
        .agg(
            amount=("amount", "sum"),
            records=("amount", "size"),
            contributors=("name", "nunique"),
        )
        .sort_values("amount", ascending=False)
    )
    if len(municipal):
        municipal["share_of_mapped_vt"] = (
            municipal["amount"] / municipal["amount"].sum()
        )
        municipal["average_contribution"] = (
            municipal["amount"] / municipal["records"]
        )
        municipal["amount_rank"] = municipal["amount"].rank(
            method="dense",
            ascending=False,
        ).astype(int)
    else:
        municipal["share_of_mapped_vt"] = pd.Series(dtype=float)
        municipal["average_contribution"] = pd.Series(dtype=float)
        municipal["amount_rank"] = pd.Series(dtype=int)

    town_analysis = town_geoids.copy()
    town_analysis = town_analysis.merge(
        municipal,
        on="municipality",
        how="left",
    )
    if not town_density.empty:
        town_analysis = town_analysis.merge(
            town_density,
            on="town_geoid",
            how="left",
        )
    else:
        town_analysis["population_2020"] = 0
        town_analysis["land_sqmi"] = 0
        town_analysis["population_density_sqmi"] = 0
    if not town_turnout.empty:
        turnout_cols = [
            "town_geoid",
            "registered_voters_2024_primary",
            "primary_votes_cast_2024",
            "primary_turnout_pct_2024",
            "primary_absentee_votes_2024",
            "primary_absentee_pct_2024",
        ]
        town_analysis = town_analysis.merge(
            town_turnout[turnout_cols],
            on="town_geoid",
            how="left",
        )
    else:
        town_analysis["registered_voters_2024_primary"] = 0
        town_analysis["primary_votes_cast_2024"] = 0
        town_analysis["primary_turnout_pct_2024"] = 0
        town_analysis["primary_absentee_votes_2024"] = 0
        town_analysis["primary_absentee_pct_2024"] = 0
    if not town_income.empty:
        income_cols = [
            "town_geoid",
            "median_household_income_2024",
            "median_household_income_moe_2024",
        ]
        town_analysis = town_analysis.merge(
            town_income[income_cols],
            on="town_geoid",
            how="left",
        )
    else:
        town_analysis["median_household_income_2024"] = 0
        town_analysis["median_household_income_moe_2024"] = 0
    town_analysis[["amount", "records", "contributors"]] = (
        town_analysis[["amount", "records", "contributors"]].fillna(0)
    )
    for col in [
        "share_of_mapped_vt",
        "average_contribution",
        "population_2020",
        "land_sqmi",
        "population_density_sqmi",
        "registered_voters_2024_primary",
        "primary_votes_cast_2024",
        "primary_turnout_pct_2024",
        "primary_absentee_votes_2024",
        "primary_absentee_pct_2024",
        "median_household_income_2024",
        "median_household_income_moe_2024",
    ]:
        if col in town_analysis.columns:
            town_analysis[col] = town_analysis[col].fillna(0)
    town_analysis["amount_rank"] = (
        town_analysis["amount_rank"].fillna(0).astype(int)
    )
    town_analysis["contribution_dollars_per_capita"] = (
        town_analysis["amount"] / town_analysis["population_2020"]
    ).where(town_analysis["population_2020"] > 0, 0)
    town_analysis["contribution_records_per_1k"] = (
        town_analysis["records"] / town_analysis["population_2020"] * 1000
    ).where(town_analysis["population_2020"] > 0, 0)
    town_analysis["contribution_dollars_per_primary_voter"] = (
        town_analysis["amount"] / town_analysis["primary_votes_cast_2024"]
    ).where(town_analysis["primary_votes_cast_2024"] > 0, 0)
    town_analysis["contribution_records_per_1k_primary_voters"] = (
        town_analysis["records"]
        / town_analysis["primary_votes_cast_2024"]
        * 1000
    ).where(town_analysis["primary_votes_cast_2024"] > 0, 0)
    town_analysis["primary_turnout_pct_display"] = (
        town_analysis["primary_turnout_pct_2024"] * 100
    )
    town_analysis["primary_voter_money_share_of_income"] = (
        town_analysis["contribution_dollars_per_primary_voter"]
        / town_analysis["median_household_income_2024"]
    ).where(town_analysis["median_household_income_2024"] > 0, 0)
    town_analysis["per_capita_money_share_of_income"] = (
        town_analysis["contribution_dollars_per_capita"]
        / town_analysis["median_household_income_2024"]
    ).where(town_analysis["median_household_income_2024"] > 0, 0)
    town_analysis["per_capita_rank"] = (
        town_analysis["contribution_dollars_per_capita"]
        .rank(method="dense", ascending=False)
        .astype(int)
    )
    town_analysis["per_primary_voter_rank"] = (
        town_analysis["contribution_dollars_per_primary_voter"]
        .rank(method="dense", ascending=False)
        .astype(int)
    )

    mapped_amount = float(matched["amount"].sum())
    unmatched_amount = float(unmatched["amount"].sum())
    vt_amount = float(vt["amount"].sum())

    selected_town = "All towns"
    if geo_mode != "Windsor address points":
        m1, m2, m3 = st.columns(3)
        m1.metric("Mapped Vermont dollars", f"${mapped_amount:,.0f}")
        m2.metric("Unmatched Vermont dollars", f"${unmatched_amount:,.0f}")
        m3.metric(
            "Map coverage",
            f"{(mapped_amount / vt_amount if vt_amount else 0):.0%}",
        )

        town_options = ["All towns"] + sorted(valid_towns)
        selected_town = st.selectbox(
            "Inspect a Vermont municipality",
            town_options,
            help=(
                "The map uses the reported contributor city/town and an "
                "optional alias table. Select a municipality to inspect its "
                "records."
            ),
        )

    if geo_mode == "Interactive Vermont map":
        if len(municipal) and vt_geojson.get("features"):
            map_data = town_analysis.copy()

            map_metric_options = {
                "Total dollars": {
                    "column": "amount",
                    "label": "Contribution dollars",
                    "hover_format": ":$,.0f",
                    "tick_format": "$,.0f",
                },
                "Share of mapped Vermont dollars": {
                    "column": "share_of_mapped_vt",
                    "label": "Share of mapped VT",
                    "hover_format": ":.1%",
                    "tick_format": ".1%",
                },
                "Contribution records": {
                    "column": "records",
                    "label": "Contribution records",
                    "hover_format": ":,",
                    "tick_format": ",",
                },
                "Average contribution": {
                    "column": "average_contribution",
                    "label": "Average contribution",
                    "hover_format": ":$,.0f",
                    "tick_format": "$,.0f",
                },
                "Dollars per capita": {
                    "column": "contribution_dollars_per_capita",
                    "label": "Dollars per capita",
                    "hover_format": ":$,.2f",
                    "tick_format": "$,.2f",
                },
                "Records per 1,000 residents": {
                    "column": "contribution_records_per_1k",
                    "label": "Records per 1,000 residents",
                    "hover_format": ":,.1f",
                    "tick_format": ",.1f",
                },
                "Dollars per primary voter": {
                    "column": "contribution_dollars_per_primary_voter",
                    "label": "Dollars per primary voter",
                    "hover_format": ":$,.2f",
                    "tick_format": "$,.2f",
                },
                "Records per 1,000 primary voters": {
                    "column": "contribution_records_per_1k_primary_voters",
                    "label": "Records per 1,000 primary voters",
                    "hover_format": ":,.1f",
                    "tick_format": ",.1f",
                },
                "2024 primary turnout": {
                    "column": "primary_turnout_pct_2024",
                    "label": "2024 primary turnout",
                    "hover_format": ":.1%",
                    "tick_format": ".1%",
                },
                "2024 primary voters": {
                    "column": "primary_votes_cast_2024",
                    "label": "2024 primary votes",
                    "hover_format": ":,",
                    "tick_format": ",",
                },
                "Median household income": {
                    "column": "median_household_income_2024",
                    "label": "Median household income",
                    "hover_format": ":$,.0f",
                    "tick_format": "$,.0f",
                },
                "Income estimate MOE": {
                    "column": "median_household_income_moe_2024",
                    "label": "Income MOE",
                    "hover_format": ":$,.0f",
                    "tick_format": "$,.0f",
                },
                "Primary-voter money share of income": {
                    "column": "primary_voter_money_share_of_income",
                    "label": "$ per primary voter / income",
                    "hover_format": ":.2%",
                    "tick_format": ".2%",
                },
                "Population density": {
                    "column": "population_density_sqmi",
                    "label": "People per sq mi",
                    "hover_format": ":,.0f",
                    "tick_format": ",.0f",
                },
                "2020 population": {
                    "column": "population_2020",
                    "label": "2020 population",
                    "hover_format": ":,",
                    "tick_format": ",",
                },
            }
            map_metric = st.selectbox(
                "Map concentration metric",
                list(map_metric_options),
            )
            map_metric_config = map_metric_options[map_metric]
            map_color_column = map_metric_config["column"]
            map_color_label = map_metric_config["label"]
            map_hover_data = {
                "amount": ":$,.0f",
                "share_of_mapped_vt": ":.1%",
                "records": ":,",
                "contributors": ":,",
                "average_contribution": ":$,.0f",
                "amount_rank": ":,",
                "population_2020": ":,",
                "land_sqmi": ":,.1f",
                "population_density_sqmi": ":,.0f",
                "contribution_dollars_per_capita": ":$,.2f",
                "contribution_records_per_1k": ":,.1f",
                "registered_voters_2024_primary": ":,",
                "primary_votes_cast_2024": ":,",
                "primary_turnout_pct_2024": ":.1%",
                "primary_absentee_votes_2024": ":,",
                "primary_absentee_pct_2024": ":.1%",
                "contribution_dollars_per_primary_voter": ":$,.2f",
                "contribution_records_per_1k_primary_voters": ":,.1f",
                "median_household_income_2024": ":$,.0f",
                "median_household_income_moe_2024": ":$,.0f",
                "primary_voter_money_share_of_income": ":.2%",
                "per_capita_money_share_of_income": ":.2%",
                "per_capita_rank": ":,",
                "per_primary_voter_rank": ":,",
                "town_geoid": False,
                "municipality": False,
            }
            map_hover_data[map_color_column] = (
                map_metric_config["hover_format"]
            )

            fig = px.choropleth(
                map_data,
                geojson=vt_geojson,
                locations="municipality",
                featureidkey="properties.JOIN_NAME",
                color=map_color_column,
                color_continuous_scale=[
                    [0.0, "#f4f6f6"],
                    [0.08, "#e4ece9"],
                    [0.28, "#c5ddd2"],
                    [0.58, "#8dbfa5"],
                    [1.0, "#4f8f78"],
                ],
                hover_name="municipality",
                hover_data=map_hover_data,
                labels={map_color_column: map_color_label},
            )
            fig.update_traces(
                marker_line_color="#4f5d64",
                marker_line_width=0.95,
            )
            fig.update_geos(
                fitbounds="locations",
                visible=False,
                bgcolor="rgba(0,0,0,0)",
            )
            fig.update_layout(
                height=720,
                margin=dict(l=0, r=0, t=10, b=0),
                coloraxis_colorbar=dict(
                    title=map_color_label,
                    tickformat=map_metric_config["tick_format"],
                ),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No mapped Vermont contributions match the filters.")

    if geo_mode == "Windsor address points":
        geocode_modified_at = (
            ADDRESS_GEOCODES.stat().st_mtime
            if ADDRESS_GEOCODES.exists()
            else 0.0
        )
        geocodes = load_windsor_address_geocodes(
            str(ADDRESS_GEOCODES),
            geocode_modified_at,
        )

        if geocodes.empty:
            st.warning(
                "No Windsor address geocode cache exists yet. Run "
                "`python scripts/build_windsor_geocodes.py` to build it."
            )
        else:
            windsor_records = matched[
                matched["municipality"].isin(windsor_towns)
            ].copy()
            windsor_records["address_key"] = windsor_records.apply(
                lambda row: address_key(
                    row.get("address_line1", ""),
                    row.get("address_line2", ""),
                    row.get("city", ""),
                    row.get("state", ""),
                    row.get("zip", ""),
                ),
                axis=1,
            )
            physical_windsor_records = windsor_records[
                windsor_records["address_line1"].map(is_physical_address)
            ].copy()
            address_summary = (
                physical_windsor_records
                .groupby("address_key", as_index=False)
                .agg(
                    amount=("amount", "sum"),
                    records=("amount", "size"),
                    contributors=("name", "nunique"),
                    candidates=("roster_name", "nunique"),
                    contributor_names=(
                        "name",
                        lambda values: summarize_values(values),
                    ),
                    candidate_names=(
                        "roster_name",
                        lambda values: summarize_values(values),
                    ),
                    municipality=("municipality", "first"),
                    address=("address_line1", "first"),
                    city=("city", "first"),
                    state=("state", "first"),
                    zip=("zip", "first"),
                )
            )

            geocode_columns = [
                "address_key",
                "one_line_address",
                "matched_address",
                "geocode_status",
                "latitude",
                "longitude",
            ]
            address_summary = address_summary.merge(
                geocodes[geocode_columns],
                on="address_key",
                how="left",
            )
            for col in ["latitude", "longitude"]:
                address_summary[col] = pd.to_numeric(
                    address_summary[col],
                    errors="coerce",
                )

            address_points = address_summary[
                (address_summary["geocode_status"] == "matched")
                & address_summary["latitude"].notna()
                & address_summary["longitude"].notna()
            ].copy()
            unplaced_addresses = address_summary[
                ~address_summary["address_key"].isin(
                    address_points["address_key"]
                )
            ].copy()

            inferred_modified_at = (
                PO_BOX_INFERRED_PARCELS.stat().st_mtime
                if PO_BOX_INFERRED_PARCELS.exists()
                else 0.0
            )
            inferred_cache = load_windsor_po_box_inferred_parcels(
                str(PO_BOX_INFERRED_PARCELS),
                inferred_modified_at,
            )
            po_box_records = windsor_records[
                windsor_records["address_line1"].map(is_po_box_address)
            ].copy()
            if not po_box_records.empty:
                po_box_records["po_box_key"] = po_box_records.apply(
                    lambda row: address_key(
                        row.get("name", ""),
                        row.get("address_line1", ""),
                        row.get("city", ""),
                        row.get("state", ""),
                        row.get("zip", ""),
                        row.get("municipality", ""),
                    ),
                    axis=1,
                )
            if not inferred_cache.empty and not po_box_records.empty:
                po_box_summary = (
                    po_box_records.groupby("po_box_key", as_index=False)
                    .agg(
                        amount=("amount", "sum"),
                        records=("amount", "size"),
                        candidates=("roster_name", "nunique"),
                        candidate_names=(
                            "roster_name",
                            lambda values: summarize_values(values),
                        ),
                        name=("name", "first"),
                        filed_po_box=("address_line1", "first"),
                        city=("city", "first"),
                        state=("state", "first"),
                        zip=("zip", "first"),
                        municipality=("municipality", "first"),
                    )
                )
                inferred_points = po_box_summary.merge(
                    inferred_cache[
                        [
                            "po_box_key",
                            "match_status",
                            "match_confidence",
                            "candidate_parcel_matches",
                            "parcel_span",
                            "owner1",
                            "owner2",
                            "grand_list_mailing_address",
                            "parcel_location",
                            "parcel_location_city",
                            "latitude",
                            "longitude",
                            "source",
                        ]
                    ],
                    on="po_box_key",
                    how="left",
                )
                inferred_points = inferred_points[
                    (inferred_points["match_status"] == "matched")
                    & (inferred_points["match_confidence"] == "high")
                    & inferred_points["latitude"].notna()
                    & inferred_points["longitude"].notna()
                ].copy()
            else:
                inferred_points = pd.DataFrame()

            street_map_points = address_points.copy()
            if not street_map_points.empty:
                street_map_points["location_type"] = "Filed street address"
                street_map_points["display_address"] = (
                    street_map_points["one_line_address"]
                )

            inferred_map_points = inferred_points.copy()
            if not inferred_map_points.empty:
                inferred_map_points["location_type"] = (
                    "Inferred P.O. box parcel"
                )
                inferred_map_points["display_address"] = (
                    inferred_map_points["filed_po_box"].fillna("")
                    + ", "
                    + inferred_map_points["city"].fillna("")
                    + ", "
                    + inferred_map_points["state"].fillna("")
                    + " "
                    + inferred_map_points["zip"].fillna("")
                ).str.strip(", ")
                inferred_map_points["one_line_address"] = (
                    inferred_map_points["display_address"]
                )
                inferred_map_points["matched_address"] = (
                    inferred_map_points["parcel_location"]
                )
                inferred_map_points["contributors"] = 1
                inferred_map_points["contributor_names"] = (
                    inferred_map_points["name"]
                )

            combined_points = pd.concat(
                [street_map_points, inferred_map_points],
                ignore_index=True,
                sort=False,
            )

            windsor_total = float(windsor_records["amount"].sum())
            point_total = float(combined_points["amount"].sum())
            physical_total = float(address_summary["amount"].sum())

            p1, p2, p3 = st.columns(3)
            p1.metric("Windsor mapped dollars", f"${windsor_total:,.0f}")
            p2.metric("Best-location dollars", f"${point_total:,.0f}")
            p3.metric(
                "Point-location coverage",
                f"{(point_total / windsor_total if windsor_total else 0):.0%}",
            )

            color_by_candidate = False
            selected_point_candidates = []
            candidate_palette = {}

            if len(combined_points):
                combined_points = combined_points.sort_values(
                    "amount",
                    ascending=False,
                )
                show_density_overlay = st.toggle(
                    "Show town population density",
                    value=True,
                )
                windsor_density = pd.DataFrame()
                if show_density_overlay and not town_density.empty:
                    windsor_density = town_density[
                        town_density["town_geoid"].isin(windsor_town_geoids)
                    ].copy()
                color_by_candidate = st.toggle(
                    "Color Windsor points by candidate",
                    value=True,
                )
                candidate_scope_records = windsor_records.copy()
                if color_by_candidate:
                    candidate_scopes = (
                        windsor_records[
                            ["office", "district"]
                        ]
                        .drop_duplicates()
                        .sort_values(["office", "district"])
                    )
                    candidate_scope_options = [
                        f"{row.office} / {row.district}"
                        for row in candidate_scopes.itertuples()
                        if str(row.office).strip()
                        and str(row.district).strip()
                    ]
                    if office != "All" and district != "All":
                        default_candidate_scope = f"{office} / {district}"
                    elif "Senate / Windsor" in candidate_scope_options:
                        default_candidate_scope = "Senate / Windsor"
                    elif candidate_scope_options:
                        default_candidate_scope = candidate_scope_options[0]
                    else:
                        default_candidate_scope = ""

                    selected_candidate_scope = st.selectbox(
                        "Candidate district",
                        candidate_scope_options,
                        index=(
                            candidate_scope_options.index(
                                default_candidate_scope
                            )
                            if default_candidate_scope
                            in candidate_scope_options
                            else 0
                        ),
                    )
                    if selected_candidate_scope:
                        selected_office, selected_district = (
                            selected_candidate_scope.split(" / ", 1)
                        )
                        candidate_scope_records = (
                            windsor_records[
                                (
                                    windsor_records["office"]
                                    == selected_office
                                )
                                & (
                                    windsor_records["district"]
                                    == selected_district
                                )
                            ]
                            .copy()
                        )

                candidate_point_totals = (
                    candidate_scope_records.groupby(
                        "roster_name",
                        as_index=False,
                    )["amount"]
                    .sum()
                    .sort_values("amount", ascending=False)
                )
                candidate_point_options = (
                    candidate_point_totals["roster_name"].tolist()
                )
                selected_point_candidates = candidate_point_options
                if color_by_candidate:
                    selected_point_candidates = st.multiselect(
                        "Windsor candidates",
                        candidate_point_options,
                        default=candidate_point_options,
                    )
                    candidate_palette = {
                        candidate_name: CANDIDATE_GRADIENTS[
                            idx % len(CANDIDATE_GRADIENTS)
                        ]
                        for idx, candidate_name in enumerate(
                            selected_point_candidates
                        )
                    }

                if color_by_candidate:
                    candidate_records = candidate_scope_records[
                        candidate_scope_records["roster_name"].isin(
                            selected_point_candidates
                        )
                    ].copy()
                    candidate_records = candidate_records[
                        candidate_records["address_line1"].map(
                            is_physical_address
                        )
                    ].copy()
                    candidate_summary = (
                        candidate_records
                        .groupby(
                            ["address_key", "roster_name"],
                            as_index=False,
                        )
                        .agg(
                            amount=("amount", "sum"),
                            records=("amount", "size"),
                            contributors=("name", "nunique"),
                            contributor_names=(
                                "name",
                                lambda values: summarize_values(values),
                            ),
                            municipality=("municipality", "first"),
                            address=("address_line1", "first"),
                            city=("city", "first"),
                            state=("state", "first"),
                            zip=("zip", "first"),
                        )
                    )
                    candidate_summary = candidate_summary.merge(
                        geocodes[geocode_columns],
                        on="address_key",
                        how="left",
                    )
                    for col in ["latitude", "longitude"]:
                        candidate_summary[col] = pd.to_numeric(
                            candidate_summary[col],
                            errors="coerce",
                        )
                    candidate_points = candidate_summary[
                        (candidate_summary["geocode_status"] == "matched")
                        & candidate_summary["latitude"].notna()
                        & candidate_summary["longitude"].notna()
                    ].copy()
                    if len(candidate_points):
                        candidate_points["location_type"] = (
                            "Filed street address"
                        )
                        candidate_points["display_address"] = (
                            candidate_points["one_line_address"]
                        )

                    if not po_box_records.empty:
                        candidate_po_box_records = po_box_records[
                            po_box_records["roster_name"].isin(
                                selected_point_candidates
                            )
                        ].copy()
                    else:
                        candidate_po_box_records = pd.DataFrame()
                    if (
                        not candidate_po_box_records.empty
                        and not inferred_cache.empty
                    ):
                        candidate_po_box_summary = (
                            candidate_po_box_records.groupby(
                                ["po_box_key", "roster_name"],
                                as_index=False,
                            )
                            .agg(
                                amount=("amount", "sum"),
                                records=("amount", "size"),
                                contributors=("name", "nunique"),
                                contributor_names=(
                                    "name",
                                    lambda values: summarize_values(values),
                                ),
                                municipality=("municipality", "first"),
                                filed_po_box=("address_line1", "first"),
                                city=("city", "first"),
                                state=("state", "first"),
                                zip=("zip", "first"),
                            )
                        )
                        candidate_inferred_points = (
                            candidate_po_box_summary.merge(
                                inferred_cache[
                                    [
                                        "po_box_key",
                                        "match_status",
                                        "match_confidence",
                                        "parcel_location",
                                        "latitude",
                                        "longitude",
                                    ]
                                ],
                                on="po_box_key",
                                how="left",
                            )
                        )
                        candidate_inferred_points = (
                            candidate_inferred_points[
                                (
                                    candidate_inferred_points["match_status"]
                                    == "matched"
                                )
                                & (
                                    candidate_inferred_points[
                                        "match_confidence"
                                    ]
                                    == "high"
                                )
                                & candidate_inferred_points[
                                    "latitude"
                                ].notna()
                                & candidate_inferred_points[
                                    "longitude"
                                ].notna()
                            ]
                            .copy()
                        )
                        if len(candidate_inferred_points):
                            candidate_inferred_points["location_type"] = (
                                "Inferred P.O. box parcel"
                            )
                            candidate_inferred_points["display_address"] = (
                                candidate_inferred_points[
                                    "filed_po_box"
                                ].fillna("")
                                + ", "
                                + candidate_inferred_points["city"].fillna("")
                                + ", "
                                + candidate_inferred_points["state"].fillna("")
                                + " "
                                + candidate_inferred_points["zip"].fillna("")
                            ).str.strip(", ")
                            candidate_inferred_points["one_line_address"] = (
                                candidate_inferred_points["display_address"]
                            )
                            candidate_inferred_points["matched_address"] = (
                                candidate_inferred_points["parcel_location"]
                            )
                        candidate_points = pd.concat(
                            [candidate_points, candidate_inferred_points],
                            ignore_index=True,
                            sort=False,
                        )

                    point_fig = go.Figure()
                    add_population_density_overlay(
                        point_fig,
                        vt_geojson,
                        windsor_density,
                    )
                    for idx, candidate_name in enumerate(
                        selected_point_candidates
                    ):
                        candidate_points_for_trace = candidate_points[
                            candidate_points["roster_name"] == candidate_name
                        ].copy()
                        if not len(candidate_points_for_trace):
                            continue
                        start, end = candidate_palette[candidate_name]
                        candidate_points_for_trace["marker_color"] = (
                            gradient_values(
                                candidate_points_for_trace["amount"],
                                start,
                                end,
                            )
                        )
                        customdata = candidate_points_for_trace[
                            [
                                "one_line_address",
                                "matched_address",
                                "municipality",
                                "amount",
                                "records",
                                "contributors",
                                "contributor_names",
                                "roster_name",
                                "location_type",
                            ]
                        ].to_numpy()
                        point_fig.add_trace(
                            go.Scattermap(
                                lat=candidate_points_for_trace["latitude"],
                                lon=candidate_points_for_trace["longitude"],
                                mode="markers",
                                name=candidate_name,
                                customdata=customdata,
                                marker={
                                    "size": scale_marker_sizes(
                                        candidate_points_for_trace["amount"],
                                    ),
                                    "color": candidate_points_for_trace[
                                        "marker_color"
                                    ],
                                    "opacity": 0.9,
                                },
                                hovertemplate=(
                                    "<b>%{customdata[7]}</b><br>"
                                    "Location type: %{customdata[8]}<br>"
                                    "Filed address: %{customdata[0]}<br>"
                                    "Mapped location: %{customdata[1]}<br>"
                                    "Municipality: %{customdata[2]}<br>"
                                    "Amount: $%{customdata[3]:,.0f}<br>"
                                    "Records: %{customdata[4]:,}<br>"
                                    "Named contributors: %{customdata[5]:,}<br>"
                                    "Contributor names: %{customdata[6]}"
                                    "<extra></extra>"
                                ),
                            )
                        )
                    point_fig.update_layout(
                        height=720,
                        margin=dict(l=0, r=0, t=10, b=0),
                        map={
                            "style": "carto-positron",
                            "center": {"lat": 43.55, "lon": -72.55},
                            "zoom": 8.15,
                        },
                        legend=dict(
                            title="Candidate",
                            orientation="h",
                            yanchor="bottom",
                            y=0.01,
                            xanchor="left",
                            x=0.01,
                        ),
                    )
                else:
                    scatter_fig = px.scatter_map(
                        combined_points,
                        lat="latitude",
                        lon="longitude",
                        size="amount",
                        color="amount",
                        color_continuous_scale=[
                            [0.0, "#ffd166"],
                            [0.32, "#f8961e"],
                            [0.68, "#e85d04"],
                            [1.0, "#9d0208"],
                        ],
                        hover_name="municipality",
                        hover_data={
                            "location_type": True,
                            "display_address": True,
                            "matched_address": True,
                            "amount": ":$,.0f",
                            "records": ":,",
                            "contributors": ":,",
                            "contributor_names": True,
                            "candidates": ":,",
                            "candidate_names": True,
                            "latitude": False,
                            "longitude": False,
                        },
                        labels={
                            "amount": "Contribution dollars",
                            "location_type": "Location type",
                            "display_address": "Filed address",
                            "matched_address": "Mapped location",
                            "records": "Records",
                            "contributors": "Named contributors",
                            "contributor_names": "Contributor names",
                            "candidates": "Candidates",
                            "candidate_names": "Candidate names",
                        },
                        map_style="carto-positron",
                        center={"lat": 43.55, "lon": -72.55},
                        zoom=8.15,
                        size_max=34,
                        height=720,
                    )
                    scatter_fig.update_traces(
                        marker={
                            "opacity": 0.9,
                        },
                    )
                    scatter_fig.update_layout(
                        margin=dict(l=0, r=0, t=10, b=0),
                        coloraxis_colorbar=dict(
                            title="Contribution dollars",
                            tickformat="$,.0f",
                        ),
                    )
                    point_fig = go.Figure()
                    add_population_density_overlay(
                        point_fig,
                        vt_geojson,
                        windsor_density,
                    )
                    for trace in scatter_fig.data:
                        point_fig.add_trace(trace)
                    point_fig.update_layout(scatter_fig.layout)
                st.plotly_chart(point_fig, width="stretch")

                with st.expander(
                    f"Mapped Windsor point table "
                    f"({len(combined_points):,} locations)",
                    expanded=False,
                ):
                    st.dataframe(
                        combined_points[
                            [
                                "location_type",
                                "display_address",
                                "municipality",
                                "amount",
                                "records",
                                "contributors",
                                "contributor_names",
                                "candidates",
                                "candidate_names",
                                "matched_address",
                            ]
                        ].rename(
                            columns={
                                "location_type": "Location type",
                                "display_address": "Filed address",
                                "municipality": "Municipality",
                                "amount": "Amount",
                                "records": "Records",
                                "contributors": "Named contributors",
                                "contributor_names": "Contributor names",
                                "candidates": "Candidates",
                                "candidate_names": "Candidate names",
                                "matched_address": "Geocoder match",
                            }
                        ),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Amount":
                                st.column_config.NumberColumn(format="$%.2f"),
                        },
                    )
            else:
                st.info("No mapped Windsor point locations match the filters.")

            with st.expander(
                f"Unplaced Windsor physical addresses "
                f"({len(unplaced_addresses):,} groups)"
            ):
                if len(unplaced_addresses):
                    st.dataframe(
                        unplaced_addresses[
                            [
                                "address",
                                "city",
                                "state",
                                "zip",
                                "municipality",
                                "amount",
                                "records",
                            ]
                        ].rename(
                            columns={
                                "address": "Filed address",
                                "city": "City",
                                "state": "State",
                                "zip": "ZIP",
                                "municipality": "Municipality",
                                "amount": "Amount",
                                "records": "Records",
                            }
                        ),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Amount":
                                st.column_config.NumberColumn(format="$%.2f"),
                        },
                    )
                else:
                    st.success("All physical Windsor addresses were placed.")

            st.markdown("#### Town per-capita contribution analysis")
            windsor_per_capita = town_analysis[
                town_analysis["town_geoid"].isin(windsor_town_geoids)
            ].copy()
            ranked_windsor_per_capita = windsor_per_capita.sort_values(
                [
                    "contribution_dollars_per_capita",
                    "amount",
                    "population_2020",
                ],
                ascending=[False, False, False],
            )
            nonzero_windsor_per_capita = ranked_windsor_per_capita[
                ranked_windsor_per_capita["amount"] > 0
            ]
            lower_activity = windsor_per_capita[
                windsor_per_capita["population_2020"] > 0
            ].sort_values(
                [
                    "contribution_dollars_per_capita",
                    "amount",
                    "population_2020",
                ],
                ascending=[True, True, False],
            )
            zero_activity = lower_activity[lower_activity["amount"] == 0]
            if len(nonzero_windsor_per_capita):
                highest = nonzero_windsor_per_capita.iloc[0]
                lowest_nonzero = nonzero_windsor_per_capita.sort_values(
                    [
                        "contribution_dollars_per_capita",
                        "amount",
                        "population_2020",
                    ],
                    ascending=[True, True, False],
                ).iloc[0]
                st.caption(
                    f"Highest Windsor town per-capita giving: "
                    f"{highest['municipality'].title()} at "
                    f"USD {highest['contribution_dollars_per_capita']:,.2f} "
                    f"per resident. Lowest nonzero town: "
                    f"{lowest_nonzero['municipality'].title()} at "
                    f"USD "
                    f"{lowest_nonzero['contribution_dollars_per_capita']:,.2f} "
                    f"per resident. Towns with no mapped contributions: "
                    f"{len(zero_activity):,}."
                )
            a1, a2 = st.columns(2)
            with a1:
                st.markdown("##### Higher per-capita money")
                st.dataframe(
                    ranked_windsor_per_capita[
                        [
                            "municipality",
                            "amount",
                            "population_2020",
                            "contribution_dollars_per_capita",
                            "records",
                            "contribution_records_per_1k",
                        ]
                    ].rename(
                        columns={
                            "municipality": "Town",
                            "amount": "Amount",
                            "population_2020": "2020 population",
                            "contribution_dollars_per_capita": "$ per capita",
                            "records": "Records",
                            "contribution_records_per_1k":
                                "Records per 1k",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Amount":
                            st.column_config.NumberColumn(format="$%.2f"),
                        "$ per capita":
                            st.column_config.NumberColumn(format="$%.2f"),
                        "Records per 1k":
                            st.column_config.NumberColumn(format="%.1f"),
                    },
                )
            with a2:
                st.markdown("##### Lower per-capita money")
                st.dataframe(
                    lower_activity[
                        [
                            "municipality",
                            "amount",
                            "population_2020",
                            "contribution_dollars_per_capita",
                            "records",
                            "contribution_records_per_1k",
                        ]
                    ].rename(
                        columns={
                            "municipality": "Town",
                            "amount": "Amount",
                            "population_2020": "2020 population",
                            "contribution_dollars_per_capita": "$ per capita",
                            "records": "Records",
                            "contribution_records_per_1k":
                                "Records per 1k",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Amount":
                            st.column_config.NumberColumn(format="$%.2f"),
                        "$ per capita":
                            st.column_config.NumberColumn(format="$%.2f"),
                        "Records per 1k":
                            st.column_config.NumberColumn(format="%.1f"),
                    },
                )

            st.markdown("#### Town participation-normalized analysis")
            windsor_primary_money = windsor_per_capita[
                windsor_per_capita["primary_votes_cast_2024"] > 0
            ].copy()
            ranked_primary_money = windsor_primary_money.sort_values(
                [
                    "contribution_dollars_per_primary_voter",
                    "amount",
                    "primary_votes_cast_2024",
                ],
                ascending=[False, False, False],
            )
            nonzero_primary_money = ranked_primary_money[
                ranked_primary_money["amount"] > 0
            ]
            lower_primary_money = windsor_primary_money.sort_values(
                [
                    "contribution_dollars_per_primary_voter",
                    "amount",
                    "primary_votes_cast_2024",
                ],
                ascending=[True, True, False],
            )
            turnout_ranked = windsor_primary_money.sort_values(
                ["primary_turnout_pct_2024", "primary_votes_cast_2024"],
                ascending=[False, False],
            )
            if len(nonzero_primary_money) and len(turnout_ranked):
                highest_primary_money = nonzero_primary_money.iloc[0]
                lowest_nonzero_primary_money = (
                    nonzero_primary_money.sort_values(
                        [
                            "contribution_dollars_per_primary_voter",
                            "amount",
                            "primary_votes_cast_2024",
                        ],
                        ascending=[True, True, False],
                    ).iloc[0]
                )
                highest_turnout = turnout_ranked.iloc[0]
                lowest_turnout = turnout_ranked.iloc[-1]
                st.caption(
                    f"Highest Windsor town giving per 2024 primary voter: "
                    f"{highest_primary_money['municipality'].title()} at "
                    f"USD "
                    f"{highest_primary_money['contribution_dollars_per_primary_voter']:,.2f}. "
                    f"Lowest nonzero: "
                    f"{lowest_nonzero_primary_money['municipality'].title()} "
                    f"at USD "
                    f"{lowest_nonzero_primary_money['contribution_dollars_per_primary_voter']:,.2f}. "
                    f"Primary turnout ranged from "
                    f"{lowest_turnout['municipality'].title()} at "
                    f"{lowest_turnout['primary_turnout_pct_2024']:.1%} "
                    f"to {highest_turnout['municipality'].title()} at "
                    f"{highest_turnout['primary_turnout_pct_2024']:.1%}."
                )

            p1, p2 = st.columns(2)
            primary_columns = [
                "municipality",
                "amount",
                "primary_votes_cast_2024",
                "registered_voters_2024_primary",
                "primary_turnout_pct_display",
                "contribution_dollars_per_primary_voter",
                "records",
                "contribution_records_per_1k_primary_voters",
            ]
            primary_rename = {
                "municipality": "Town",
                "amount": "Amount",
                "primary_votes_cast_2024": "2024 primary votes",
                "registered_voters_2024_primary": "Registered voters",
                "primary_turnout_pct_display": "Primary turnout",
                "contribution_dollars_per_primary_voter":
                    "$ per primary voter",
                "records": "Records",
                "contribution_records_per_1k_primary_voters":
                    "Records per 1k primary voters",
            }
            primary_config = {
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
                "Primary turnout":
                    st.column_config.NumberColumn(format="%.1f%%"),
                "$ per primary voter":
                    st.column_config.NumberColumn(format="$%.2f"),
                "Records per 1k primary voters":
                    st.column_config.NumberColumn(format="%.1f"),
            }
            with p1:
                st.markdown("##### Higher money per primary voter")
                st.dataframe(
                    ranked_primary_money[primary_columns].rename(
                        columns=primary_rename
                    ),
                    width="stretch",
                    hide_index=True,
                    column_config=primary_config,
                )
            with p2:
                st.markdown("##### Lower money per primary voter")
                st.dataframe(
                    lower_primary_money[primary_columns].rename(
                        columns=primary_rename
                    ),
                    width="stretch",
                    hide_index=True,
                    column_config=primary_config,
                )

            st.markdown("#### Town household income context")
            windsor_income = windsor_per_capita[
                windsor_per_capita["median_household_income_2024"] > 0
            ].copy()
            if len(windsor_income):
                highest_income = windsor_income.sort_values(
                    "median_household_income_2024",
                    ascending=False,
                ).iloc[0]
                lowest_income = windsor_income.sort_values(
                    "median_household_income_2024",
                    ascending=True,
                ).iloc[0]
                st.caption(
                    f"ACS 2024 5-year median household income ranges from "
                    f"USD {lowest_income['median_household_income_2024']:,.0f} "
                    f"in {lowest_income['municipality'].title()} to USD "
                    f"{highest_income['median_household_income_2024']:,.0f} "
                    f"in {highest_income['municipality'].title()}. "
                    f"MOE is the ACS margin of error for the income estimate."
                )

                income_columns = [
                    "municipality",
                    "median_household_income_2024",
                    "median_household_income_moe_2024",
                    "population_2020",
                    "amount",
                    "contribution_dollars_per_primary_voter",
                    "primary_turnout_pct_display",
                ]
                income_rename = {
                    "municipality": "Town",
                    "median_household_income_2024": "Median household income",
                    "median_household_income_moe_2024": "Income MOE",
                    "population_2020": "2020 population",
                    "amount": "Amount",
                    "contribution_dollars_per_primary_voter":
                        "$ per primary voter",
                    "primary_turnout_pct_display": "Primary turnout",
                }
                income_config = {
                    "Median household income":
                        st.column_config.NumberColumn(format="$%.0f"),
                    "Income MOE":
                        st.column_config.NumberColumn(format="$%.0f"),
                    "2020 population":
                        st.column_config.NumberColumn(format="%.0f"),
                    "Amount":
                        st.column_config.NumberColumn(format="$%.2f"),
                    "$ per primary voter":
                        st.column_config.NumberColumn(format="$%.2f"),
                    "Primary turnout":
                        st.column_config.NumberColumn(format="%.1f%%"),
                }
                st.markdown("##### Windsor County towns")
                st.dataframe(
                    windsor_income.sort_values("municipality")[
                        income_columns
                    ].rename(columns=income_rename),
                    width="stretch",
                    hide_index=True,
                    column_config=income_config,
                )

    if selected_town != "All towns":
        town_records = matched[
            matched["municipality"] == selected_town
        ].copy()
        st.markdown(f"#### {selected_town.title()}")
        t1, t2, t3 = st.columns(3)
        t1.metric(
            "Contribution dollars",
            f"${town_records['amount'].sum():,.0f}",
        )
        t2.metric("Contribution records", f"{len(town_records):,}")
        t3.metric(
            "Candidates supported",
            f"{town_records['roster_name'].nunique():,}",
        )

        town_by_candidate = (
            town_records.groupby("roster_name", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
        )
        st.dataframe(
            town_by_candidate.rename(
                columns={
                    "roster_name": "Candidate",
                    "amount": "Amount",
                }
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

    if geo_mode == "Vermont town table":
        town_table = town_analysis.copy()
        town_table = town_table.sort_values(
            [
                "contribution_dollars_per_primary_voter",
                "contribution_dollars_per_capita",
                "amount",
                "municipality",
            ],
            ascending=[False, False, False, True],
        )

        town_table_display = town_table.rename(
            columns={
                "amount_rank": "Rank",
                "per_capita_rank": "Per-capita rank",
                "per_primary_voter_rank": "Primary-voter rank",
                "municipality": "Municipality",
                "amount": "Amount",
                "records": "Records",
                "contributors": "Named contributors",
                "share_of_mapped_vt": "Share of mapped VT",
                "average_contribution": "Average contribution",
                "population_2020": "2020 population",
                "population_density_sqmi": "People per sq mi",
                "contribution_dollars_per_capita": "$ per capita",
                "contribution_records_per_1k": "Records per 1k",
                "registered_voters_2024_primary": "Registered voters",
                "primary_votes_cast_2024": "2024 primary votes",
                "primary_turnout_pct_display": "2024 primary turnout",
                "contribution_dollars_per_primary_voter":
                    "$ per primary voter",
                "contribution_records_per_1k_primary_voters":
                    "Records per 1k primary voters",
                "median_household_income_2024": "Median household income",
                "median_household_income_moe_2024": "Income MOE",
            }
        )[
            [
                "Primary-voter rank",
                "Per-capita rank",
                "Rank",
                "Municipality",
                "Amount",
                "$ per primary voter",
                "$ per capita",
                "2024 primary votes",
                "Registered voters",
                "2024 primary turnout",
                "Median household income",
                "Income MOE",
                "2020 population",
                "People per sq mi",
                "Share of mapped VT",
                "Records",
                "Records per 1k primary voters",
                "Records per 1k",
                "Average contribution",
                "Named contributors",
            ]
        ]

        st.dataframe(
            town_table_display,
            width="stretch",
            hide_index=True,
            column_config={
                "Primary-voter rank":
                    st.column_config.NumberColumn(format="%d"),
                "Per-capita rank": st.column_config.NumberColumn(format="%d"),
                "Rank": st.column_config.NumberColumn(format="%d"),
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
                "$ per primary voter":
                    st.column_config.NumberColumn(format="$%.2f"),
                "$ per capita":
                    st.column_config.NumberColumn(format="$%.2f"),
                "2024 primary turnout":
                    st.column_config.NumberColumn(format="%.1f%%"),
                "Median household income":
                    st.column_config.NumberColumn(format="$%.0f"),
                "Income MOE":
                    st.column_config.NumberColumn(format="$%.0f"),
                "People per sq mi":
                    st.column_config.NumberColumn(format="%.0f"),
                "Share of mapped VT":
                    st.column_config.NumberColumn(format="%.1%%"),
                "Records per 1k primary voters":
                    st.column_config.NumberColumn(format="%.1f"),
                "Records per 1k":
                    st.column_config.NumberColumn(format="%.1f"),
                "Average contribution":
                    st.column_config.NumberColumn(format="$%.2f"),
            },
                )

    with st.expander(
        f"Unmatched Vermont location labels ({len(unmatched):,} records)"
    ):
        if len(unmatched):
            unmatched_summary = (
                unmatched.groupby(
                    "reported_city_normalized",
                    as_index=False,
                )
                .agg(
                    amount=("amount", "sum"),
                    records=("amount", "size"),
                )
                .sort_values("amount", ascending=False)
            )
            st.caption(
                "These reported city/place labels did not exactly match an "
                "official VCGI municipality and are not silently assigned. "
                "Add deliberate mappings to town_aliases.csv when appropriate."
            )
            st.dataframe(
                unmatched_summary.rename(
                    columns={
                        "reported_city_normalized": "Reported location",
                        "amount": "Amount",
                        "records": "Records",
                    }
                ),
                width="stretch",
                hide_index=True,
                column_config={
                    "Amount":
                        st.column_config.NumberColumn(format="$%.2f"),
                },
            )
        else:
            st.success("All Vermont location labels matched a municipality.")


# ---------- Overview charts ----------
st.subheader("Fundraising overview")
left, right = st.columns(2)

with left:
    st.markdown("#### Fundraising leaderboard")
    leaderboard = (
        filtered.groupby("roster_name", as_index=False)["amount"]
        .sum()
        .sort_values("amount", ascending=True)
    )
    if len(leaderboard):
        fig = px.bar(
            leaderboard.tail(20),
            x="amount",
            y="roster_name",
            orientation="h",
            labels={"amount": "Contribution dollars", "roster_name": "Candidate"},
        )
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No records match the current filters.")

with right:
    st.markdown("#### Fundraising over time")
    timeline = filtered.dropna(subset=["transaction_date"]).copy()
    timeline["month"] = timeline["transaction_date"].dt.to_period("M").astype(str)
    timeline = (
        timeline.groupby("month", as_index=False)["amount"]
        .sum()
        .sort_values("month")
    )
    if len(timeline):
        fig = px.line(
            timeline,
            x="month",
            y="amount",
            markers=True,
            labels={"month": "Month", "amount": "Contribution dollars"},
        )
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No dated records match the current filters.")


# ---------- Shared donors ----------
st.subheader("Shared donors across candidates")
named = filtered[filtered["name"].str.strip() != ""].copy()
shared = (
    named.groupby("name")
    .agg(
        total_amount=("amount", "sum"),
        candidate_count=("roster_name", "nunique"),
        candidates=("roster_name", lambda s: ", ".join(sorted(set(s)))),
    )
    .reset_index()
)
shared = shared[shared["candidate_count"] > 1].sort_values(
    ["candidate_count", "total_amount"], ascending=[False, False]
)

if len(shared):
    st.dataframe(
        shared.rename(
            columns={
                "name": "Contributor",
                "total_amount": "Amount",
                "candidate_count": "Candidates",
                "candidates": "Supported candidates",
            }
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
else:
    st.info("No shared named donors match the current filters.")

# ---------- Candidate comparison ----------
st.subheader("Candidate comparison")
all_candidates = sorted(contrib["roster_name"].dropna().unique())

cc1, cc2 = st.columns(2)
cand_a = cc1.selectbox("Candidate A", [""] + all_candidates, key="compare_a")
cand_b = cc2.selectbox("Candidate B", [""] + all_candidates, key="compare_b")

def candidate_stats(name: str):
    x = contrib[contrib["roster_name"] == name]
    total = x["amount"].sum()
    count = len(x)
    median = x["amount"].median() if count else 0
    average = x["amount"].mean() if count else 0
    vt = x.loc[x["state"] == "VT", "amount"].sum()
    return {
        "Total": total,
        "Records": count,
        "Average": average,
        "Median": median,
        "Vermont share": vt / total if total else 0,
    }

if cand_a and cand_b:
    a = candidate_stats(cand_a)
    b = candidate_stats(cand_b)
    comparison = pd.DataFrame(
        {
            "Metric": list(a.keys()),
            cand_a: list(a.values()),
            cand_b: list(b.values()),
        }
    )
    st.dataframe(comparison, width="stretch", hide_index=True)

# ---------- Verification ----------
with st.expander("Data verification status"):
    st.dataframe(
        status[
            [
                "roster_name",
                "office",
                "district",
                "profile_status",
                "verification_status",
                "verified_name",
                "verification_reason",
            ]
        ],
        width="stretch",
        hide_index=True,
    )

# ---------- Records ----------
st.subheader("Contribution records")
display_cols = [
    "transaction_date",
    "roster_name",
    "name",
    "city",
    "state",
    "zip",
    "subtype",
    "amount",
]
records = filtered[display_cols].sort_values(
    "transaction_date", ascending=False
).copy()

st.dataframe(
    records,
    width="stretch",
    hide_index=True,
    height=520,
    column_config={
        "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
        "transaction_date": st.column_config.DateColumn("Date"),
        "roster_name": "Candidate",
        "name": "Contributor",
        "city": "City",
        "state": "State",
        "zip": "ZIP",
        "subtype": "Type",
    },
)

csv_bytes = records.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download filtered contributions CSV",
    csv_bytes,
    file_name="filtered_contributions.csv",
    mime="text/csv",
)

st.caption(
    "The app uses contributor city/state/ZIP from public filings. "
    "Windsor point locations include filed street-address geocodes and "
    "high-confidence inferred P.O. box parcel matches where available."
)
