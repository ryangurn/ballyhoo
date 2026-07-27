# sociallist — feed archive

Machine-managed immutable snapshots of every published artifact. Not served by GitHub
Pages; read via `raw.githubusercontent.com`.

## Layout

```
events/recent/<YYYY-MM-DD>/<HHMMSS>Z.json.gz   every change, pruned after 7 days
events/daily/<YYYY>/<MM>/<DD>.json.gz          one per day, kept indefinitely
events/daily/<YYYY>/<MM>/index.json            manifest: time, sha256, size, count
sources/<source-id>/...                        same two tiers per source
```

The daily tier needs no rollup job: each write overwrites the current day's entry, so
it holds that day's latest snapshot and freezes when the date rolls over.

## Reading a snapshot

Snapshots are gzipped; manifests are not.

```bash
curl -sL https://raw.githubusercontent.com/ryangurn/sociallist/archive/events/daily/2026/07/27.json.gz | gunzip | jq .
curl -sL https://raw.githubusercontent.com/ryangurn/sociallist/archive/events/daily/2026/07/index.json | jq .
```

## Retention

Pruning bounds the **working tree**, keeping this branch browsable. It does not reclaim
git history, which grows at the full per-run rate — roughly 11 MB/day, ~4 GB/year.
Compacting that history (an orphan-commit rewrite, force-pushed) is deliberately
deferred; the runway is roughly 15–18 months against GitHub's ~5 GB guidance.
