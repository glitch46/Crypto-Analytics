#!/usr/bin/env python3
import datetime
import json
import os
import urllib.parse
import urllib.request

CRYPTO_API_KEY = os.environ.get("CRYPTODATADOWNLOAD_API_KEY")
CRYPTO_API_BASE = "https://api.cryptodatadownload.com/v1/data"
DERIBIT_BASE = "https://www.deribit.com/api/v2/public"

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
    data = fetch_json(url, headers=build_headers())
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data


def fetch_deribit(path, params=None):
    query = urllib.parse.urlencode(params or {})
    url = f"{DERIBIT_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    data = fetch_json(url)
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data


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


def maturity_to_yymmdd(date_str):
    """Convert YYYY-MM-DD to YYMMDD integer for CDD options API."""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return int(dt.strftime("%y%m%d"))
    except (ValueError, TypeError):
        return None


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
        row = data[-1] if isinstance(data[-1], dict) else data[0]
        for key in ("close", "Close"):
            if key in row:
                try:
                    return float(row[key])
                except (TypeError, ValueError):
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
    return load_cdd("/ohlc/deribit/futures/funding/", {
        "symbol": symbol,
        "limit": 3,
        "return": "JSON"
    })


def load_deribit_volatility(symbol, limit=30):
    return load_cdd("/ohlc/deribit/volatility/", {
        "symbol": symbol,
        "limit": limit,
        "return": "JSON"
    })


def load_binance_basis(symbol, limit=2):
    return load_cdd("/summary/binance/basis/", {
        "symbol": symbol,
        "limit": limit,
        "return": "JSON"
    })


def load_binance_options_ohlc_by_underlying(underlying, limit=5000):
    return load_cdd("/ohlc/binance/options/", {
        "underlying": underlying,
        "limit": limit,
        "return": "JSON"
    })


def load_deribit_options_greeks_maturity(underlying, date, limit=5000):
    return load_cdd("/summary/deribit/options/greeks/maturities/", {
        "underlying": underlying,
        "startdate": date,
        "enddate": date,
        "limit": limit,
        "return": "JSON"
    })


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
        if len(history) >= 7:
            history = history[-7:]

        if len(history) < 7:
            today = datetime.date.today()
            history_map = {item["date"]: item["open_interest"] for item in history}
            last_value = history[-1]["open_interest"] if history else 0
            padded = []
            for offset in range(6, -1, -1):
                day = (today - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
                padded.append({"date": day, "open_interest": history_map.get(day, last_value)})
            history = padded
        oi_history[asset] = history

        maturities = load_binance_oi_maturity(underlying)
        maturity_rows = maturities if isinstance(maturities, list) else []
        # Get the latest date's rows only (API returns newest first)
        latest_date = None
        for row in maturity_rows:
            d = row.get("date")
            if d and (latest_date is None or d > latest_date):
                latest_date = d
        latest_maturity_rows = [r for r in maturity_rows if r.get("date") == latest_date] if latest_date else []
        maturity_values = []
        for row in latest_maturity_rows:
            maturity = row.get("maturity")
            parsed = parse_maturity(maturity)
            if parsed and within_forward_window(parsed, 90):
                maturity_values.append(parsed)
        maturity_values = sorted(set(maturity_values))
        nearest_maturity = maturity_values[0].strftime("%Y-%m-%d") if maturity_values else None

        strikes = []
        deribit_strikes = []
        expiry_strikes_map = {}
        total_oi_usd = 0.0
        total_oi_base = 0.0
        binance_oi_usd = 0.0
        nearest_oi_usd = 0.0
        oi_total_by_expiry = {}
        if nearest_maturity:
            options_rows = load_binance_options_ohlc(underlying, nearest_maturity)
            options_rows = options_rows if isinstance(options_rows, list) else []
            latest_by_symbol = extract_latest_by_symbol(options_rows)

            for symbol, row in latest_by_symbol.items():
                strike = parse_symbol_strike(symbol)
                opt_type = parse_symbol_type(symbol, row.get("type"))
                oi = row.get("openinterest_contracts")
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

        binance_oi_summary = oi_summary if isinstance(oi_summary, list) else []
        if binance_oi_summary:
            try:
                latest_oi_row = binance_oi_summary[0]
                binance_oi_contracts = float(latest_oi_row.get("total_calls_oi", 0) or 0) + float(
                    latest_oi_row.get("total_puts_oi", 0) or 0
                )
            except (TypeError, ValueError):
                binance_oi_contracts = 0.0
            if binance_oi_contracts:
                binance_oi_usd = binance_oi_contracts

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
            strike_entry = {
                "instrument_name": inst.get("instrument_name"),
                "strike": float(inst.get("strike", 0) or 0),
                "option_type": inst.get("option_type"),
                "open_interest": oi_value
            }
            if inst.get("expiration_timestamp") == nearest_deribit_ts:
                deribit_strikes.append(strike_entry)
                nearest_oi_usd += oi_value_usd
            expiry_key = expiry_date.strftime("%Y-%m-%d")
            expiry_strikes_map.setdefault(expiry_key, []).append(strike_entry)
            oi_total_by_expiry[expiry_key] = oi_total_by_expiry.get(expiry_key, 0.0) + oi_value
            total_oi_usd += oi_value_usd
            total_oi_base += oi_value

        expiry_totals = []
        for expiry_key, strike_rows in expiry_strikes_map.items():
            total = sum(row.get("open_interest", 0) or 0 for row in strike_rows)
            expiry_totals.append({"date": expiry_key, "total": total})

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

            for erow in expiry_rows:
                expiry_strikes = expiry_strikes_map.get(erow["date"], [])
                expiry_points = sorted({s["strike"] for s in expiry_strikes})
                best_expiry, _ = compute_max_pain(expiry_strikes, expiry_points)
                erow["max_pain"] = best_expiry["strike"] if best_expiry else None

        expiry_pressure[asset] = expiry_rows

        combined_strikes = strikes + deribit_strikes
        price_points = sorted({s["strike"] for s in combined_strikes})
        best, candidates = compute_max_pain(combined_strikes, price_points)
        max_pain[asset] = {
            "peak_expiry": expiry_rows[0]["date"] if expiry_rows else "—",
            "peak_notional": expiry_rows[0]["notional"] if expiry_rows else None,
            "max_pain": best["strike"] if best else None,
            "candidates": candidates
        }

        total_oi, call_oi, put_oi, put_call = aggregate_open_interest(combined_strikes)

        if not combined_strikes and nearest_maturity:
            for row in latest_maturity_rows:
                maturity = row.get("maturity")
                if maturity == nearest_maturity:
                    calls = row.get("calls_oi") or 0
                    puts = row.get("puts_oi") or 0
                    try:
                        call_oi += float(calls)
                        put_oi += float(puts)
                    except (TypeError, ValueError):
                        pass
            total_oi = call_oi + put_oi
            put_call = (put_oi / call_oi) if call_oi else None

        oi_change = None
        if len(history) >= 2 and history[0]["open_interest"]:
            oi_change = (history[-1]["open_interest"] - history[0]["open_interest"]) / history[0]["open_interest"]

        spot_price = load_spot_price(underlying)
        if spot_price:
            if total_oi_base:
                total_oi_usd = total_oi_base * spot_price
            if binance_oi_usd:
                total_oi_usd += binance_oi_usd * spot_price
        if total_oi_usd:
            total_oi = total_oi_usd

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

        greeks_dates = load_cdd("/summary/deribit/options/greeks/available/", {
            "underlying": meta["spot_symbol"],
            "return": "JSON"
        })
        latest_greeks_date = None
        if isinstance(greeks_dates, dict):
            asset_key = meta["spot_symbol"]
            latest_greeks_date = greeks_dates.get(asset_key, {}).get("last_date")

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
        if latest_greeks_date:
            greeks_maturity = load_deribit_options_greeks_maturity(meta["spot_symbol"], latest_greeks_date, 5000)
            greeks_maturity = greeks_maturity if isinstance(greeks_maturity, list) else []
            iv_values = [row.get("avg_iv") for row in greeks_maturity if row.get("avg_iv") is not None]
            if iv_values:
                avg_iv = sum(iv_values) / len(iv_values)
                if iv_7d:
                    rv_iv = f"{iv_7d:.1f}% / {avg_iv:.1f}%"

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
            "spot_source": "CryptoDataDownload"
        }

        trader[asset] = {
            "funding_rate": f"{funding_rate * 100:.4f}%" if funding_rate is not None else "—",
            "perp_basis": f"${perp_basis:.2f}" if perp_basis is not None else "—",
            "rv_iv": rv_iv or "—",
            "liquidations": "—",
            "sources": "Deribit + Binance (CDD)"
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
