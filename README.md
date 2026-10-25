# Open-Source Campaign Analytics — OSCA

Branded Windsor Senate election-night workspace, deployed through Streamlit.

## Run

```sh
pip install -r requirements.txt
streamlit run app.py
```

The entrypoint mounts the versioned `election_night/frontend` custom component.
Its SOS button communicates with the Python adapter using Streamlit's components-v1
protocol; no external API server or secrets are needed. Public SOS requests are
cached for 45 seconds. Browser polling is optional at 60-second intervals.

Open `?demo=1` or select **Try election-night simulation** for the synthetic replay.
Return to live mode to enter actual preliminary results or fetch SOS. The simulation
uses OSCA's recorded 2026 primary reporting chronology, not verified submission
times. Its votes remain synthetic. Simulation and live session imports cannot mix.

## Interface

- District reporting map and linked candidate-total / third-seat-margin charts.
- Official 2024 general-election overlay for the same reporting footprint.
- Preliminary town entry; manual town overrides survive SOS refreshes.
- Browser-local immutable snapshots, JSON export/import, and source notes.
- 2024-turnout reweighting scenario for entered results.
- Separate, explicit hypothetical crossover sensitivity and historical-multiplier model.
- Dotted switching-model chart overlay, with no winner call or probability.

Comparator defaults: Burrows → Joe Major; Major → Alison H. Clarkson; Izzo → Marc
Nemeth. They affect historical comparisons, not projected vote calculations.

## Evidence and model boundaries

Data files under `election_night/frontend/data` retain official source URLs,
normalization metadata and calibration inputs. The SOS adapter excludes district
summary rows and combines Hartford reporting splits to avoid double counting.
Zero reports, unavailable data, partial reports, and certified/official flags are
separate states. Browser state is not a shared or durable results database; export
sessions for backup. Refresh errors retain prior successful results.

The historical conversion model uses pooled 2024 factors: D 52,586 / 11,617 =
4.526642; R 33,882 / 3,815 = 8.881258. Estimated switchers' D selections are removed
proportionally to town primary selection rates before multiplication; each assumed
switcher adds exactly one general vote to each R nominee after multiplication.
Ordinary district totals are allocated by remaining 2024 turnout weights only for
chart timing, not as a prediction of candidate geography. A single presidential
election cycle does not validate a midterm forecast. Independents and write-ins
are not modeled in this six-nominee scenario.

This deployment replaces the former campaign-finance interface. The previous
implementation remains recoverable in Git history (last prior revision:
`41184df9e968f47e86fab4dd112dcf3db8072044`). Existing finance data and ingestion
scripts remain in the repository but are not used by the new interface.

D3 7.9.0 is vendored with its license in `election_night/frontend/vendor`.
