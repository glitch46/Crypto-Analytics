#!/usr/bin/env python3
import csv
import datetime
import json
import math
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

BINANCE_API = "https://data-api.binance.vision"
COINBASE_API = "https://api.exchange.coinbase.com"
CFTC_DEA_FUT = "https://www.cftc.gov/dea/newcot/deafut.txt"

ASSETS = {
    "BTC": {
        "binance_symbol": "BTCUSDT",
        "coinbase_product": "BTC-USD",
        "cot_market": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
    },
    "ETH": {
        "binance_symbol": "ETHUSDT",
        "coinbase_product": "ETH-USD",
        "cot_market": "ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE",
    },
}

DEPTH_WINDOWS = [0.025, 0.05, 0.10, 0.25]
SNAPSHOT_RETENTION = 30 * 24 * 4
HEATMAP_POINTS_PER_SIDE = 6
HEATMAP_RETENTION = SNAPSHOT_RETENTION * 24
CVD_GRANULARITY_SECONDS = 900


def fetch_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
    res = requests.get(url, params=params or {}, headers=headers or {}, timeout=30)
    res.raise_for_status()
    return res.json()


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def zscore(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    var = sum((x - avg) ** 2 for x in values) / (len(values) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (values[-1] - avg) / std


def pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return (current - previous) / previous


def normalize_depth(orders: List[List[float]], is_bid: bool) -> List[Tuple[float, float]]:
    normalized = []
    for row in orders:
        if len(row) < 2:
            continue
        price = safe_float(row[0])
        qty = safe_float(row[1])
        if price > 0 and qty > 0:
            normalized.append((price, qty))
    normalized.sort(key=lambda x: x[0], reverse=is_bid)
    return normalized


def fetch_binance_orderbook(symbol: str, limit: int = 1000) -> Dict[str, List[Tuple[float, float]]]:
    data = fetch_json(f"{BINANCE_API}/api/v3/depth", {"symbol": symbol, "limit": limit})
    bids = normalize_depth(data.get("bids", []), is_bid=True)
    asks = normalize_depth(data.get("asks", []), is_bid=False)
    return {"bids": bids, "asks": asks}


def fetch_coinbase_orderbook(product: str, level: int = 2) -> Dict[str, List[Tuple[float, float]]]:
    data = fetch_json(f"{COINBASE_API}/products/{product}/book", {"level": level})
    bids = normalize_depth(data.get("bids", []), is_bid=True)
    asks = normalize_depth(data.get("asks", []), is_bid=False)
    return {"bids": bids, "asks": asks}


def fetch_binance_trades(symbol: str, limit: int = 1000) -> List[dict]:
    return fetch_json(f"{BINANCE_API}/api/v3/trades", {"symbol": symbol, "limit": limit})


def fetch_coinbase_trades(product: str, limit: int = 300) -> List[dict]:
    headers = {"User-Agent": "crypto-analytics-trading-indicators/1.0"}
    return fetch_json(f"{COINBASE_API}/products/{product}/trades", {"limit": limit}, headers=headers)


def fetch_binance_klines(symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1000) -> List[list]:
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    }
    data = fetch_json(f"{BINANCE_API}/api/v3/klines", params)
    return data if isinstance(data, list) else []


def fetch_coinbase_candles(product: str, start_iso: str, end_iso: str, granularity: int = 900) -> List[list]:
    params = {"start": start_iso, "end": end_iso, "granularity": granularity}
    headers = {"User-Agent": "crypto-analytics-trading-indicators/1.0"}
    data = fetch_json(f"{COINBASE_API}/products/{product}/candles", params, headers=headers)
    return data if isinstance(data, list) else []


def build_binance_cvd_history(symbol: str, now_utc: datetime.datetime) -> List[dict]:
    start_dt = now_utc - timedelta(days=30)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(now_utc.timestamp() * 1000)

    klines = []
    cursor = start_ms
    while cursor < end_ms:
        chunk = fetch_binance_klines(symbol, "15m", cursor, end_ms, 1000)
        if not chunk:
            break
        klines.extend(chunk)
        last_open = int(chunk[-1][0])
        next_cursor = last_open + CVD_GRANULARITY_SECONDS * 1000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(chunk) < 1000:
            break

    dedup = {}
    for k in klines:
        if len(k) < 11:
            continue
        open_ms = int(k[0])
        quote_volume = safe_float(k[7])
        taker_buy_quote = safe_float(k[10])
        flow = (2.0 * taker_buy_quote) - quote_volume
        ts = datetime.datetime.fromtimestamp(open_ms / 1000, datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
        dedup[ts] = flow

    out = []
    running = 0.0
    for ts in sorted(dedup.keys()):
        flow = dedup[ts]
        running += flow
        out.append({"timestamp": ts, "flow": flow, "cumulative": running})
    return out[-SNAPSHOT_RETENTION:]


def build_coinbase_cvd_history(product: str, now_utc: datetime.datetime) -> List[dict]:
    start_dt = now_utc - timedelta(days=30)
    all_candles = []
    chunk_size = timedelta(minutes=300 * 15)
    cursor = start_dt
    while cursor < now_utc:
        end_chunk = min(cursor + chunk_size, now_utc)
        rows = fetch_coinbase_candles(
            product,
            cursor.isoformat().replace("+00:00", "Z"),
            end_chunk.isoformat().replace("+00:00", "Z"),
            granularity=CVD_GRANULARITY_SECONDS,
        )
        all_candles.extend(rows)
        cursor = end_chunk

    dedup = {}
    for c in all_candles:
        if len(c) < 6:
            continue
        # Coinbase candle format: [time, low, high, open, close, volume]
        ts_unix = int(c[0])
        low = safe_float(c[1])
        high = safe_float(c[2])
        open_px = safe_float(c[3])
        close_px = safe_float(c[4])
        vol = safe_float(c[5])
        vwap = (low + high + open_px + close_px) / 4.0
        direction = 1.0 if close_px > open_px else (-1.0 if close_px < open_px else 0.0)
        flow = direction * vol * vwap
        ts = datetime.datetime.fromtimestamp(ts_unix, datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
        dedup[ts] = flow

    out = []
    running = 0.0
    for ts in sorted(dedup.keys()):
        flow = dedup[ts]
        running += flow
        out.append({"timestamp": ts, "flow": flow, "cumulative": running})
    return out[-SNAPSHOT_RETENTION:]


def orderbook_mid(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> Optional[float]:
    if not bids or not asks:
        return None
    return (bids[0][0] + asks[0][0]) / 2


def compute_depth_metrics(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]], mid: float) -> Dict[str, dict]:
    metrics = {}
    for window in DEPTH_WINDOWS:
        bid_floor = mid * (1 - window)
        ask_ceiling = mid * (1 + window)

        bid_notional = sum(price * qty for price, qty in bids if price >= bid_floor)
        ask_notional = sum(price * qty for price, qty in asks if price <= ask_ceiling)
        total = bid_notional + ask_notional
        delta = bid_notional - ask_notional
        normalized = (delta / total) if total else 0.0

        key = f"{window * 100:.1f}%"
        metrics[key] = {
            "bid_notional": bid_notional,
            "ask_notional": ask_notional,
            "delta": delta,
            "normalized_delta": normalized,
        }
    return metrics


def binance_cvd_notional(trades: List[dict]) -> float:
    cvd = 0.0
    for t in trades:
        price = safe_float(t.get("price"))
        qty = safe_float(t.get("qty"))
        notional = price * qty
        is_buyer_maker = bool(t.get("isBuyerMaker"))
        cvd += -notional if is_buyer_maker else notional
    return cvd


def coinbase_cvd_notional(trades: List[dict]) -> float:
    cvd = 0.0
    for t in trades:
        price = safe_float(t.get("price"))
        size = safe_float(t.get("size"))
        notional = price * size
        side = str(t.get("side", "")).lower()
        if side == "buy":
            cvd += notional
        elif side == "sell":
            cvd -= notional
    return cvd


def top_heatmap_points(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    ts: str,
    exchange: str,
) -> List[dict]:
    points = []
    for price, qty in bids[:HEATMAP_POINTS_PER_SIDE]:
        points.append({
            "timestamp": ts,
            "exchange": exchange,
            "side": "bid",
            "price": price,
            "size": qty,
            "notional": price * qty,
        })
    for price, qty in asks[:HEATMAP_POINTS_PER_SIDE]:
        points.append({
            "timestamp": ts,
            "exchange": exchange,
            "side": "ask",
            "price": price,
            "size": qty,
            "notional": price * qty,
        })
    return points


def compute_overlay_bands(
    mid: float,
    depth_5: dict,
    depth_10: dict,
    bid_wall_price: Optional[float],
    ask_wall_price: Optional[float],
) -> dict:
    base_support = mid * (1 - 0.01)
    base_resistance = mid * (1 + 0.01)

    bid_strength = max(0.0, depth_5.get("normalized_delta", 0.0))
    ask_strength = max(0.0, -depth_5.get("normalized_delta", 0.0))

    support = min(base_support, bid_wall_price if bid_wall_price else base_support)
    resistance = max(base_resistance, ask_wall_price if ask_wall_price else base_resistance)

    support *= 1 - min(0.02, bid_strength * 0.02)
    resistance *= 1 + min(0.02, ask_strength * 0.02)

    return {
        "support": support,
        "resistance": resistance,
        "inner_support": mid * (1 - 0.005),
        "inner_resistance": mid * (1 + 0.005),
        "depth_bias_10": depth_10.get("normalized_delta", 0.0),
    }


def parse_cot_commercial_history() -> Dict[str, dict]:
    txt = requests.get(CFTC_DEA_FUT, timeout=30).text
    reader = csv.reader(txt.splitlines())

    rows = {}
    for row in reader:
        if len(row) < 13:
            continue
        market = row[0].strip().strip('"')
        for asset, cfg in ASSETS.items():
            if market == cfg["cot_market"]:
                report_date = row[2].strip()
                open_interest = safe_float(row[7])
                commercial_long = safe_float(row[11])
                commercial_short = safe_float(row[12])
                net = commercial_long - commercial_short
                short_ratio = (commercial_short / open_interest) if open_interest else 0.0
                rows[asset] = {
                    "date": report_date,
                    "commercial_long": commercial_long,
                    "commercial_short": commercial_short,
                    "commercial_net": net,
                    "commercial_short_ratio": short_ratio,
                }
    return rows


def trim_series(series: List[dict], key: str, max_len: int) -> List[dict]:
    dedup = {}
    for item in series:
        dedup[item[key]] = item
    out = [dedup[k] for k in sorted(dedup.keys())]
    if len(out) > max_len:
        out = out[-max_len:]
    return out


def load_existing(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception:
        return {}


def latest_wall_stats(heatmap_points: List[dict], current_ts: str) -> dict:
    recent = [p for p in heatmap_points if p.get("timestamp") != current_ts]
    recent = recent[-400:]

    def count_near(side: str, price: Optional[float], tol=0.002):
        if not price:
            return 0
        lo = price * (1 - tol)
        hi = price * (1 + tol)
        return sum(1 for p in recent if p.get("side") == side and lo <= p.get("price", 0) <= hi)

    latest_bid = [p for p in heatmap_points if p.get("timestamp") == current_ts and p.get("side") == "bid"]
    latest_ask = [p for p in heatmap_points if p.get("timestamp") == current_ts and p.get("side") == "ask"]

    bid_price = latest_bid[0]["price"] if latest_bid else None
    ask_price = latest_ask[0]["price"] if latest_ask else None

    bid_persistence = count_near("bid", bid_price)
    ask_persistence = count_near("ask", ask_price)
    return {
        "bid_wall_price": bid_price,
        "ask_wall_price": ask_price,
        "bid_wall_persistence": bid_persistence,
        "ask_wall_persistence": ask_persistence,
    }


def confluence_signal(asset_payload: dict) -> dict:
    depth_hist = asset_payload.get("depth_delta_history", [])
    cvd_hist = asset_payload.get("cvd_history", [])
    cot_hist = asset_payload.get("commercials", [])

    depth_score = 50.0
    cvd_score = 50.0
    wall_score = 50.0
    commercial_caution = 50.0

    if depth_hist:
        latest = depth_hist[-1]
        d5 = latest.get("combined", {}).get("5.0%", {}).get("normalized_delta", 0.0)
        d10 = latest.get("combined", {}).get("10.0%", {}).get("normalized_delta", 0.0)
        depth_score = max(0.0, min(100.0, (d5 + d10 + 1.0) * 50.0))

    if len(cvd_hist) >= 8:
        recent = [x.get("aggregate", 0.0) for x in cvd_hist[-8:]]
        slope = recent[-1] - recent[0]
        scale = max(1.0, abs(recent[-1]) * 0.1)
        cvd_norm = max(-1.0, min(1.0, slope / scale))
        cvd_score = (cvd_norm + 1.0) * 50.0

    walls = asset_payload.get("wall_stats", {})
    bid_p = walls.get("bid_wall_persistence", 0)
    ask_p = walls.get("ask_wall_persistence", 0)
    wall_delta = bid_p - ask_p
    wall_score = max(0.0, min(100.0, 50.0 + wall_delta * 3.0))

    if cot_hist:
        short_ratios = [x.get("commercial_short_ratio", 0.0) for x in cot_hist if x.get("commercial_short_ratio") is not None]
        if short_ratios:
            z = zscore(short_ratios)
            commercial_caution = max(0.0, min(100.0, 50.0 + (z or 0.0) * 18.0))

    long_readiness = 0.35 * depth_score + 0.35 * cvd_score + 0.20 * wall_score + 0.10 * (100.0 - commercial_caution)

    interpretation = "Neutral"
    if long_readiness >= 65:
        interpretation = "Constructive for longs"
    elif long_readiness <= 40:
        interpretation = "Caution / defensive"

    return {
        "depth_score": round(depth_score, 2),
        "cvd_score": round(cvd_score, 2),
        "wall_score": round(wall_score, 2),
        "commercial_caution": round(commercial_caution, 2),
        "long_readiness": round(long_readiness, 2),
        "label": interpretation,
    }


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, "indicators.json")

    existing = load_existing(output_path)
    assets_store = existing.get("assets", {})
    now_utc = datetime.datetime.now(datetime.UTC)
    ts = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    cot_latest = parse_cot_commercial_history()

    assets_payload = {}
    for asset, cfg in ASSETS.items():
        prev = assets_store.get(asset, {})
        depth_history = prev.get("depth_delta_history", [])
        cvd_history = prev.get("cvd_history", [])
        heatmap_points = prev.get("heatmap_points", [])
        overlay_history = prev.get("overlay_history", [])
        commercials_history = prev.get("commercials", [])

        binance_ob = fetch_binance_orderbook(cfg["binance_symbol"], limit=1000)
        coinbase_ob = fetch_coinbase_orderbook(cfg["coinbase_product"], level=2)

        binance_mid = orderbook_mid(binance_ob["bids"], binance_ob["asks"])
        coinbase_mid = orderbook_mid(coinbase_ob["bids"], coinbase_ob["asks"])
        mids = [m for m in [binance_mid, coinbase_mid] if m is not None]
        mid = sum(mids) / len(mids) if mids else 0.0

        binance_depth = compute_depth_metrics(binance_ob["bids"], binance_ob["asks"], binance_mid or mid)
        coinbase_depth = compute_depth_metrics(coinbase_ob["bids"], coinbase_ob["asks"], coinbase_mid or mid)

        combined_depth = {}
        for window in [f"{x * 100:.1f}%" for x in DEPTH_WINDOWS]:
            b = binance_depth[window]
            c = coinbase_depth[window]
            bid_notional = b["bid_notional"] + c["bid_notional"]
            ask_notional = b["ask_notional"] + c["ask_notional"]
            delta = bid_notional - ask_notional
            total = bid_notional + ask_notional
            combined_depth[window] = {
                "bid_notional": bid_notional,
                "ask_notional": ask_notional,
                "delta": delta,
                "normalized_delta": (delta / total) if total else 0.0,
            }

        depth_snapshot = {
            "timestamp": ts,
            "mid_price": mid,
            "binance": binance_depth,
            "coinbase": coinbase_depth,
            "combined": combined_depth,
        }
        depth_history.append(depth_snapshot)
        depth_history = depth_history[-SNAPSHOT_RETENTION:]

        b_cvd = build_binance_cvd_history(cfg["binance_symbol"], now_utc)
        c_cvd = build_coinbase_cvd_history(cfg["coinbase_product"], now_utc)
        b_map = {x["timestamp"]: x for x in b_cvd}
        c_map = {x["timestamp"]: x for x in c_cvd}
        merged_ts = sorted(set(b_map.keys()) | set(c_map.keys()))
        cvd_history = []
        last_b = 0.0
        last_c = 0.0
        for t in merged_ts:
            if t in b_map:
                last_b = b_map[t]["cumulative"]
                b_flow = b_map[t]["flow"]
            else:
                b_flow = 0.0
            if t in c_map:
                last_c = c_map[t]["cumulative"]
                c_flow = c_map[t]["flow"]
            else:
                c_flow = 0.0
            cvd_history.append({
                "timestamp": t,
                "binance": last_b,
                "coinbase": last_c,
                "aggregate": last_b + last_c,
                "binance_flow": b_flow,
                "coinbase_flow": c_flow,
            })
        cvd_history = cvd_history[-SNAPSHOT_RETENTION:]

        heatmap_points.extend(top_heatmap_points(binance_ob["bids"], binance_ob["asks"], ts, "Binance Spot"))
        heatmap_points.extend(top_heatmap_points(coinbase_ob["bids"], coinbase_ob["asks"], ts, "Coinbase Spot"))
        heatmap_points = heatmap_points[-HEATMAP_RETENTION:]

        walls = latest_wall_stats(heatmap_points, ts)
        overlay = compute_overlay_bands(
            mid,
            combined_depth.get("5.0%", {}),
            combined_depth.get("10.0%", {}),
            walls.get("bid_wall_price"),
            walls.get("ask_wall_price"),
        )
        overlay_history.append({"timestamp": ts, "mid_price": mid, **overlay})
        overlay_history = overlay_history[-SNAPSHOT_RETENTION:]

        cot_row = cot_latest.get(asset)
        if cot_row:
            commercials_history.append(cot_row)
            commercials_history = trim_series(commercials_history, "date", 260)

        payload = {
            "latest": {
                "timestamp": ts,
                "mid_price": mid,
                "binance_mid": binance_mid,
                "coinbase_mid": coinbase_mid,
                "depth_5_delta": combined_depth.get("5.0%", {}).get("delta"),
                "depth_5_norm": combined_depth.get("5.0%", {}).get("normalized_delta"),
                "depth_10_delta": combined_depth.get("10.0%", {}).get("delta"),
                "depth_10_norm": combined_depth.get("10.0%", {}).get("normalized_delta"),
                "depth_25_delta": combined_depth.get("25.0%", {}).get("delta"),
                "depth_25_norm": combined_depth.get("25.0%", {}).get("normalized_delta"),
                "cvd_aggregate": cvd_history[-1]["aggregate"] if cvd_history else 0.0,
            },
            "depth_delta_history": depth_history,
            "cvd_history": cvd_history,
            "heatmap_points": heatmap_points,
            "overlay_history": overlay_history,
            "commercials": commercials_history,
            "wall_stats": walls,
        }
        payload["signals"] = confluence_signal(payload)
        assets_payload[asset] = payload

    metadata = {
        "last_updated": ts,
        "refresh_cadence": "15 minutes",
        "sources": [
            "Binance Spot REST",
            "Coinbase Exchange REST",
            "CFTC COT (Legacy Futures)",
        ],
        "notes": [
            "Depth delta is liquidity imbalance, not a direct direction predictor.",
            "Commercial short increases are interpreted as contrarian caution in crowded long conditions.",
            "Coinbase CVD is derived from 15m candle direction proxy due public trade-history pagination limits.",
            "Signals are visual-only and intended for discretionary confirmation.",
        ],
    }

    output = {
        "metadata": metadata,
        "config": {
            "exchanges": ["Binance Spot", "Coinbase Spot"],
            "depth_windows": ["2.5%", "5.0%", "10.0%", "25.0%"],
            "heatmap_points_per_side": HEATMAP_POINTS_PER_SIDE,
        },
        "assets": assets_payload,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
