# Open-Source Campaign Analytics

Open-Source Campaign Analytics (OSCA) is a 2026 Vermont House and Senate
campaign-finance and election-context app for districts touching Windsor
County.

## Project layout

```text
vt-campaign-finance/
├── app.py
├── candidates.csv
├── ingest/
│   ├── api.py
│   ├── db.py
│   ├── run.py
│   └── verify.py
├── scripts/
│   ├── run_app.command
│   └── refresh_data.command
├── data/
├── raw_json/
├── requirements.txt
├── .gitignore
└── README.md
```

## Run locally

```bash
cd ~/Documents/Projects
chmod +x scripts/run_app.command scripts/refresh_data.command
xattr -d com.apple.quarantine scripts/run_app.command 2>/dev/null || true
xattr -d com.apple.quarantine scripts/refresh_data.command 2>/dev/null || true
./scripts/run_app.command
```

Streamlit normally opens at:

```text
http://localhost:8501
```

## Refresh the data

```bash
./scripts/refresh_data.command
```

Then reload the Streamlit page.

## Phase 1 private sharing

The app is ready to deploy as a private Streamlit Community Cloud app from a
GitHub repository.

1. Create a private GitHub repository.
2. Push this repository to GitHub.
3. In Streamlit Community Cloud, choose **Create app**.
4. Select the GitHub repo, branch, and `app.py` as the entrypoint.
5. Keep the app private while validating the data and presentation.

This Phase 1 bundle includes:

- `data/campaign_finance.sqlite`, the local public campaign-finance database
  used by the app at startup.
- Generated CSV caches for population density, 2024 primary turnout, household
  income, Windsor street-address geocodes, and inferred P.O. box parcel matches.
- The OSCA icon used for the app header and browser icon.

No Streamlit secrets are currently required. The app uses local public-data
caches plus live public VCGI town boundaries.

## 2026 primary results

The Windsor town map can incorporate town-level 2026 primary results from the
Vermont Election Night Results site. Refresh the local CSV caches with:

```bash
python scripts/fetch_vermont_primary_2026.py
```

The script writes candidate result rows to:

```text
data/vermont_primary_results_2026.csv
```

Expected columns:

```csv
town_geoid,municipality,office,district,party,candidate,votes
```

It also writes town turnout rows to:

```text
data/vermont_primary_turnout_2026.csv
```

`town_geoid` is preferred in any manually prepared file. If it is blank, the
app will try to match the `municipality` value to the VCGI town name. The map
uses the turnout file for actual 2026 primary voters and turnout percentage,
and uses the candidate result file for leading candidate/result-row context.

The app also includes a Windsor Senate rollout view with a district map and
linked candidate-total and third-seat-pressure charts. It uses the archived
download/export sequence to show when each town first appeared in public result
snapshots.

## GitHub setup

From inside the project folder:

```bash
git init
git add .
git commit -m "Initial Vermont campaign finance explorer"
```

Check the repository:

```bash
git status
git log --oneline
```

Create an empty private repository on GitHub, then run the commands GitHub gives
you. They will look roughly like:

```bash
git branch -M main
git remote add origin <YOUR-PRIVATE-REPOSITORY-URL>
git push -u origin main
```

Do not paste credentials or tokens into source files.

## Data handling

The main SQLite database is intentionally tracked for the Phase 1 private
Streamlit deployment. SQLite runtime sidecar files (`*.sqlite-shm` and
`*.sqlite-wal`) and raw API downloads remain ignored.

The app displays contributor city/state/ZIP from public campaign-finance
filings. The Windsor address map also displays filed street-address geocodes
and high-confidence inferred P.O. box parcel locations when available.

## Current limitations

- Expenditures are intentionally not ingested until the correct public Vermont
  API endpoint has been captured.
- Candidates without confirmed GUIDs may still use name fallback.
- Mike Schmitt remains marked as having no profile/GUID found rather than being
  treated as a verified zero.


## Interactive Vermont municipality map

The app can now load Vermont town polygons directly from the official VCGI
BNDHASH Town Boundaries feature service and render contribution dollars as a
municipal choropleth.

The join is deliberately conservative:

1. A reported Vermont `city` is normalized.
2. If it exactly matches an official town name, it is mapped.
3. Otherwise the label remains **unmatched** rather than being silently guessed.
4. You can explicitly resolve postal/place-name differences in `town_aliases.csv`.

Example:

```csv
reported_city,municipality
BROWNSVILLE,WEST WINDSOR
WHITE RIVER JUNCTION,HARTFORD
```

Only add aliases you are comfortable treating as a municipality mapping.

The source boundary dataset is VCGI's BNDHASH town layer. VCGI notes that it is
intended for general mapping and is not a legally definitive boundary dataset.
