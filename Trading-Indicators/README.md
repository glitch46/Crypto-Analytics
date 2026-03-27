# Trading Indicators Dashboard

This dashboard visualizes spot-orderbook structure and flow for BTC/ETH using:

- Binance Spot orderbook + trades
- Coinbase Spot orderbook + trades
- CFTC COT legacy futures (commercial positioning context)

## Features

- Depth Delta (2.5%, 5%, 10%, 25%)
- Spot CVD by exchange (Binance, Coinbase) + aggregate
- Heatmap proxy (top persistent bid/ask walls)
- Depth overlay support/resistance bands
- Commercial short contrarian context panel
- Visual-only long-readiness confluence score

## Data refresh

Refresh script:

```bash
python3 Trading-Indicators/scripts/refresh_trading_indicators.py
```

Output file:

- `Trading-Indicators/data/indicators.json`

## Interpretation notes

- Depth delta is liquidity imbalance, not a direct directional predictor.
- Positive depth delta + rising spot CVD + stronger bid-wall persistence is the preferred long context.
- Rising commercial shorts often indicate caution in crowded long regimes, and may become contrarian once spot liquidity improves.
