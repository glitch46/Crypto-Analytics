# Crypto Options Backtest Dashboard

Static dashboard that backtests options strategies for BTC and ETH using Deribit historical settlement data and Binance spot prices. Data refresh is handled via `scripts/refresh_crypto.py` and emitted as static JSON for the frontend.

## Data Sources

- **Binance Spot API** - Spot prices (free, public, no authentication required)
- **Deribit Public API** - Options settlement data, funding rates (free, public, no authentication required)
- **Note**: Binance Options discontinued in 2023; all options data now from Deribit

## Data Files
- `data/oi_history.json`: 7-day rolling open interest history (BTC/ETH)
- `data/max_pain.json`: max pain strike and top candidates
- `data/options_snapshot.json`: options KPI snapshot
- `data/trader_focus.json`: short-term trader metrics
- `data/expiry_pressure.json`: upcoming expiry pressure leaderboard
- `data/metadata.json`: refresh timestamp + sources

## Refresh

**No API keys required!** All data sources are free public APIs:

```bash
python scripts/refresh_crypto.py
```

The script fetches data from:
- Binance Spot API (free, unlimited public endpoints)
- Deribit Public API (free, unlimited public endpoints)

The frontend reads static JSON and includes no embedded API keys.
