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

Support indicators beside reported totals and saved town candidate counts compare
current votes per ballot with the selected comparator's 2024 town support rate.
Expected votes = current town ballots × comparator's 2024 votes / 2024 town ballots.
Single arrows indicate a 2 to under 5 percentage-point difference; double arrows
indicate 5 points or more. No arrow appears below 2 points or without valid data.
Only complete validated towns with a known comparator baseline are eligible.
District indicators sum actual and expected votes in the same eligible towns and
divide their difference by current ballots; reported totals still include partial
returns. Tooltips identify the comparator, difference, expected votes and coverage.
Unsaved row edits hide town indicators until saved. These are descriptive historical
comparisons, not significance tests or changes to either projection model.

Run calculation checks with `node election_night/tests/model.test.cjs`.

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


## Separate results display

Select **Open results display ↗** in the control panel. The display opens separately;
if the browser opens a tab, drag it into its own window or onto another monitor.
Keep both views in the same browser profile. The display follows saved results,
the selected reporting snapshot, comparators, overlays, focus, turnout scale, and
switching assumptions. It never saves entries or polls SOS independently.

The presentation view (`?display=1`, plus `&demo=1` for simulation) hides editing
controls and places the map, charts, and turnout table side by side on wide screens.
Synchronization uses same-origin BroadcastChannel with browser-storage fallback;
it is not cross-device sharing. Closing the control panel leaves the last snapshot
visible with a disconnected notice. A cached display snapshot is marked as waiting
until the control panel reconnects. Live and simulation channels remain separate.

Run synchronization checks with `node election_night/tests/display-sync.test.cjs`.


## House contests

Thirteen 2026 House races overlap the Windsor Senate district. Each section includes
only its representative towns, a reporting map, cumulative candidate totals, a
reported-vote table, and a seat-aware margin chart. The default final-seat gap is
first minus second for one seat, or second minus third for two seats. Selecting a
candidate instead shows their votes minus the Nth-highest other candidate for N
seats. Ties are zero; an uncontested final seat has no invented opponent or margin.
Named write-ins are contenders; unallocated write-ins are shown separately.

The combined SOS refresh reads the House feed in addition to Senate and turnout,
retaining prior House results on a House-feed failure. Successful updates are saved
in the same immutable reporting snapshots and synchronize to the presentation view.
Old snapshots without House data remain explicitly unobserved. Existing manual
Senate overrides remain independent. No House manual-entry or forecast is added.

House contests crossing the Senate boundary use their full district returns and
maps: 39 distinct towns, including 14 outside the Senate district. Hartford is split
between Windsor-4 and Windsor-6: each race uses only its corresponding reporting
split, but maps show the whole town with a '(part)' note. Whole-town turnout is not
used as the split's ballot denominator. Completion follows town turnout reporting;
Hartford can remain partial until both splits have reported.

`election_night/frontend/data/house-races.json` records the official SOS roster URL and checksum,
with unknown vote counts at startup. Its 2024 ballot reference is used only to size
synthetic demonstration data. `house-towns.geojson` uses the same VCGI town outlines
as the Senate map. House demo votes are invented; external-town reporting times are
also invented and clearly labeled. They do not assert a House primary chronology.

Checks: `node election_night/tests/house.test.cjs` and
`python -m unittest discover -s election_night/tests`.
