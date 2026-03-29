#!/usr/bin/env python3
import datetime
import json
import os
import time
import urllib.parse
import urllib.request

# Free API endpoints (no API keys required)
BINANCE_API_BASE = "https://api.binance.com/api/v3"
BINANCE_FUTURES_BASE = "https://fapi.binance.com/fapi/v1"
DERIBIT_BASE = "https://www.deribit.com/api/v2/public"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum"}

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
    """Get current spot price.  Deribit index first, then CoinGecko, then Binance."""
    try:
        currency = symbol.replace("USDT", "")
        data = fetch_deribit("/get_index_price", {"index_name": f"{currency.lower()}_usd"})
        if isinstance(data, dict) and "index_price" in data:
            return float(data["index_price"])
    except Exception:
        pass
    try:
        coin_id = COINGECKO_IDS.get(symbol.replace("USDT", ""), "bitcoin")
        data = fetch_coingecko("/simple/price", {"ids": coin_id, "vs_currencies": "usd"})
        if isinstance(data, dict) and coin_id in data:
            return float(data[coin_id]["usd"])
    except Exception:
        pass
    try:
        data = fetch_binance("/ticker/price", {"symbol": symbol})
        if isinstance(data, dict) and "price" in data:
            return float(data["price"])
    except Exception:
        pass
    return None


def load_deribit_instruments(currency):
    return fetch_deribit("/get_instruments", {
        "currency": currency,
        "kind": "option"
    })


def load_deribit_book_summary(currency):
    return fetch_deribit("/get_book_summary_by_currency", {
        "currency": currency,
        "kind": "option"
    })


def load_deribit_funding(symbol):
    """Get funding rate history from Deribit public API (free).
    Requires start_timestamp / end_timestamp."""
    try:
        now = int(time.time() * 1000)
        day_ms = 86400 * 1000
        data = fetch_deribit("/get_funding_rate_history", {
            "instrument_name": symbol,
            "start_timestamp": now - 3 * day_ms,
            "end_timestamp": now
        })
        if isinstance(data, list):
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
    """Get volatility index from Deribit public API (free).
    Requires start_timestamp / end_timestamp."""
    try:
        now = int(time.time() * 1000)
        day_ms = 86400 * 1000
        data = fetch_deribit("/get_volatility_index_data", {
            "currency": symbol,
            "resolution": "1D",
            "start_timestamp": now - limit * day_ms,
            "end_timestamp": now
        })
        if isinstance(data, dict) and "data" in data:
            result = []
            for item in data["data"]:
                if len(item) >= 5:
                    result.append({
                        "timestamp": item[0],
                        "close": item[4]
                    })
            return result
    except Exception:
        pass
    return []


def load_binance_basis(symbol, limit=2):
    """Calculate perp-vs-spot basis using Deribit (primary) or Binance (fallback)."""
    currency = symbol.replace("USDT", "")
    try:
        perp = f"{currency}-PERPETUAL"
        ticker = fetch_deribit("/ticker", {"instrument_name": perp})
        if isinstance(ticker, dict):
            mark = ticker.get("mark_price")
            index = ticker.get("index_price")
            if mark and index:
                basis = float(mark) - float(index)
                return [{"basis": basis, "spot": float(index), "futures": float(mark)}]
    except Exception:
        pass
    try:
        spot_data = fetch_binance("/ticker/price", {"symbol": symbol})
        spot_price = float(spot_data["price"]) if spot_data else None
        futures_data = fetch_binance("/ticker/price",
                                     {"symbol": symbol},
                                     base_url=BINANCE_FUTURES_BASE)
        futures_price = float(futures_data["price"]) if futures_data else None
        if spot_price and futures_price:
            return [{"basis": futures_price - spot_price, "spot": spot_price, "futures": futures_price}]
    except Exception:
        pass
    return []


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

    for asset, meta in ASSETS.items():
        underlying = f"{meta['spot_symbol']}USDT"

        # Binance Options removed (discontinued in 2023) - using Deribit only
        spot_price = load_spot_price(underlying)

        # Load previous OI history for this asset (accumulate across runs)
        prev_history = existing_oi.get(asset, [])
        prev_map = {item["date"]: item["open_interest"] for item in prev_history if item.get("date")}
        
        # We'll compute today's Deribit total OI after fetching book summary below
        # For now, store prev_map and fill history after we have deribit_summary
        oi_history[asset] = prev_map  # temporary, replaced below

        strikes = []
        deribit_strikes = []
        expiry_strikes_map = {}
        total_oi_usd = 0.0
        total_oi_base = 0.0
        binance_oi_usd = 0.0
        call_oi_usd = 0.0
        put_oi_usd = 0.0
        nearest_oi_usd = 0.0
        oi_total_by_expiry = {}
        oi_usd_by_expiry = {}
        calls_usd_by_expiry = {}
        puts_usd_by_expiry = {}
        # Binance Options removed (discontinued in 2023)

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
        # Remove entries older than 14 days to keep file small
        cutoff_oi = (datetime.date.today() - datetime.timedelta(days=14)).strftime("%Y-%m-%d")
        prev_map = {k: v for k, v in prev_map.items() if k >= cutoff_oi}
        history = sorted([{"date": k, "open_interest": v} for k, v in prev_map.items()], key=lambda x: x["date"])
        if len(history) < 7:
            last_value = history[-1]["open_interest"] if history else total_oi_usd or total_oi or 0
            today = datetime.date.today()
            history_map = {item["date"]: item["open_interest"] for item in history}
            padded = []
            for offset in range(6, -1, -1):
                day = (today - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
                padded.append({"date": day, "open_interest": history_map.get(day, last_value)})
            history = padded
        else:
            history = history[-7:]
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
            "spot_source": "Deribit"
        }

        trader[asset] = {
            "funding_rate": f"{funding_rate * 100:.4f}%" if funding_rate is not None else "—",
            "perp_basis": f"${perp_basis:.2f}" if perp_basis is not None else "—",
            "rv_iv": rv_iv or "—",
            "liquidations": "—",
            "sources": "Deribit + Binance"
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
            "sources": ["Binance", "Deribit"]
        }
        f.write(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
