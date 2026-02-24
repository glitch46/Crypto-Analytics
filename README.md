# Crypto Analytics Dashboard

Static GitHub Pages dashboard for crypto options analytics. The main UI lives in `Crypto-Dashboard/` and refreshes via CryptoDataDownload API.

## Data
- `Crypto-Dashboard/data/oi_history.json`: 7-day open interest history
- `Crypto-Dashboard/data/max_pain.json`: max pain strike and candidates
- `Crypto-Dashboard/data/options_snapshot.json`: options KPI snapshot
- `Crypto-Dashboard/data/trader_focus.json`: short-term trader metrics
- `Crypto-Dashboard/data/metadata.json`: refresh timestamp + sources

## Refresh
GitHub Actions runs on schedule to update the JSON outputs.
