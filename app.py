from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import requests

import pandas as pd
import plotly.express as px
import streamlit as st

HERE = Path(__file__).resolve().parent
DB = HERE / "data" / "campaign_finance.sqlite"

VT_TOWNS_QUERY = (
    "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/"
    "FS_VCGI_OPENDATA_Boundary_BNDHASH_poly_towns_SP_v1/FeatureServer/0/query"
)
TOWN_ALIASES = HERE / "town_aliases.csv"

st.set_page_config(
    page_title="Windsor County Campaign Finance",
    page_icon="🗳️",
    layout="wide",
)

st.title("2026 Windsor County Campaign Finance")
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
        "outFields": "TOWNNAME,TOWNNAMEMC,TOWNGEOID",
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

    return geojson


@st.cache_data(show_spinner=False)
def load_town_aliases(path: str):
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
            t.transaction_guid
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
        "transaction_id", "transaction_guid"
    ]:
        if col in contrib.columns:
            contrib[col] = contrib[col].fillna("").astype(str)

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

# ---------- Overview charts ----------
left, right = st.columns(2)

with left:
    st.subheader("Fundraising leaderboard")
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
    st.subheader("Fundraising over time")
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

# ---------- Geography ----------
st.subheader("Geographic breakdown")
geo_mode = st.radio(
    "Geographic view",
    ["Interactive Vermont map", "By state", "Vermont town table"],
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
    aliases = load_town_aliases(str(TOWN_ALIASES))

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
    else:
        municipal["share_of_mapped_vt"] = pd.Series(dtype=float)

    mapped_amount = float(matched["amount"].sum())
    unmatched_amount = float(unmatched["amount"].sum())
    vt_amount = float(vt["amount"].sum())

    m1, m2, m3 = st.columns(3)
    m1.metric("Mapped Vermont dollars", f"${mapped_amount:,.0f}")
    m2.metric("Unmatched Vermont dollars", f"${unmatched_amount:,.0f}")
    m3.metric(
        "Map coverage",
        f"{(mapped_amount / vt_amount if vt_amount else 0):.0%}",
    )

    town_options = ["All mapped towns"] + municipal["municipality"].tolist()
    selected_town = st.selectbox(
        "Inspect a Vermont municipality",
        town_options,
        help=(
            "The map uses the reported contributor city/town and an optional "
            "alias table. Select a municipality to inspect its records."
        ),
    )

    if geo_mode == "Interactive Vermont map":
        if len(municipal) and vt_geojson.get("features"):
            map_towns = pd.DataFrame(
                {"municipality": sorted(valid_towns)}
            )
            map_data = map_towns.merge(
                municipal,
                on="municipality",
                how="left",
            )
            map_data[["amount", "records", "contributors"]] = (
                map_data[["amount", "records", "contributors"]]
                .fillna(0)
            )

            fig = px.choropleth(
                map_data,
                geojson=vt_geojson,
                locations="municipality",
                featureidkey="properties.JOIN_NAME",
                color="amount",
                color_continuous_scale=[
                    [0.0, "#eef2f3"],
                    [0.12, "#dce9e5"],
                    [0.4, "#a9d4c1"],
                    [0.7, "#71b596"],
                    [1.0, "#3f8f72"],
                ],
                hover_name="municipality",
                hover_data={
                    "amount": ":$,.0f",
                    "records": ":,",
                    "contributors": ":,",
                    "municipality": False,
                },
                labels={"amount": "Contribution dollars"},
            )
            fig.update_traces(
                marker_line_color="#ffffff",
                marker_line_width=0.45,
            )
            fig.update_geos(
                fitbounds="locations",
                visible=False,
            )
            fig.update_layout(
                height=720,
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No mapped Vermont contributions match the filters.")

    if selected_town != "All mapped towns":
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
        st.dataframe(
            municipal.rename(
                columns={
                    "municipality": "Municipality",
                    "amount": "Amount",
                    "records": "Records",
                    "contributors": "Named contributors",
                    "share_of_mapped_vt": "Share of mapped VT",
                }
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
                "Share of mapped VT":
                    st.column_config.NumberColumn(format="%.1%%"),
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
    "Street addresses are not displayed."
)
