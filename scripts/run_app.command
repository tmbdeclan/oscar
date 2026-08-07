#!/bin/bash
set -e
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -r requirements.txt

if [ ! -f data/campaign_finance.sqlite ]; then
  python -m ingest.run
fi

python -m streamlit run app.py
