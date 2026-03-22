# Crypto Analytics Dashboard

Static GitHub Pages dashboard for crypto options analytics. The main UI lives in `Crypto-Dashboard/` and refreshes via CryptoDataDownload API.

## Features

- **30-Day Open Interest Momentum**: Aggregated options open interest from Binance and Deribit exchanges
- **Max Pain Strike Map**: Identifies strike prices with maximum pain for option holders
- **Options Snapshot**: Real-time KPIs including put/call ratio, ATM IV, and OI concentration
- **Expiry Pressure Radar**: Upcoming expiration dates with significant open interest
- **30-Day Trader Focus**: Short-term metrics including funding rates and volatility spreads
- **Trading Indicators**: Spot orderbook depth delta, spot CVD by exchange, heatmap proxy, depth overlay, and CFTC commercial positioning context

## Data Sources

- Binance Options
- Deribit Options
- CryptoDataDownload API
- Binance Spot REST
- Coinbase Exchange REST
- CFTC COT legacy futures report

## Data Files

- `Crypto-Dashboard/data/oi_history.json`: 30-day open interest history (aggregated Binance + Deribit)
- `Crypto-Dashboard/data/max_pain.json`: max pain strike and candidates
- `Crypto-Dashboard/data/options_snapshot.json`: options KPI snapshot
- `Crypto-Dashboard/data/trader_focus.json`: short-term trader metrics
- `Crypto-Dashboard/data/expiry_pressure.json`: upcoming expiry pressure leaderboard
- `Crypto-Dashboard/data/metadata.json`: refresh timestamp + sources
- `Trading-Indicators/data/indicators.json`: BTC/ETH spot depth, CVD, heatmap proxy, overlay bands, confluence signals

## Refresh

GitHub Actions runs on schedule to update the JSON outputs.
