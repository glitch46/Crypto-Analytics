#!/usr/bin/env python3
import datetime
import json
import math
import os
import urllib.parse
import urllib.request

# Free API endpoints (no API keys required)
BINANCE_API_BASE = "https://api.binance.com/api/v3"
BINANCE_FUTURES_BASE = "https://fapi.binance.com/fapi/v1"
DERIBIT_BASE = "https://www.deribit.com/api/v2/public"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

ASSETS = {
    "BTC": {
        "spot_symbol": "BTC"
    },
    "ETH": {
        "spot_symbol": "ETH"
    }
}

BACKTEST_MONTHS = 12


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_binance(path, params=None, base_url=None):
    """Fetch data from Binance Spot API (free, no auth required)"""
    if base_url is None:
        base_url = BINANCE_API_BASE
    query = urllib.parse.urlencode(params or {})
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{query}"
    return fetch_json(url)


def fetch_coingecko(path, params=None):
    """Fetch data from CoinGecko API (free tier, no auth required)"""
    query = urllib.parse.urlencode(params or {})
    url = f"{COINGECKO_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    return fetch_json(url)


def fetch_deribit(path, params=None):
    query = urllib.parse.urlencode(params or {})
    url = f"{DERIBIT_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    data = fetch_json(url)
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data


# Binance Options functions removed - Binance discontinued options trading in 2023
# All options data now comes from Deribit API


def load_spot_price(symbol):
    """Get current spot price from Binance Spot API (free)"""
    try:
        data = fetch_binance("/ticker/price", {"symbol": symbol})
        if isinstance(data, dict) and "price" in data:
            return float(data["price"])
    except Exception:
        pass
    # Fallback to CoinGecko
    try:
        coin_id = "bitcoin" if "BTC" in symbol else "ethereum"
        data = fetch_coingecko(f"/simple/price", {
            "ids": coin_id,
            "vs_currencies": "usd"
        })
        if isinstance(data, dict) and coin_id in data:
            return float(data[coin_id]["usd"])
    except Exception:
        pass
    return None


def load_spot_history(symbol, limit=450):
    """Get historical spot data from Binance Spot API (free, max 1000 candles)"""
    try:
        # Binance klines: [open_time, open, high, low, close, volume, close_time, ...]
        data = fetch_binance("/klines", {
            "symbol": symbol,
            "interval": "1d",
            "limit": min(limit, 1000)
        })
        if isinstance(data, list):
            result = []
            for candle in data:
                if len(candle) >= 6:
                    timestamp = int(candle[0]) / 1000
                    date = datetime.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
                    result.append({
                        "date": date,
                        "open": candle[1],
                        "high": candle[2],
                        "low": candle[3],
                        "close": candle[4],
                        "volume": candle[5]
                    })
            return result
    except Exception:
        pass
    return []


def load_deribit_instruments(currency):
    return fetch_deribit("/get_instruments", {
        "currency": currency,
        "kind": "option"
    })


def load_deribit_settlements(currency, settlement_type="delivery", count=1000, continuation=None):
    params = {
        "currency": currency,
        "type": settlement_type,
        "count": count
    }
    if continuation:
        params["continuation"] = continuation
    return fetch_deribit("/get_last_settlements_by_currency", params)


def load_deribit_book_summary(currency):
    return fetch_deribit("/get_book_summary_by_currency", {
        "currency": currency,
        "kind": "option"
    })


def load_deribit_funding(symbol):
    """Get funding rate history from Deribit public API (free)"""
    try:
        data = fetch_deribit("/get_funding_rate_history", {
            "instrument_name": symbol,
            "count": 3
        })
        if isinstance(data, list):
            # Convert to CDD-like format for compatibility
            result = []
            for item in data:
                result.append({
                    "timestamp": item.get("timestamp"),
                    "interest_8h": item.get("interest_8h"),
                    "index_price": item.get("index_price")
                })
            return result
    except Exception:
        pass
    return []


def load_deribit_volatility(symbol, limit=30):
    """Get volatility index from Deribit public API (free)"""
    try:
        # Get historical volatility index data
        data = fetch_deribit("/get_volatility_index_data", {
            "currency": symbol,
            "resolution": "1D",
            "count": limit
        })
        if isinstance(data, dict) and "data" in data:
            # Convert to CDD-like format
            result = []
            for item in data["data"]:
                if len(item) >= 2:
                    timestamp = item[0]
                    volatility = item[1]
                    result.append({
                        "timestamp": timestamp,
                        "close": volatility
                    })
            return result
    except Exception:
        pass
    return []


def load_binance_basis(symbol, limit=2):
    """Calculate basis from Binance Futures and Spot prices (free)"""
    try:
        # Get spot price
        spot_data = fetch_binance("/ticker/price", {"symbol": symbol})
        spot_price = float(spot_data["price"]) if spot_data else None
        
        # Get futures price
        futures_symbol = symbol.replace("USDT", "") + "USDT"  # Ensure proper format
        futures_data = fetch_binance("/ticker/price", 
                                     {"symbol": futures_symbol}, 
                                     base_url=BINANCE_FUTURES_BASE)
        futures_price = float(futures_data["price"]) if futures_data else None
        
        if spot_price and futures_price:
            basis = futures_price - spot_price
            return [{"basis": basis, "spot": spot_price, "futures": futures_price}]
    except Exception:
        pass
    return []


def compute_max_pain(strikes, price_points):
    best = None
    candidates = []
    if not strikes or not price_points:
        return best, candidates
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
    if len(history) < 30:
        today = datetime.date.today()
        for i in range(30 - len(history)):
            day = today - datetime.timedelta(days=(29 - len(history) - i))
            history.insert(0, {"date": day.strftime("%Y-%m-%d"), "open_interest": 0})
    return history[-30:]


def extract_latest_by_symbol(options_rows):
    latest = {}
    for row in options_rows:
        symbol = row.get("symbol") or row.get("Symbol")
        if not symbol:
            continue
        date = row.get("date") or row.get("Date") or ""
        hour = row.get("hour") or row.get("Hour") or ""
        stamp = f"{date} {hour}".strip()
        existing = latest.get(symbol)
        if not existing or stamp > existing.get("_stamp", ""):
            row["_stamp"] = stamp
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


def parse_deribit_expiry_date(value):
    try:
        return datetime.datetime.strptime(value, "%d%b%y").date()
    except (ValueError, TypeError):
        return None


def parse_deribit_option_expiry(instrument_name):
    if not instrument_name:
        return None
    parts = instrument_name.split("-")
    if len(parts) < 4:
        return None
    return parse_deribit_expiry_date(parts[1])


def is_deribit_option(instrument_name):
    if not instrument_name:
        return False
    parts = instrument_name.split("-")
    if len(parts) < 4:
        return False
    return normalize_option_type(parts[-1]) is not None


def extract_latest_by_symbol_before(options_rows, cutoff_date):
    latest = {}
    if isinstance(cutoff_date, str):
        cutoff_date = parse_maturity(cutoff_date)
    for row in options_rows:
        date = row.get("date") or row.get("Date")
        if not date:
            continue
        row_date = parse_maturity(date)
        if not row_date or (cutoff_date and row_date > cutoff_date):
            continue
        symbol = row.get("symbol") or row.get("Symbol")
        if not symbol:
            continue
        hour = row.get("hour") or row.get("Hour") or ""
        stamp = f"{date} {hour}".strip()
        existing = latest.get(symbol)
        if not existing or stamp > existing.get("_stamp", ""):
            row["_stamp"] = stamp
            latest[symbol] = row
    return latest


def collect_settlement_prices(currency, cutoff_date):
    settlements = []
    continuation = None
    while True:
        data = load_deribit_settlements(currency, "delivery", 1000, continuation)
        if not isinstance(data, dict):
            break
        rows = data.get("settlements", [])
        if not rows:
            break
        stop = False
        for row in rows:
            ts = row.get("timestamp")
            if not ts:
                continue
            event_date = datetime.datetime.utcfromtimestamp(ts / 1000).date()
            if cutoff_date and event_date < cutoff_date:
                stop = True
                break
            settlements.append(row)
        continuation = data.get("continuation")
        if stop or not continuation:
            break
    return settlements


def pick_monthly_expiries(expiry_prices, months=12):
    monthly = {}
    for expiry_date in sorted(expiry_prices.keys(), reverse=True):
        month_key = expiry_date.strftime("%Y-%m")
        if month_key not in monthly:
            monthly[month_key] = expiry_date
        if len(monthly) >= months:
            break
    return sorted(monthly.values())


def get_spot_on_or_before(price_map, target_date, max_lookback=10):
    for offset in range(max_lookback + 1):
        candidate = target_date - datetime.timedelta(days=offset)
        if candidate in price_map:
            return price_map[candidate]
    return None


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_daily_prices(rows, max_days=1095):
    prices = []
    for row in rows:
        date_value = row.get("date") or row.get("Date")
        open_value = row.get("open") if row.get("open") is not None else row.get("Open")
        high_value = row.get("high") if row.get("high") is not None else row.get("High")
        low_value = row.get("low") if row.get("low") is not None else row.get("Low")
        close_value = row.get("close") or row.get("Close")
        if not date_value:
            continue
        parsed = parse_maturity(date_value)
        if parsed is None:
            continue
        open_price = parse_float(open_value)
        high_price = parse_float(high_value)
        low_price = parse_float(low_value)
        close_price = parse_float(close_value)
        if close_price is None:
            continue
        if open_price is None:
            open_price = close_price
        if high_price is None:
            high_price = max(open_price, close_price)
        if low_price is None:
            low_price = min(open_price, close_price)
        prices.append({
            "date": parsed.strftime("%Y-%m-%d"),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price
        })
    prices.sort(key=lambda x: x["date"])
    if max_days and len(prices) > max_days:
        prices = prices[-max_days:]
    return prices


def compute_rsi(values, period=14):
    if len(values) <= period:
        return []
    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rsi_values = []
    for _ in range(period):
        rsi_values.append(None)
    for i in range(period, len(values)):
        if i > period:
            delta = values[i] - values[i - 1]
            gain = max(delta, 0)
            loss = max(-delta, 0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = avg_gain / avg_loss if avg_loss else None
        rsi = 100 - (100 / (1 + rs)) if rs is not None else 100
        rsi_values.append(rsi)
    return rsi_values


def compute_weekly_rsi(daily_prices, period=14):
    weekly = []
    week_map = {}
    for entry in daily_prices:
        parsed = parse_maturity(entry["date"])
        if not parsed:
            continue
        week_key = f"{parsed.isocalendar().year}-{parsed.isocalendar().week:02d}"
        week_map[week_key] = entry
    for key in sorted(week_map.keys()):
        weekly.append(week_map[key])
    closes = [row["close"] for row in weekly]
    rsi_series = compute_rsi(closes, period)
    result = []
    for idx, row in enumerate(weekly):
        rsi = rsi_series[idx] if idx < len(rsi_series) else None
        result.append({"date": row["date"], "rsi": rsi})
    return result


def compute_daily_rsi(daily_prices, period=14):
    closes = [row["close"] for row in daily_prices]
    rsi_series = compute_rsi(closes, period)
    result = []
    for idx, row in enumerate(daily_prices):
        rsi = rsi_series[idx] if idx < len(rsi_series) else None
        result.append({"date": row["date"], "rsi": rsi})
    return result


def _meeus_new_moon_jde(k):
    T = k / 1236.85
    T2 = T * T
    T3 = T2 * T
    T4 = T3 * T
    JDE = (2451550.09766 + 29.530588861 * k
           + 0.00015437 * T2 - 0.000000150 * T3 + 0.00000000073 * T4)
    E = 1 - 0.002516 * T - 0.0000074 * T2
    M = math.radians(2.5534 + 29.10535670 * k - 0.0000014 * T2 - 0.00000011 * T3)
    Mp = math.radians(201.5643 + 385.81693528 * k + 0.0107582 * T2 + 0.00001238 * T3 - 0.000000058 * T4)
    F = math.radians(160.7108 + 390.67050284 * k - 0.0016118 * T2 - 0.00000227 * T3 + 0.000000011 * T4)
    O = math.radians(124.7746 - 1.56375588 * k + 0.0020672 * T2 + 0.00000215 * T3)
    corr = (
        -0.40720 * math.sin(Mp) + 0.17241 * E * math.sin(M) + 0.01608 * math.sin(2 * Mp)
        + 0.01039 * math.sin(2 * F) + 0.00739 * E * math.sin(Mp - M) - 0.00514 * E * math.sin(Mp + M)
        + 0.00208 * E * E * math.sin(2 * M) - 0.00111 * math.sin(Mp - 2 * F) - 0.00057 * math.sin(Mp + 2 * F)
        + 0.00056 * E * math.sin(2 * Mp + M) - 0.00042 * math.sin(3 * Mp) + 0.00042 * E * math.sin(M + 2 * F)
        + 0.00038 * E * math.sin(M - 2 * F) - 0.00024 * E * math.sin(2 * Mp - M) - 0.00017 * math.sin(O)
        - 0.00007 * math.sin(Mp + 2 * M) + 0.00004 * math.sin(2 * Mp - 2 * F) + 0.00004 * math.sin(3 * M)
        + 0.00003 * math.sin(Mp + M - 2 * F) + 0.00003 * math.sin(2 * Mp + 2 * F)
        - 0.00003 * math.sin(Mp + M + 2 * F) + 0.00003 * math.sin(Mp - M + 2 * F)
        - 0.00002 * math.sin(Mp - M - 2 * F) - 0.00002 * math.sin(3 * Mp + M) + 0.00002 * math.sin(4 * Mp)
    )
    return JDE + corr


def _meeus_full_moon_jde(k):
    k = k + 0.5
    T = k / 1236.85
    T2 = T * T
    T3 = T2 * T
    T4 = T3 * T
    JDE = (2451550.09766 + 29.530588861 * k
           + 0.00015437 * T2 - 0.000000150 * T3 + 0.00000000073 * T4)
    E = 1 - 0.002516 * T - 0.0000074 * T2
    M = math.radians(2.5534 + 29.10535670 * k - 0.0000014 * T2 - 0.00000011 * T3)
    Mp = math.radians(201.5643 + 385.81693528 * k + 0.0107582 * T2 + 0.00001238 * T3 - 0.000000058 * T4)
    F = math.radians(160.7108 + 390.67050284 * k - 0.0016118 * T2 - 0.00000227 * T3 + 0.000000011 * T4)
    O = math.radians(124.7746 - 1.56375588 * k + 0.0020672 * T2 + 0.00000215 * T3)
    corr = (
        -0.40614 * math.sin(Mp) + 0.17302 * E * math.sin(M) + 0.01614 * math.sin(2 * Mp)
        + 0.01043 * math.sin(2 * F) + 0.00734 * E * math.sin(Mp - M) - 0.00515 * E * math.sin(Mp + M)
        + 0.00209 * E * E * math.sin(2 * M) - 0.00111 * math.sin(Mp - 2 * F) - 0.00057 * math.sin(Mp + 2 * F)
        + 0.00056 * E * math.sin(2 * Mp + M) - 0.00042 * math.sin(3 * Mp) + 0.00042 * E * math.sin(M + 2 * F)
        + 0.00038 * E * math.sin(M - 2 * F) - 0.00024 * E * math.sin(2 * Mp - M) - 0.00017 * math.sin(O)
        - 0.00007 * math.sin(Mp + 2 * M) + 0.00004 * math.sin(2 * Mp - 2 * F) + 0.00004 * math.sin(3 * M)
        + 0.00003 * math.sin(Mp + M - 2 * F) + 0.00003 * math.sin(2 * Mp + 2 * F)
        - 0.00003 * math.sin(Mp + M + 2 * F) + 0.00003 * math.sin(Mp - M + 2 * F)
        - 0.00002 * math.sin(Mp - M - 2 * F) - 0.00002 * math.sin(3 * Mp + M) + 0.00002 * math.sin(4 * Mp)
    )
    return JDE + corr


def _jde_to_date(jde):
    jde += 0.5
    Z = int(jde)
    F = jde - Z
    if Z < 2299161:
        A = Z
    else:
        alpha = int((Z - 1867216.25) / 36524.25)
        A = Z + 1 + alpha - int(alpha / 4)
    B = A + 1524
    C = int((B - 122.1) / 365.25)
    D = int(365.25 * C)
    E = int((B - D) / 30.6001)
    day = B - D - int(30.6001 * E)
    month = E - 1 if E < 14 else E - 13
    year = C - 4716 if month > 2 else C - 4715
    return datetime.date(year, month, day)


def compute_lunar_events(start_date, end_date):
    events = []
    k_approx = (start_date.year + start_date.month / 12.0 - 2000) * 12.3685
    k_start = int(k_approx) - 2
    for i in range(200):
        k = k_start + i
        jde_new = _meeus_new_moon_jde(k)
        d_new = _jde_to_date(jde_new)
        if start_date <= d_new <= end_date:
            events.append({"date": d_new.strftime("%Y-%m-%d"), "type": "new"})
        jde_full = _meeus_full_moon_jde(k)
        d_full = _jde_to_date(jde_full)
        if start_date <= d_full <= end_date:
            events.append({"date": d_full.strftime("%Y-%m-%d"), "type": "full"})
        if d_new > end_date and d_full > end_date:
            break
    events.sort(key=lambda x: x["date"])
    return events


def build_strikes_from_settlements(settlement_rows, expiry_date):
    strikes = []
    for row in settlement_rows:
        instrument = row.get("instrument_name", "")
        exp = parse_deribit_option_expiry(instrument)
        if exp != expiry_date:
            continue
        strike = parse_symbol_strike(instrument)
        parts = instrument.split("-")
        opt_type = normalize_option_type(parts[-1]) if len(parts) >= 4 else None
        oi = abs(parse_float(row.get("position")) or 0.0)
        if strike and opt_type and oi > 0:
            strikes.append({
                "instrument_name": instrument,
                "strike": strike,
                "option_type": opt_type,
                "open_interest": oi
            })
    return strikes


def within_forward_window(date_value, days=90, start_offset=1):
    if not date_value:
        return False
    today = datetime.date.today()
    start = today + datetime.timedelta(days=start_offset)
    end = today + datetime.timedelta(days=days)
    return start <= date_value <= end


def filter_strikes_by_spot(strikes, spot_price, min_mult=0.5, max_mult=2.0):
    if not spot_price:
        return strikes
    lower = spot_price * min_mult
    upper = spot_price * max_mult
    filtered = [s for s in strikes if lower <= s.get("strike", 0) <= upper and (s.get("open_interest", 0) or 0) > 0]
    return filtered if filtered else strikes


def load_existing_oi_history(output_dir):
    path = os.path.join(output_dir, "oi_history.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.loads(f.read())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def main():
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(output_dir, exist_ok=True)

    existing_oi = load_existing_oi_history(output_dir)
    oi_history = {}
    max_pain = {}
    snapshot = {}
    trader = {}
    expiry_pressure = {}
    backtest = {}
    strategy_data = {}

    for asset, meta in ASSETS.items():
        underlying = f"{meta['spot_symbol']}USDT"

        # Load previous OI history for this asset (accumulate across runs)
        prev_history = existing_oi.get(asset, [])
        prev_map = {item["date"]: item["open_interest"] for item in prev_history if item.get("date")}

        # We'll compute today's Deribit total OI after fetching book summary below
        # For now, store prev_map and fill history after we have deribit_summary
        oi_history[asset] = prev_map  # temporary, replaced below

        spot_price = load_spot_price(underlying)
        spot_history = load_spot_history(underlying, 1300)
        spot_history = spot_history if isinstance(spot_history, list) else []
        spot_map = {}
        for row in spot_history:
            date_value = row.get("date") or row.get("Date")
            close_value = row.get("close") or row.get("Close")
            if not date_value:
                continue
            parsed = parse_maturity(date_value)
            if parsed is None:
                continue
            close_price = parse_float(close_value)
            if close_price is not None:
                spot_map[parsed] = close_price

        if asset == "BTC":
            daily_prices = build_daily_prices(spot_history, 1095)
            if daily_prices:
                start_date = parse_maturity(daily_prices[0]["date"])
                end_date = parse_maturity(daily_prices[-1]["date"])
            else:
                start_date = None
                end_date = None
            weekly_rsi = compute_weekly_rsi(daily_prices, 14)
            daily_rsi = compute_daily_rsi(daily_prices, 14)
            lunar_events = compute_lunar_events(start_date, end_date) if start_date and end_date else []
            price_lookup = {row["date"]: row["close"] for row in daily_prices}
            for event in lunar_events:
                event["close"] = price_lookup.get(event["date"])
            strategy_data = {
                "prices": daily_prices,
                "weekly_rsi": weekly_rsi,
                "daily_rsi": daily_rsi,
                "lunar_events": lunar_events
            }

        # Binance Options removed (discontinued in 2023) - using Deribit only
        strikes = []
        deribit_strikes = []
        expiry_strikes_map = {}
        total_oi_usd = 0.0
        total_oi_base = 0.0
        call_oi_usd = 0.0
        put_oi_usd = 0.0
        nearest_oi_usd = 0.0
        oi_total_by_expiry = {}
        oi_usd_by_expiry = {}
        calls_usd_by_expiry = {}
        puts_usd_by_expiry = {}

        deribit_instruments = load_deribit_instruments(meta["spot_symbol"])
        deribit_instruments = deribit_instruments if isinstance(deribit_instruments, list) else []
        deribit_instruments = [i for i in deribit_instruments if within_forward_window(
            datetime.date.fromtimestamp(i.get("expiration_timestamp", 0) / 1000),
            90
        )]
        expiry_ts_values = sorted({i["expiration_timestamp"] for i in deribit_instruments})
        nearest_deribit_ts = expiry_ts_values[0] if expiry_ts_values else None
        nearest_deribit_expiry = None
        if nearest_deribit_ts:
            nearest_deribit_expiry = datetime.datetime.utcfromtimestamp(nearest_deribit_ts / 1000).strftime("%Y-%m-%d")

        deribit_summary = load_deribit_book_summary(meta["spot_symbol"])
        deribit_summary = deribit_summary if isinstance(deribit_summary, list) else []
        summary_map = {row.get("instrument_name"): row for row in deribit_summary}
        for inst in deribit_instruments:
            expiry_date = datetime.date.fromtimestamp(inst.get("expiration_timestamp", 0) / 1000)
            if inst.get("expiration_timestamp") != nearest_deribit_ts:
                pass
            row = summary_map.get(inst.get("instrument_name"))
            if not row:
                continue
            try:
                oi_value = float(row.get("open_interest", 0) or 0)
            except (TypeError, ValueError):
                oi_value = 0.0
            try:
                oi_value_usd = float(row.get("open_interest_usd", 0) or 0)
            except (TypeError, ValueError):
                oi_value_usd = 0.0
            if oi_value_usd == 0.0 and spot_price:
                oi_value_usd = oi_value * spot_price
            strike_entry = {
                "instrument_name": inst.get("instrument_name"),
                "strike": float(inst.get("strike", 0) or 0),
                "option_type": inst.get("option_type"),
                "open_interest": oi_value
            }
            if inst.get("expiration_timestamp") == nearest_deribit_ts:
                deribit_strikes.append(strike_entry)
                nearest_oi_usd += oi_value_usd
            if inst.get("option_type") == "call":
                call_oi_usd += oi_value_usd
            elif inst.get("option_type") == "put":
                put_oi_usd += oi_value_usd
            expiry_key = expiry_date.strftime("%Y-%m-%d")
            expiry_strikes_map.setdefault(expiry_key, []).append(strike_entry)
            oi_total_by_expiry[expiry_key] = oi_total_by_expiry.get(expiry_key, 0.0) + oi_value
            oi_usd_by_expiry[expiry_key] = oi_usd_by_expiry.get(expiry_key, 0.0) + oi_value_usd
            if inst.get("option_type") == "call":
                calls_usd_by_expiry[expiry_key] = calls_usd_by_expiry.get(expiry_key, 0.0) + oi_value_usd
            elif inst.get("option_type") == "put":
                puts_usd_by_expiry[expiry_key] = puts_usd_by_expiry.get(expiry_key, 0.0) + oi_value_usd
            total_oi_usd += oi_value_usd
            total_oi_base += oi_value

        expiry_totals = []
        for expiry_key in expiry_strikes_map.keys():
            total = oi_usd_by_expiry.get(expiry_key, 0.0)
            expiry_totals.append({"date": expiry_key, "total": total})

        combined_strikes = strikes + deribit_strikes
        combined_strikes = filter_strikes_by_spot(combined_strikes, spot_price, 0.7, 1.3)

        expiry_rows = []
        if expiry_totals:
            top_contracts = sorted(
                [
                    {
                        "expiry": key,
                        "open_interest_usd": oi_usd_by_expiry.get(key, 0.0),
                        "strike_rows": expiry_strikes_map.get(key, [])
                    }
                    for key in expiry_strikes_map.keys()
                ],
                key=lambda x: x["open_interest_usd"],
                reverse=True
            )
            top_contracts = top_contracts[:10]

            filtered_expiry_totals = [
                {"date": item["expiry"], "total": item["open_interest_usd"]}
                for item in top_contracts
            ]

            avg_total = sum(item["total"] for item in filtered_expiry_totals) / len(filtered_expiry_totals)
            for item in filtered_expiry_totals:
                calls_usd = calls_usd_by_expiry.get(item["date"], 0.0)
                puts_usd = puts_usd_by_expiry.get(item["date"], 0.0)
                expiry_rows.append({
                    "date": item["date"],
                    "asset": meta["spot_symbol"],
                    "notional": item["total"],
                    "delta_vs_avg": (item["total"] - avg_total) / avg_total,
                    "max_pain": None,
                    "calls_usd": calls_usd,
                    "puts_usd": puts_usd
                })
            expiry_rows.sort(key=lambda x: x["notional"], reverse=True)
            expiry_rows = expiry_rows[:5]

            for erow in expiry_rows:
                expiry_strikes = expiry_strikes_map.get(erow["date"], [])
                expiry_strikes = filter_strikes_by_spot(expiry_strikes, spot_price, 0.7, 1.3)
                expiry_points = sorted({s["strike"] for s in expiry_strikes})
                best_expiry, _ = compute_max_pain(expiry_strikes, expiry_points)
                erow["max_pain"] = best_expiry["strike"] if best_expiry else None

        expiry_pressure[asset] = expiry_rows

        price_points = sorted({s["strike"] for s in combined_strikes})
        best, candidates = compute_max_pain(combined_strikes, price_points)
        max_pain[asset] = {
            "peak_expiry": expiry_rows[0]["date"] if expiry_rows else "—",
            "peak_notional": expiry_rows[0]["notional"] if expiry_rows else None,
            "max_pain": best["strike"] if best else None,
            "candidates": candidates
        }

        total_oi, call_oi, put_oi, put_call = aggregate_open_interest(combined_strikes)

        # Use Deribit USD-denominated values if available
        if call_oi_usd or put_oi_usd:
            call_oi = call_oi_usd
            put_oi = put_oi_usd
            put_call = (put_oi_usd / call_oi_usd) if call_oi_usd else None

        if not total_oi_usd and spot_price:
            total_oi_usd = total_oi_base * spot_price
        if total_oi_usd:
            total_oi = total_oi_usd

        # Build rolling OI history from Deribit total OI
        prev_map = oi_history.get(asset, {})
        if isinstance(prev_map, list):
            prev_map = {item["date"]: item["open_interest"] for item in prev_map if item.get("date")}
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        prev_map[today_str] = total_oi_usd or total_oi or 0
        # Remove entries older than 35 days to keep file small but retain 30 days of history
        cutoff_oi = (datetime.date.today() - datetime.timedelta(days=35)).strftime("%Y-%m-%d")
        prev_map = {k: v for k, v in prev_map.items() if k >= cutoff_oi}
        history = sorted([{"date": k, "open_interest": v} for k, v in prev_map.items()], key=lambda x: x["date"])
        if len(history) < 30:
            last_value = history[-1]["open_interest"] if history else total_oi_usd or total_oi or 0
            today = datetime.date.today()
            history_map = {item["date"]: item["open_interest"] for item in history}
            padded = []
            for offset in range(29, -1, -1):
                day = (today - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
                padded.append({"date": day, "open_interest": history_map.get(day, last_value)})
            history = padded
        else:
            history = history[-30:]
        oi_history[asset] = history

        oi_change = None
        if len(history) >= 2 and history[0]["open_interest"]:
            oi_change = (history[-1]["open_interest"] - history[0]["open_interest"]) / history[0]["open_interest"]

        basis_rows = load_binance_basis(underlying, 2)
        basis_rows = basis_rows if isinstance(basis_rows, list) else []
        perp_basis = None
        if basis_rows:
            try:
                perp_basis = float(basis_rows[0].get("basis", 0))
            except (TypeError, ValueError):
                perp_basis = None

        funding_rows = load_deribit_funding(f"{meta['spot_symbol']}-PERPETUAL")
        funding_rows = funding_rows if isinstance(funding_rows, list) else []
        funding_rate = None
        if funding_rows:
            try:
                funding_rate = float(funding_rows[0].get("interest_8h"))
            except (TypeError, ValueError):
                funding_rate = None

        vol_rows = load_deribit_volatility(meta["spot_symbol"], 30)
        vol_rows = vol_rows if isinstance(vol_rows, list) else []
        iv_7d = None
        iv_30d = None
        if vol_rows:
            try:
                iv_7d = float(vol_rows[0].get("close"))
            except (TypeError, ValueError):
                iv_7d = None
            if len(vol_rows) >= 7:
                try:
                    iv_30d = float(vol_rows[min(29, len(vol_rows) - 1)].get("close"))
                except (TypeError, ValueError):
                    iv_30d = None
        iv_term = None
        if iv_7d and iv_30d:
            iv_term = f"{iv_7d:.1f}% / {iv_30d:.1f}%"

        # Greeks calculation removed - CDD endpoint no longer available
        # Using simple IV from Deribit volatility index instead
        latest_greeks_date = None

        oi_concentration = None
        nearest_share = None
        if oi_total_by_expiry:
            totals = sorted(oi_total_by_expiry.values(), reverse=True)
            top5 = sum(totals[:5])
            total_sum = sum(totals)
            if total_sum:
                oi_concentration = top5 / total_sum
                if nearest_deribit_expiry and nearest_deribit_expiry in oi_total_by_expiry:
                    nearest_share = oi_total_by_expiry[nearest_deribit_expiry] / total_sum

        rv_iv = None
        # Calculate simple RV/IV ratio using volatility index
        if iv_7d and iv_30d:
            rv_iv = f"{iv_7d:.1f}% / {iv_30d:.1f}%"

        snapshot[asset] = {
            "total_oi": total_oi,
            "oi_change_7d": oi_change,
            "put_call_ratio": put_call,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "atm_iv": iv_7d / 100 if iv_7d else None,
            "iv_term": iv_term,
            "oi_concentration": oi_concentration,
            "nearest_expiry_share": nearest_share,
            "spot_price": spot_price,
            "spot_source": "Binance"
        }

        trader[asset] = {
            "funding_rate": f"{funding_rate * 100:.4f}%" if funding_rate is not None else "—",
            "perp_basis": f"${perp_basis:.2f}" if perp_basis is not None else "—",
            "rv_iv": rv_iv or "—",
            "sources": "Deribit + Binance"
        }

        cutoff_date = datetime.date.today() - datetime.timedelta(days=365)
        settlements = collect_settlement_prices(meta["spot_symbol"], cutoff_date)
        expiry_prices = {}
        for row in settlements:
            instrument = row.get("instrument_name")
            if not is_deribit_option(instrument):
                continue
            expiry_date = parse_deribit_option_expiry(instrument)
            if not expiry_date or expiry_date < cutoff_date:
                continue
            price = parse_float(row.get("index_price"))
            if price is None:
                continue
            expiry_prices.setdefault(expiry_date, []).append(price)
        expiry_prices = {
            date_key: sum(values) / len(values)
            for date_key, values in expiry_prices.items()
            if values
        }

        monthly_expiries = pick_monthly_expiries(expiry_prices, BACKTEST_MONTHS)
        backtest_rows = []
        win_total = 0
        win_hits = 0
        puts_over_calls = 0
        max_pain_devs = []

        for expiry_date in monthly_expiries:
            bt_strikes = build_strikes_from_settlements(settlements, expiry_date)
            if not bt_strikes:
                continue
            _, bt_call_oi, bt_put_oi, bt_put_call = aggregate_open_interest(bt_strikes)
            bt_price_points = sorted({s["strike"] for s in bt_strikes})
            bt_best, _ = compute_max_pain(bt_strikes, bt_price_points)
            bt_max_pain = bt_best["strike"] if isinstance(bt_best, dict) else None

            settlement_price = expiry_prices.get(expiry_date)
            spot_30d = get_spot_on_or_before(spot_map, expiry_date - datetime.timedelta(days=30))
            spot_expiry = get_spot_on_or_before(spot_map, expiry_date)

            price_change = None
            price_change_pct = None
            outcome_direction = "flat"
            if settlement_price is not None and spot_30d is not None:
                price_change = settlement_price - spot_30d
                if spot_30d:
                    price_change_pct = price_change / spot_30d
                if price_change > 0:
                    outcome_direction = "up"
                elif price_change < 0:
                    outcome_direction = "down"

            skew_direction = "flat"
            if bt_put_call is not None:
                if bt_put_call > 1:
                    skew_direction = "down"
                elif bt_put_call < 1:
                    skew_direction = "up"
            skew_followed = False
            if skew_direction != "flat" and outcome_direction != "flat":
                win_total += 1
                skew_followed = skew_direction == outcome_direction
                if skew_followed:
                    win_hits += 1

            if bt_put_call is not None and bt_put_call > 1:
                puts_over_calls += 1

            bt_max_pain_dev = None
            bt_max_pain_dev_pct = None
            if settlement_price is not None and bt_max_pain:
                bt_max_pain_dev = settlement_price - bt_max_pain
                if settlement_price:
                    bt_max_pain_dev_pct = abs(bt_max_pain_dev) / settlement_price
                if bt_max_pain_dev_pct is not None:
                    max_pain_devs.append(bt_max_pain_dev_pct)

            backtest_rows.append({
                "month": expiry_date.strftime("%Y-%m"),
                "expiry": expiry_date.strftime("%Y-%m-%d"),
                "settlement_price": settlement_price,
                "spot_30d": spot_30d,
                "spot_expiry": spot_expiry,
                "put_call": bt_put_call,
                "call_oi": bt_call_oi,
                "put_oi": bt_put_oi,
                "max_pain": bt_max_pain,
                "max_pain_dev": bt_max_pain_dev,
                "max_pain_dev_pct": bt_max_pain_dev_pct,
                "price_change": price_change,
                "price_change_pct": price_change_pct,
                "skew_direction": skew_direction,
                "outcome_direction": outcome_direction,
                "skew_followed": skew_followed
            })

        backtest_rows.sort(key=lambda x: x["expiry"])
        win_rate = (win_hits / win_total) if win_total else None
        avg_max_pain_dev = (sum(max_pain_devs) / len(max_pain_devs)) if max_pain_devs else None

        backtest[asset] = {
            "summary": {
                "win_rate": win_rate,
                "months": len(backtest_rows),
                "puts_over_calls": puts_over_calls,
                "avg_max_pain_dev": avg_max_pain_dev
            },
            "months": backtest_rows
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
    with open(os.path.join(output_dir, "backtest.json"), "w") as f:
        f.write(json.dumps(backtest, indent=2))
    if strategy_data:
        with open(os.path.join(output_dir, "strategy_signals.json"), "w") as f:
            f.write(json.dumps(strategy_data, indent=2))
    with open(os.path.join(output_dir, "metadata.json"), "w") as f:
        meta = {
            "last_updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "sources": ["Binance", "Deribit"]
        }
        f.write(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
