# Vermont Campaign Finance Explorer

Local Streamlit app and ingestion pipeline for 2026 Vermont House and Senate
campaign-finance data in districts touching Windsor County.

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

## First run

```bash
cd ~/Downloads/vt_campaign_finance_repo
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

## Initialize Git

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

## Create a private GitHub repository later

Create an empty private repository on GitHub, then run the commands GitHub gives
you. They will look roughly like:

```bash
git branch -M main
git remote add origin <YOUR-PRIVATE-REPOSITORY-URL>
git push -u origin main
```

Do not paste credentials or tokens into source files.

## Data handling

The SQLite database and raw API downloads are intentionally ignored by Git.
That keeps local data and generated artifacts out of repository history.

The app displays contributor city/state/ZIP from public campaign-finance
filings but does not display street addresses.

## Current limitations

- Expenditures are intentionally not ingested until the correct public Vermont
  API endpoint has been captured.
- Candidates without confirmed GUIDs may still use name fallback.
- Mike Schmitt remains marked as having no profile/GUID found rather than being
  treated as a verified zero.
