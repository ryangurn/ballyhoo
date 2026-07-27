# sociallist — published feed

Machine-managed. Do not edit by hand; the pipeline overwrites this branch.

| Path | What |
|---|---|
| `events.json` | Canonical merged feed. The iOS app reads only this. |
| `sources/<id>.json` | One source's unmerged output. Supported public contract. |
| `sources/index.json` | Per-source health: last run, event count, status. |
| `history.json` | Event counts from recent merges, for the anomaly floor check. |
| `merge-report.json` | Last merge's dedup decisions and per-source problems. |

Served at https://ryangurn.github.io/sociallist/

Historical snapshots live on the `archive` branch.
Source lives in `pipeline/` on `main`.
