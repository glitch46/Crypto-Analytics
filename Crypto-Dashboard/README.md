# Crypto Options Pulse Dashboard

Static dashboard that visualizes 7-day open interest and max pain for BTC and ETH using Binance + Deribit options data. Data refresh is handled via `scripts/refresh_crypto.py` and emitted as static JSON for the frontend.

## Data Files
- `data/oi_history.json`: 7-day open interest history (BTC/ETH)
- `data/max_pain.json`: max pain strike and top candidates
- `data/options_snapshot.json`: options KPI snapshot
- `data/trader_focus.json`: short-term trader metrics
- `data/expiry_pressure.json`: upcoming expiry pressure leaderboard
- `data/metadata.json`: refresh timestamp + sources

## Refresh
Set `CRYPTODATADOWNLOAD_API_KEY` before running. Requests are authenticated via the `Authorization: Bearer <token>` header per CryptoDataDownload API docs:

```
python scripts/refresh_crypto.py
```

The frontend reads static JSON and includes no embedded API keys.
