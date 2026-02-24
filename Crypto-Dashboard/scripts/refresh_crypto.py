#!/usr/bin/env python3
import datetime
import json
import os
import urllib.parse
import urllib.request

CRYPTO_API_KEY = os.environ.get("CRYPTODATADOWNLOAD_API_KEY")
CRYPTO_API_BASE = "https://api.cryptodatadownload.com/v1/data"

ASSETS = {
    "BTC": {
        "spot_symbol": "BTC"
    },
    "ETH": {
        "spot_symbol": "ETH"
    }
}


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_headers():
    if not CRYPTO_API_KEY:
        raise RuntimeError("CRYPTODATADOWNLOAD_API_KEY is required")
    return {
        "Authorization": f"Token {CRYPTO_API_KEY}",
        "User-Agent": "crypto-analytics-dashboard/1.0"
    }


def load_cdd(path, params=None):
    payload = dict(params or {})
    payload.setdefault("auth_token", CRYPTO_API_KEY)
    query = urllib.parse.urlencode(payload)
    url = f"{CRYPTO_API_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    return fetch_json(url, headers=build_headers())


def load_binance_options_oi_summary(underlying, limit=5000):
    return load_cdd("/summary/binance/options/oi/", {
        "underlying": underlying,
        "limit": limit,
        "return": "JSON"
    })


def load_binance_oi_maturity(underlying, limit=5000):
    return load_cdd("/summary/binance/options/oi/maturity/", {
        "underlying": underlying,
        "limit": limit,
        "return": "JSON"
    })


def load_binance_options_ohlc(underlying, maturity, limit=5000):
    return load_cdd("/ohlc/binance/options/", {
        "underlying": underlying,
        "maturity": maturity,
        "limit": limit,
        "return": "JSON"
    })


def load_binance_options_oi_instrument(underlying, symbol, limit=5000):
    return load_cdd("/summary/binance/options/oi/instrument/", {
        "underlying": underlying,
        "symbol": symbol,
        "limit": limit,
        "return": "JSON"
    })


def load_spot_price(symbol):
    try:
        data = load_cdd("/ohlc/binance/spot/", {
            "symbol": symbol,
            "interval": "1d",
            "limit": 1,
            "return": "JSON"
        })
    except Exception:
        return None
    if isinstance(data, list) and data:
        row = data[-1]
        for key in ("Close", "close"):
            if key in row:
                return row.get(key)
    return None


def compute_max_pain(strikes, price_points):
    best = None
    candidates = []
    for strike in price_points:
        pain = 0.0
        for entry in strikes:
            oi = entry.get("open_interest", 0) or 0
            if entry["option_type"] == "call":
                pain += max(0.0, strike - entry["strike"]) * oi
            else:
                pain += max(0.0, entry["strike"] - strike) * oi
        candidates.append({"strike": strike, "pain": pain})
    candidates.sort(key=lambda x: x["pain"], reverse=True)
    if candidates:
        best = candidates[0]
    return best, candidates[:5]


def aggregate_open_interest(rows):
    total = 0.0
    call_oi = 0.0
    put_oi = 0.0
    for row in rows:
        oi = row.get("open_interest", 0) or 0
        total += oi
        if row.get("option_type") == "call":
            call_oi += oi
        elif row.get("option_type") == "put":
            put_oi += oi
    put_call = (put_oi / call_oi) if call_oi else None
    return total, call_oi, put_oi, put_call


def build_history(rows):
    history = []
    for row in rows:
        date = row.get("Date") or row.get("date")
        if not date:
            continue
        calls = row.get("Total Calls OI") or row.get("total_calls_oi") or 0
        puts = row.get("Total Puts OI") or row.get("total_puts_oi") or 0
        try:
            oi = float(calls) + float(puts)
        except (TypeError, ValueError):
            oi = 0
        history.append({"date": date, "open_interest": oi})
    history.sort(key=lambda x: x["date"])
    if len(history) < 7:
        today = datetime.date.today()
        for i in range(7 - len(history)):
            day = today - datetime.timedelta(days=(6 - len(history) - i))
            history.insert(0, {"date": day.strftime("%Y-%m-%d"), "open_interest": 0})
    return history[-7:]


def extract_latest_by_symbol(options_rows):
    latest = {}
    for row in options_rows:
        symbol = row.get("Symbol") or row.get("symbol")
        if not symbol:
            continue
        date = row.get("Date") or row.get("date") or ""
        hour = row.get("Hour") or row.get("hour") or ""
        stamp = f"{date} {hour}".strip()
        existing = latest.get(symbol)
        if not existing or stamp > existing.get("stamp", ""):
            row["stamp"] = stamp
            latest[symbol] = row
    return latest


def normalize_option_type(value):
    if not value:
        return None
    value = str(value).lower()
    if value.startswith("c"):
        return "call"
    if value.startswith("p"):
        return "put"
    return None


def parse_symbol_strike(symbol):
    parts = symbol.split("-")
    if len(parts) >= 4:
        try:
            return float(parts[2])
        except (TypeError, ValueError):
            return None
    return None


def parse_symbol_type(symbol, fallback=None):
    if fallback:
        fallback = normalize_option_type(fallback)
        if fallback:
            return fallback
    parts = symbol.split("-")
    if len(parts) >= 4:
        return normalize_option_type(parts[3])
    return None


def parse_maturity(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def main():
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(output_dir, exist_ok=True)

    oi_history = {}
    max_pain = {}
    snapshot = {}
    trader = {}
    expiry_pressure = {}

    for asset, meta in ASSETS.items():
        underlying = f"{meta['spot_symbol']}USDT"

        oi_summary = load_binance_options_oi_summary(underlying)
        history = build_history(oi_summary if isinstance(oi_summary, list) else [])
        oi_history[asset] = history

        maturities = load_binance_oi_maturity(underlying)
        maturity_rows = maturities if isinstance(maturities, list) else []
        maturity_values = []
        for row in maturity_rows:
            maturity = row.get("Maturity") or row.get("maturity")
            parsed = parse_maturity(maturity)
            if parsed:
                maturity_values.append(parsed)
        maturity_values.sort()
        nearest_maturity = maturity_values[0].strftime("%Y-%m-%d") if maturity_values else None

        strikes = []
        expiry_totals = []
        if nearest_maturity:
            options_rows = load_binance_options_ohlc(underlying, nearest_maturity)
            options_rows = options_rows if isinstance(options_rows, list) else []
            latest_by_symbol = extract_latest_by_symbol(options_rows)

            for symbol, row in latest_by_symbol.items():
                strike = parse_symbol_strike(symbol)
                opt_type = parse_symbol_type(symbol, row.get("Type") or row.get("type"))
                oi = row.get("Open Interest Contracts") or row.get("open_interest_contracts")
                try:
                    oi_value = float(oi) if oi is not None else 0.0
                except (TypeError, ValueError):
                    oi_value = 0.0
                if strike and opt_type:
                    strikes.append({
                        "instrument_name": symbol,
                        "strike": strike,
                        "option_type": opt_type,
                        "open_interest": oi_value
                    })

        for row in maturity_rows:
            maturity = row.get("Maturity") or row.get("maturity")
            calls = row.get("Total Calls OI") or row.get("total_calls_oi") or 0
            puts = row.get("Total Puts OI") or row.get("total_puts_oi") or 0
            try:
                total = float(calls) + float(puts)
            except (TypeError, ValueError):
                total = 0.0
            if maturity:
                expiry_totals.append({"date": maturity, "total": total})

        avg_total = None
        if expiry_totals:
            avg_total = sum(item["total"] for item in expiry_totals) / len(expiry_totals)

        expiry_rows = []
        if expiry_totals and avg_total:
            for item in expiry_totals:
                expiry_rows.append({
                    "date": item["date"],
                    "asset": meta["spot_symbol"],
                    "notional": item["total"],
                    "delta_vs_avg": (item["total"] - avg_total) / avg_total,
                    "max_pain": None
                })
            expiry_rows.sort(key=lambda x: x["notional"], reverse=True)
            expiry_rows = expiry_rows[:5]

            for row in expiry_rows:
                options_rows = load_binance_options_ohlc(underlying, row["date"])
                options_rows = options_rows if isinstance(options_rows, list) else []
                latest_by_symbol = extract_latest_by_symbol(options_rows)
                expiry_strikes = []
                for symbol, opt_row in latest_by_symbol.items():
                    strike = parse_symbol_strike(symbol)
                    opt_type = parse_symbol_type(symbol, opt_row.get("Type") or opt_row.get("type"))
                    oi = opt_row.get("Open Interest Contracts") or opt_row.get("open_interest_contracts")
                    try:
                        oi_value = float(oi) if oi is not None else 0.0
                    except (TypeError, ValueError):
                        oi_value = 0.0
                    if strike and opt_type:
                        expiry_strikes.append({
                            "instrument_name": symbol,
                            "strike": strike,
                            "option_type": opt_type,
                            "open_interest": oi_value
                        })
                expiry_points = sorted({s["strike"] for s in expiry_strikes})
                best_expiry, _ = compute_max_pain(expiry_strikes, expiry_points)
                row["max_pain"] = best_expiry["strike"] if best_expiry else None

        expiry_pressure[asset] = expiry_rows

        price_points = sorted({s["strike"] for s in strikes})
        best, candidates = compute_max_pain(strikes, price_points)
        max_pain[asset] = {
            "expiry": nearest_maturity or "—",
            "max_pain": best["strike"] if best else None,
            "candidates": candidates
        }

        total_oi, call_oi, put_oi, put_call = aggregate_open_interest(strikes)

        if not strikes and nearest_maturity:
            for row in maturity_rows:
                maturity = row.get("Maturity") or row.get("maturity")
                if maturity == nearest_maturity:
                    calls = row.get("Total Calls OI") or row.get("total_calls_oi") or 0
                    puts = row.get("Total Puts OI") or row.get("total_puts_oi") or 0
                    try:
                        call_oi = float(calls)
                        put_oi = float(puts)
                        total_oi = call_oi + put_oi
                        put_call = (put_oi / call_oi) if call_oi else None
                    except (TypeError, ValueError):
                        pass
                    break

        oi_change = None
        if len(history) >= 2 and history[0]["open_interest"]:
            oi_change = (history[-1]["open_interest"] - history[0]["open_interest"]) / history[0]["open_interest"]

        spot_price = load_spot_price(underlying)

        snapshot[asset] = {
            "total_oi": total_oi,
            "oi_change_7d": oi_change,
            "put_call_ratio": put_call,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "atm_iv": None,
            "iv_term": None,
            "oi_concentration": None,
            "nearest_expiry_share": None,
            "spot_price": spot_price,
            "spot_source": "CryptoDataDownload"
        }

        trader[asset] = {
            "funding_rate": "—",
            "perp_basis": "—",
            "rv_iv": "—",
            "liquidations": "—"
        }

    with open(os.path.join(output_dir, "oi_history.json"), "w") as f:
        f.write(json.dumps(oi_history, indent=2))
    with open(os.path.join(output_dir, "max_pain.json"), "w") as f:
        f.write(json.dumps(max_pain, indent=2))
    with open(os.path.join(output_dir, "options_snapshot.json"), "w") as f:
        f.write(json.dumps(snapshot, indent=2))
    with open(os.path.join(output_dir, "trader_focus.json"), "w") as f:
        f.write(json.dumps(trader, indent=2))
    with open(os.path.join(output_dir, "expiry_pressure.json"), "w") as f:
        f.write(json.dumps(expiry_pressure, indent=2))
    with open(os.path.join(output_dir, "metadata.json"), "w") as f:
        meta = {
            "last_updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "sources": ["CryptoDataDownload"]
        }
        f.write(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
