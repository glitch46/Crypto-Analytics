# Crypto Options Pulse Dashboard

Static dashboard that visualizes 30-day open interest and max pain for BTC and ETH using aggregated Binance + Deribit options data. Data refresh is handled via `scripts/refresh_crypto.py` and emitted as static JSON for the frontend.

## Features

- **30-Day Open Interest Momentum**: Aggregated options open interest from Binance and Deribit exchanges displayed as a single unified chart
- **Max Pain Strike Map**: Identifies strike prices with maximum pain for option holders (filtered to 70%-130% spot range)
- **Options Snapshot**: Real-time KPIs including:
  - Total options OI (notional USD)
  - Put/Call OI ratio
  - ATM implied volatility
  - IV term structure
  - OI concentration metrics
- **Expiry Pressure Radar**: Upcoming expiration dates ranked by notional value
- **30-Day Trader Focus**: Funding rates, perp basis, and realized vs implied volatility

## Data Sources

- Binance Options
- Deribit Options
- CryptoDataDownload API

## Data Files

- `data/oi_history.json`: 30-day open interest history (aggregated Binance + Deribit for BTC/ETH)
- `data/max_pain.json`: max pain strike and top candidates
- `data/options_snapshot.json`: options KPI snapshot
- `data/trader_focus.json`: short-term trader metrics
- `data/expiry_pressure.json`: upcoming expiry pressure leaderboard
- `data/metadata.json`: refresh timestamp + sources

## Refresh

Set `CRYPTODATADOWNLOAD_API_KEY` before running. Requests are authenticated via the `Authorization: Token <token>` header per CryptoDataDownload API docs:

```
python scripts/refresh_crypto.py
```

The frontend reads static JSON and includes no embedded API keys.