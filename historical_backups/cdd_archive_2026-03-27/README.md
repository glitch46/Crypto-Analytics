# CryptoDataDownload Historical Data Archive

**Archive Date:** March 27, 2026  
**Reason:** Migration from CryptoDataDownload API to free alternatives  
**Data Source:** CryptoDataDownload (https://api.cryptodatadownload.com)

## Archived Files

### Crypto-Dashboard Data (8 files)
- `backtest.json` - 12 months of historical backtest data with settlement prices
- `expiry_pressure.json` - Expiry pressure analysis
- `max_pain.json` - Max pain calculations
- `metadata.json` - Last updated timestamps and data sources
- `oi_history.json` - Rolling 7-day open interest history
- `options_snapshot.json` - Current options market snapshot
- `strategy_signals.json` - **3 years of BTC price history (2023-03-18 to 2026-03-27, 9,771+ data points)**
- `trader_focus.json` - Trader-focused metrics (funding, basis, IV)

### Backtest-Dashboard Data (6 files)
- `expiry_pressure.json` - Expiry pressure analysis
- `max_pain.json` - Max pain calculations
- `metadata.json` - Last updated timestamps and data sources
- `oi_history.json` - Rolling 7-day open interest history
- `options_snapshot.json` - Current options market snapshot
- `trader_focus.json` - Trader-focused metrics

## Data Coverage

### Historical Price Data (strategy_signals.json)
- **Asset:** BTC
- **Date Range:** March 18, 2023 - March 27, 2026
- **Data Points:** 1,095+ days of OHLC data
- **Fields:** date, open, high, low, close, weekly_rsi, daily_rsi, lunar_events

### Backtest Data (backtest.json)
- **Period:** April 2025 - March 2026 (12 months)
- **Metrics:** Settlement prices, OI, Put/Call ratios, Max Pain deviation
- **Success Rate:** ~41.7% skew-following accuracy

### Open Interest History (oi_history.json)
- **Rolling Window:** 7 days
- **Latest Period:** March 13-19, 2026
- **Assets:** BTC, ETH
- **Values:** USD-denominated total OI

## Why This Archive Exists

CryptoDataDownload API was a paid service providing historical crypto market data. As of March 2026, we migrated to free alternatives:

- **Spot Prices:** Binance Spot API (free)
- **Historical Data:** CoinGecko API / Binance API (free)
- **Options Data:** Deribit Public API (free)
- **Funding/Volatility:** Deribit Public API (free)

This archive preserves all historical data fetched from CryptoDataDownload before the migration, ensuring no data loss and providing a reference point for comparing data quality from the new sources.

## Restoration

If you need to reference this historical data:

1. The data is in JSON format and can be loaded directly
2. Structure matches the current dashboard format
3. Use for backtesting, analysis, or data validation
4. Do NOT overwrite current dashboard data without backup

## Notes

- Binance Options data was already stale as of 2023 (noted in original code)
- OI history only keeps rolling 7-day window (older data pruned)
- Strategy signals contain the most comprehensive historical dataset
- All timestamps in UTC
- Data sources mixed: CryptoDataDownload (Binance + Deribit wrapped) + Direct Deribit API
