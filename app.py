from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

HERE = Path(__file__).resolve().parent
DB = HERE / "data" / "campaign_finance.sqlite"

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
        st.plotly_chart(fig, use_container_width=True)
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
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No dated records match the current filters.")

# ---------- Geography ----------
st.subheader("Geographic breakdown")
geo_mode = st.radio(
    "Geographic view",
    ["By state", "Within Vermont by city/town"],
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
    geo["share"] = geo["amount"] / geo["amount"].sum() if geo["amount"].sum() else 0

    g1, g2 = st.columns([1.3, 1])
    with g1:
        if len(geo):
            fig = px.bar(
                geo.head(25).sort_values("amount"),
                x="amount",
                y="geo_label",
                orientation="h",
                labels={"amount": "Contribution dollars", "geo_label": "State"},
            )
            fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
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
            use_container_width=True,
            hide_index=True,
            column_config={
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
                "Share": st.column_config.NumberColumn(format="%.1%%"),
            },
        )

else:
    vt = filtered[filtered["state"] == "VT"].copy()
    vt["geo_label"] = vt["city"].replace("", "Unreported")
    geo = (
        vt.groupby("geo_label", as_index=False)
        .agg(amount=("amount", "sum"), records=("amount", "size"))
        .sort_values("amount", ascending=False)
    )
    geo["share_of_vt"] = geo["amount"] / geo["amount"].sum() if geo["amount"].sum() else 0

    g1, g2 = st.columns([1.3, 1])
    with g1:
        if len(geo):
            fig = px.bar(
                geo.head(30).sort_values("amount"),
                x="amount",
                y="geo_label",
                orientation="h",
                labels={
                    "amount": "Contribution dollars",
                    "geo_label": "Vermont city / town",
                },
            )
            fig.update_layout(height=680, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No Vermont-located contributions match the current filters.")
    with g2:
        st.dataframe(
            geo.rename(
                columns={
                    "geo_label": "Vermont city / town",
                    "amount": "Amount",
                    "records": "Records",
                    "share_of_vt": "Share of VT",
                }
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
                "Share of VT": st.column_config.NumberColumn(format="%.1%%"),
            },
        )

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
        use_container_width=True,
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
    st.dataframe(comparison, use_container_width=True, hide_index=True)

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
        use_container_width=True,
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
    use_container_width=True,
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
