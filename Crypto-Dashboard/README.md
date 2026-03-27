# Crypto Options Pulse Dashboard

Static dashboard that visualizes 30-day open interest and max pain for BTC and ETH using Deribit options data and Binance spot prices. Data refresh is handled via `scripts/refresh_crypto.py` and emitted as static JSON for the frontend.

## Features

- **30-Day Open Interest Momentum**: Options open interest from Deribit displayed as a unified chart
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

- **Binance Spot API** - Spot prices and historical data (free, public, no authentication required)
- **Deribit Public API** - Options data, funding rates, volatility index (free, public, no authentication required)
- **Note**: Binance Options discontinued in 2023; all options data now from Deribit

## Data Files

- `data/oi_history.json`: 7-day rolling open interest history (Deribit for BTC/ETH)
- `data/max_pain.json`: max pain strike and top candidates
- `data/options_snapshot.json`: options KPI snapshot
- `data/trader_focus.json`: short-term trader metrics
- `data/expiry_pressure.json`: upcoming expiry pressure leaderboard
- `data/backtest.json`: 12-month historical backtest data
- `data/strategy_signals.json`: 3-year BTC price history with RSI and lunar events
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