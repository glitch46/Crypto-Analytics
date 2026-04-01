#!/usr/bin/env python3
"""
Situation Monitor — Geopolitical Oil Shock Transmission Tracker
Fetches macro/energy data via yfinance, computes derived metrics,
and outputs situation.json for the dashboard.
"""

import datetime
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import re

import yfinance as yf
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

# ── Tickers ──────────────────────────────────────────────────────────────────
TICKERS = {
    "wti":       "CL=F",
    "brent":     "BZ=F",
    "gasoline":  "RB=F",
    "natgas":    "NG=F",
    "tnx":       "^TNX",    # 10Y yield
    "fvx":       "^FVX",    # 5Y yield
    "tyx":       "^TYX",    # 30Y yield
    "irx":       "^IRX",    # 13-week T-bill
    "vix":       "^VIX",
    "gold":      "GC=F",
    "dxy":       "DX-Y.NYB",
    "spx":       "^GSPC",
    "xle":       "XLE",
    "lqd":       "LQD",
    "hyg":       "HYG",
    "tlt":       "TLT",
}

HISTORY_PERIOD = "6mo"
HISTORY_INTERVAL = "1d"

# ── Key Levels ───────────────────────────────────────────────────────────────
KEY_LEVELS = {
    "oil_elevated":  90,
    "oil_high":     100,
    "oil_critical": 110,
    "tnx_elevated":  4.5,
    "tnx_high":      5.0,
    "vix_elevated":  20,
    "vix_high":      30,
    "vix_critical":  40,
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


def pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def sma(values: List[float], window: int) -> Optional[float]:
    valid = [v for v in values if v != 0]
    if len(valid) < window:
        return None
    return sum(valid[-window:]) / window


def rolling_correlation(xs: List[float], ys: List[float], window: int) -> Optional[float]:
    """Pearson correlation over last `window` observations."""
    if len(xs) < window or len(ys) < window:
        return None
    x = xs[-window:]
    y = ys[-window:]
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if sx == 0 or sy == 0:
        return None
    return round(cov / (sx * sy), 4)


def compute_zscore(values: List[float], window: int = 90) -> Optional[float]:
    valid = [v for v in values if v != 0]
    if len(valid) < max(window, 2):
        return None
    subset = valid[-window:]
    avg = sum(subset) / len(subset)
    var = sum((x - avg) ** 2 for x in subset) / (len(subset) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return round((valid[-1] - avg) / std, 2)


# ── FRED: ICE BofA HY OAS ───────────────────────────────────────────────────
FRED_HY_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"


def fetch_hy_spread() -> Dict[str, Any]:
    """Fetch ICE BofA US High Yield Index Option-Adjusted Spread from FRED."""
    try:
        r = curl_requests.get(FRED_HY_CSV, impersonate="chrome", timeout=20)
        r.raise_for_status()

        lines = r.text.strip().split("\n")
        dates = []
        values = []
        # Keep only last ~6 months of daily data
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=180)).strftime("%Y-%m-%d")
        for line in lines[1:]:  # skip header
            parts = line.split(",")
            if len(parts) < 2 or parts[1] == ".":
                continue
            date_str = parts[0]
            if date_str < cutoff:
                continue
            try:
                val = float(parts[1])
            except ValueError:
                continue
            dates.append(date_str)
            values.append(val)

        current = values[-1] if values else None
        chg_1d = round(values[-1] - values[-2], 3) if len(values) >= 2 else None
        chg_7d = round(values[-1] - values[-6], 3) if len(values) >= 6 else None
        chg_30d = round(values[-1] - values[-23], 3) if len(values) >= 23 else None

        # Compute SMA
        sma_val = sum(values) / len(values) if values else None

        print(f"  HY OAS: {current}% (7d chg: {chg_7d})")

        return {
            "current": current,
            "chg_1d": chg_1d,
            "chg_7d": chg_7d,
            "chg_30d": chg_30d,
            "sma": round(sma_val, 3) if sma_val else None,
            "dates": dates,
            "values": values,
        }
    except Exception as e:
        print(f"  Warning: HY OAS fetch failed: {e}")
        return {
            "current": None, "chg_1d": None, "chg_7d": None, "chg_30d": None,
            "sma": None, "dates": [], "values": [],
        }


# ── AAII Sentiment Survey ────────────────────────────────────────────────────
AAII_URL = "https://www.aaii.com/sentimentsurvey/sent_results"
AAII_HISTORICAL_AVG = {"bullish": 37.5, "neutral": 31.5, "bearish": 31.0}


def fetch_aaii_sentiment() -> Dict[str, Any]:
    """Scrape AAII Investor Sentiment Survey data."""
    try:
        r = curl_requests.get(AAII_URL, impersonate="chrome", timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        tables = soup.find_all("table")
        if not tables:
            raise ValueError("No tables found on AAII page")

        rows = tables[0].find_all("tr")
        dates = []
        bullish = []
        neutral = []
        bearish = []

        current_year = datetime.datetime.now().year
        for row in rows[1:]:  # skip header
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            date_str = cells[0]
            try:
                b = float(cells[1].replace("%", ""))
                n = float(cells[2].replace("%", ""))
                be = float(cells[3].replace("%", ""))
            except (ValueError, IndexError):
                continue

            # Parse date like "Mar 25" -> "2026-03-25"
            try:
                # Add a dummy year to avoid deprecation warning
                parsed = datetime.datetime.strptime(f"{date_str} 2000", "%b %d %Y")
                # Assign year — if month > current month, it's previous year
                year = current_year
                if parsed.month > datetime.datetime.now().month:
                    year = current_year - 1
                date_fmt = f"{year}-{parsed.month:02d}-{parsed.day:02d}"
            except ValueError:
                date_fmt = date_str

            dates.append(date_fmt)
            bullish.append(b)
            neutral.append(n)
            bearish.append(be)

        # Reverse to chronological order (page is newest-first)
        dates.reverse()
        bullish.reverse()
        neutral.reverse()
        bearish.reverse()

        # Bull-bear spread
        bull_bear_spread = [round(b - be, 1) for b, be in zip(bullish, bearish)]

        current = {
            "date": dates[-1] if dates else None,
            "bullish": bullish[-1] if bullish else None,
            "neutral": neutral[-1] if neutral else None,
            "bearish": bearish[-1] if bearish else None,
            "bull_bear_spread": bull_bear_spread[-1] if bull_bear_spread else None,
        }

        # Sentiment signal interpretation
        if current["bearish"] and current["bearish"] > 50:
            signal = "EXTREME FEAR — contrarian bullish signal"
        elif current["bearish"] and current["bearish"] > 40:
            signal = "Elevated bearishness — lean contrarian bullish"
        elif current["bullish"] and current["bullish"] > 50:
            signal = "EXTREME GREED — contrarian bearish signal"
        elif current["bullish"] and current["bullish"] > 40:
            signal = "Elevated bullishness — lean contrarian bearish"
        else:
            signal = "Neutral sentiment — no strong contrarian signal"

        print(f"  AAII: Bullish {current['bullish']}%, Bearish {current['bearish']}%, Spread {current['bull_bear_spread']}")

        return {
            "current": current,
            "signal": signal,
            "historical_avg": AAII_HISTORICAL_AVG,
            "history": {
                "dates": dates,
                "bullish": bullish,
                "neutral": neutral,
                "bearish": bearish,
                "bull_bear_spread": bull_bear_spread,
            },
        }

    except Exception as e:
        print(f"  Warning: AAII fetch failed: {e}")
        return {
            "current": {"date": None, "bullish": None, "neutral": None, "bearish": None, "bull_bear_spread": None},
            "signal": "Data unavailable",
            "historical_avg": AAII_HISTORICAL_AVG,
            "history": {"dates": [], "bullish": [], "neutral": [], "bearish": [], "bull_bear_spread": []},
        }


# ── Data Fetch ───────────────────────────────────────────────────────────────
def fetch_all_data() -> Dict[str, Any]:
    """Download history for all tickers via yfinance."""
    symbols = list(TICKERS.values())
    print(f"Fetching {len(symbols)} tickers: {', '.join(symbols)}")

    raw = yf.download(
        symbols,
        period=HISTORY_PERIOD,
        interval=HISTORY_INTERVAL,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
    )

    result: Dict[str, Any] = {}
    for key, symbol in TICKERS.items():
        try:
            if len(TICKERS) == 1:
                df = raw
            else:
                df = raw[symbol]
            closes = df["Close"].dropna().tolist()
            dates = [d.strftime("%Y-%m-%d") for d in df["Close"].dropna().index]
            highs = df["High"].dropna().tolist()
            lows = df["Low"].dropna().tolist()
            volumes = df["Volume"].dropna().tolist() if "Volume" in df.columns else []
            result[key] = {
                "dates":   dates,
                "closes":  [safe_float(c) for c in closes],
                "highs":   [safe_float(h) for h in highs],
                "lows":    [safe_float(l) for l in lows],
                "volumes": [safe_float(v) for v in volumes],
            }
        except Exception as e:
            print(f"  Warning: failed to parse {key} ({symbol}): {e}")
            result[key] = {"dates": [], "closes": [], "highs": [], "lows": [], "volumes": []}

    return result


# ── Derived Metrics ──────────────────────────────────────────────────────────
def compute_kpis(data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute KPI card values."""
    kpis = {}
    for key in ["wti", "brent", "tnx", "vix", "gold", "dxy", "spx", "xle", "lqd", "hyg", "tlt"]:
        closes = data.get(key, {}).get("closes", [])
        if not closes:
            kpis[key] = {"current": None, "chg_1d": None, "chg_7d": None, "chg_30d": None}
            continue
        current = closes[-1]
        chg_1d = pct_change(current, closes[-2]) if len(closes) >= 2 else None
        chg_7d = pct_change(current, closes[-6]) if len(closes) >= 6 else None
        chg_30d = pct_change(current, closes[-23]) if len(closes) >= 23 else None
        kpis[key] = {
            "current": round(current, 2),
            "chg_1d": chg_1d,
            "chg_7d": chg_7d,
            "chg_30d": chg_30d,
        }
    return kpis


def compute_oil_risk_premium(data: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate geopolitical risk premium as deviation from 90d SMA."""
    brent_closes = data.get("brent", {}).get("closes", [])
    wti_closes = data.get("wti", {}).get("closes", [])

    brent_sma90 = sma(brent_closes, 90)
    wti_sma90 = sma(wti_closes, 90)

    brent_current = brent_closes[-1] if brent_closes else 0
    wti_current = wti_closes[-1] if wti_closes else 0

    brent_premium = round(brent_current - brent_sma90, 2) if brent_sma90 else None
    wti_premium = round(wti_current - wti_sma90, 2) if wti_sma90 else None

    brent_premium_pct = round(brent_premium / brent_sma90 * 100, 2) if brent_sma90 and brent_premium else None

    return {
        "brent_sma90": round(brent_sma90, 2) if brent_sma90 else None,
        "wti_sma90": round(wti_sma90, 2) if wti_sma90 else None,
        "brent_premium": brent_premium,
        "wti_premium": wti_premium,
        "brent_premium_pct": brent_premium_pct,
    }


def compute_credit_spread(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Approximate credit spread using LQD price inversely.
    When LQD drops, spreads widen. We compute a proxy:
      spread_proxy = (LQD_sma90 - LQD_current) / LQD_sma90 * 100
    Positive = widening, Negative = tightening.
    Also compute HYG-TLT relative as a stress gauge.
    """
    lqd_closes = data.get("lqd", {}).get("closes", [])
    tnx_closes = data.get("tnx", {}).get("closes", [])
    hyg_closes = data.get("hyg", {}).get("closes", [])
    tlt_closes = data.get("tlt", {}).get("closes", [])

    lqd_sma90 = sma(lqd_closes, 90)
    lqd_current = lqd_closes[-1] if lqd_closes else None

    # Spread proxy: how much LQD has declined from its SMA (decline = widening)
    spread_proxy = None
    if lqd_sma90 and lqd_current:
        spread_proxy = round((lqd_sma90 - lqd_current) / lqd_sma90 * 100, 3)

    # HYG/TLT ratio history
    hyg_tlt_ratio = []
    if hyg_closes and tlt_closes:
        min_len = min(len(hyg_closes), len(tlt_closes))
        for i in range(min_len):
            if tlt_closes[i] != 0:
                hyg_tlt_ratio.append(round(hyg_closes[i] / tlt_closes[i], 4))

    # Spread direction over time
    spread_history = []
    if lqd_closes and tnx_closes:
        min_len = min(len(lqd_closes), len(tnx_closes))
        lqd_dates = data.get("lqd", {}).get("dates", [])
        for i in range(min_len):
            # Inverse of LQD price as spread proxy
            if lqd_closes[i] != 0:
                spread_history.append(round(100 / lqd_closes[i], 4))

    return {
        "spread_proxy": spread_proxy,
        "spread_direction": "widening" if spread_proxy and spread_proxy > 0 else "tightening",
        "lqd_current": round(lqd_current, 2) if lqd_current else None,
        "lqd_sma90": round(lqd_sma90, 2) if lqd_sma90 else None,
        "hyg_tlt_ratio": hyg_tlt_ratio,
        "spread_history": spread_history,
    }


def compute_correlations(data: Dict[str, Any]) -> Dict[str, Any]:
    """Rolling correlations between oil and yields."""
    brent = data.get("brent", {}).get("closes", [])
    tnx = data.get("tnx", {}).get("closes", [])

    return {
        "oil_yield_30d": rolling_correlation(brent, tnx, 30),
        "oil_yield_60d": rolling_correlation(brent, tnx, 60),
        "oil_yield_100d": rolling_correlation(brent, tnx, 100),
    }


def compute_yield_curve(data: Dict[str, Any]) -> Dict[str, Any]:
    """Current yield curve snapshot and history."""
    irx = data.get("irx", {}).get("closes", [])
    fvx = data.get("fvx", {}).get("closes", [])
    tnx = data.get("tnx", {}).get("closes", [])
    tyx = data.get("tyx", {}).get("closes", [])

    current = {
        "13w": round(irx[-1], 3) if irx else None,
        "5y":  round(fvx[-1], 3) if fvx else None,
        "10y": round(tnx[-1], 3) if tnx else None,
        "30y": round(tyx[-1], 3) if tyx else None,
    }

    # 10Y-2Y spread (using 13w as short-end proxy)
    spread_10y_short = None
    if tnx and irx:
        spread_10y_short = round(tnx[-1] - irx[-1], 3)

    inverted = spread_10y_short is not None and spread_10y_short < 0

    # History for curve chart
    curve_history = {
        "dates": data.get("tnx", {}).get("dates", []),
        "irx":   irx,
        "fvx":   fvx,
        "tnx":   tnx,
        "tyx":   tyx,
    }

    return {
        "current": current,
        "spread_10y_short": spread_10y_short,
        "inverted": inverted,
        "history": curve_history,
    }


def compute_relative_performance(data: Dict[str, Any]) -> Dict[str, Any]:
    """XLE vs S&P 500 indexed to 100."""
    xle = data.get("xle", {}).get("closes", [])
    spx = data.get("spx", {}).get("closes", [])
    dates = data.get("xle", {}).get("dates", [])

    min_len = min(len(xle), len(spx), len(dates))
    if min_len == 0:
        return {"dates": [], "xle_indexed": [], "spx_indexed": []}

    xle_base = xle[0]
    spx_base = spx[0]

    xle_indexed = [round(v / xle_base * 100, 2) if xle_base else 100 for v in xle[:min_len]]
    spx_indexed = [round(v / spx_base * 100, 2) if spx_base else 100 for v in spx[:min_len]]

    return {
        "dates": dates[:min_len],
        "xle_indexed": xle_indexed,
        "spx_indexed": spx_indexed,
    }


# ── Transmission Chain ───────────────────────────────────────────────────────
def compute_transmission_chain(data: Dict[str, Any], kpis: Dict, oil_risk: Dict, credit: Dict) -> Dict[str, Any]:
    """
    Evaluate each link in the transmission chain:
    Oil Spike → Inflation Expectations → Bond Yields ↑ → Credit Spreads ↑ → Equity Valuations ↓

    Status: green (inactive), yellow (warning), red (active)
    """
    chain = {}

    # 1. Oil Spike
    brent_premium_pct = oil_risk.get("brent_premium_pct") or 0
    wti_chg_30d = (kpis.get("wti", {}).get("chg_30d") or 0)
    if brent_premium_pct > 10 or wti_chg_30d > 15:
        chain["oil_spike"] = "red"
    elif brent_premium_pct > 5 or wti_chg_30d > 8:
        chain["oil_spike"] = "yellow"
    else:
        chain["oil_spike"] = "green"

    # 2. Inflation Expectations (proxied by oil + gasoline moves)
    gasoline_closes = data.get("gasoline", {}).get("closes", [])
    gas_chg_30d = pct_change(gasoline_closes[-1], gasoline_closes[-23]) if len(gasoline_closes) >= 23 else 0
    if (wti_chg_30d > 15 and (gas_chg_30d or 0) > 10):
        chain["inflation_expectations"] = "red"
    elif (wti_chg_30d > 8 or (gas_chg_30d or 0) > 5):
        chain["inflation_expectations"] = "yellow"
    else:
        chain["inflation_expectations"] = "green"

    # 3. Bond Yields Rising
    tnx_chg_30d = kpis.get("tnx", {}).get("chg_30d") or 0
    tnx_current = kpis.get("tnx", {}).get("current") or 0
    if tnx_chg_30d > 10 or tnx_current > KEY_LEVELS["tnx_high"]:
        chain["bond_yields"] = "red"
    elif tnx_chg_30d > 5 or tnx_current > KEY_LEVELS["tnx_elevated"]:
        chain["bond_yields"] = "yellow"
    else:
        chain["bond_yields"] = "green"

    # 4. Credit Spreads Widening
    spread = credit.get("spread_proxy") or 0
    if spread > 2:
        chain["credit_spreads"] = "red"
    elif spread > 0.5:
        chain["credit_spreads"] = "yellow"
    else:
        chain["credit_spreads"] = "green"

    # 5. Equity Valuations Declining
    spx_chg_30d = kpis.get("spx", {}).get("chg_30d") or 0
    vix_current = kpis.get("vix", {}).get("current") or 0
    if spx_chg_30d < -10 or vix_current > KEY_LEVELS["vix_high"]:
        chain["equity_valuations"] = "red"
    elif spx_chg_30d < -5 or vix_current > KEY_LEVELS["vix_elevated"]:
        chain["equity_valuations"] = "yellow"
    else:
        chain["equity_valuations"] = "green"

    # Count active links
    statuses = list(chain.values())
    red_count = statuses.count("red")
    yellow_count = statuses.count("yellow")
    active_count = red_count + yellow_count

    return {
        "links": chain,
        "red_count": red_count,
        "yellow_count": yellow_count,
        "active_count": active_count,
    }


# ── Threat Assessment ────────────────────────────────────────────────────────
def compute_threat_level(chain: Dict, kpis: Dict, oil_risk: Dict, credit: Dict) -> Dict[str, Any]:
    """Composite threat scoring (0-100) and level assessment."""
    score = 0.0

    # Oil component (0-30)
    brent_premium_pct = abs(oil_risk.get("brent_premium_pct") or 0)
    score += min(brent_premium_pct * 2, 30)

    # Volatility component (0-20)
    vix = kpis.get("vix", {}).get("current") or 0
    if vix > 40:
        score += 20
    elif vix > 30:
        score += 15
    elif vix > 20:
        score += 10
    elif vix > 15:
        score += 5

    # Credit component (0-25)
    spread = abs(credit.get("spread_proxy") or 0)
    score += min(spread * 8, 25)

    # Equity component (0-15)
    spx_chg = kpis.get("spx", {}).get("chg_30d") or 0
    if spx_chg < -10:
        score += 15
    elif spx_chg < -5:
        score += 10
    elif spx_chg < -2:
        score += 5

    # Transmission chain bonus (0-10)
    red_count = chain.get("red_count", 0)
    score += red_count * 2

    score = min(round(score, 1), 100)

    if score >= 70:
        level = "CRITICAL"
    elif score >= 40:
        level = "HIGH"
    elif score >= 20:
        level = "ELEVATED"
    else:
        level = "LOW"

    return {
        "score": score,
        "level": level,
        "components": {
            "oil": min(round(brent_premium_pct * 2, 1), 30),
            "volatility": min(round(score, 1), 20),
            "credit": min(round(spread * 8, 1), 25),
            "equity": min(round(abs(min(spx_chg, 0)), 1), 15),
            "chain": red_count * 2,
        },
    }


# ── Narrative Assessment ─────────────────────────────────────────────────────
def build_narrative(kpis: Dict, oil_risk: Dict, credit: Dict, chain: Dict, threat: Dict, correlations: Dict, yield_curve: Dict) -> Dict[str, str]:
    """Auto-generated thesis assessment narrative."""

    # Supply Shock vs Demand
    brent_premium = oil_risk.get("brent_premium_pct") or 0
    vix_current = kpis.get("vix", {}).get("current") or 0
    spx_chg = kpis.get("spx", {}).get("chg_30d") or 0

    if brent_premium > 5 and spx_chg < -2:
        supply_demand = (
            "Oil is trading above its 90-day moving average while equities weaken — "
            "consistent with a SUPPLY-DRIVEN move. This is the stagflationary scenario "
            "where energy costs rise independent of economic growth, pressuring both "
            "consumers and corporate margins."
        )
    elif brent_premium > 5 and spx_chg > 2:
        supply_demand = (
            "Oil is elevated alongside rising equities — suggesting a DEMAND-DRIVEN "
            "rally. This is less threatening to the thesis transmission chain as it "
            "reflects economic strength rather than supply disruption."
        )
    elif brent_premium < -5:
        supply_demand = (
            "Oil is trading below its 90-day average, indicating REDUCED supply risk. "
            "Geopolitical risk premium appears minimal at current levels."
        )
    else:
        supply_demand = (
            "Oil price is near its 90-day average with no clear directional signal. "
            "Neither supply shock nor demand surge is dominant."
        )

    # Fed Watch
    tnx_current = kpis.get("tnx", {}).get("current") or 0
    tnx_chg = kpis.get("tnx", {}).get("chg_30d") or 0
    if tnx_current > 5.0:
        fed_watch = (
            f"10Y yield at {tnx_current}% — well above neutral territory. "
            "The bond market is pricing persistent inflation or hawkish Fed policy. "
            "An oil shock at these levels could force the Fed into a difficult choice "
            "between fighting inflation and supporting growth."
        )
    elif tnx_current > 4.5:
        fed_watch = (
            f"10Y yield at {tnx_current}% — elevated but not extreme. "
            "Further oil-driven inflation could push yields higher and complicate "
            "the Fed's rate path. Watch for hawkish rhetoric shifts."
        )
    elif tnx_chg > 5:
        fed_watch = (
            f"10Y yield rising ({tnx_chg:+.1f}% over 30 days). "
            "Bond market is adjusting expectations upward. If oil continues to rise, "
            "this trend likely accelerates."
        )
    else:
        fed_watch = (
            f"10Y yield at {tnx_current}% — relatively stable. "
            "Current bond market conditions do not signal immediate stress. "
            "An oil shock would need to be sustained to meaningfully shift Fed calculus."
        )

    # Credit Market Signal
    spread_dir = credit.get("spread_direction", "unknown")
    spread_val = credit.get("spread_proxy") or 0
    if spread_dir == "widening" and spx_chg < -3:
        credit_signal = (
            "Credit spreads are WIDENING while equities decline — the transmission "
            "chain is active. Investment-grade bonds are pricing in higher risk. "
            "This is the confirmation signal the thesis watches for."
        )
    elif spread_dir == "widening" and spx_chg >= 0:
        credit_signal = (
            "Credit spreads are widening but equities remain resilient. This divergence "
            "often resolves with equities catching down to credit's warning. "
            "The bond market tends to lead — this bears watching."
        )
    elif spread_dir == "tightening":
        credit_signal = (
            "Credit spreads are tightening — the bond market is NOT confirming stress. "
            "This suggests risk appetite remains intact and the transmission chain "
            "is not fully engaged."
        )
    else:
        credit_signal = "Credit market data is insufficient for a clear signal."

    # Historical Analog
    if brent_premium > 10 and vix_current > 25:
        analog = (
            "Current conditions most resemble the 2022 Russia-Ukraine energy shock: "
            "elevated oil, rising volatility, and yield curve stress. The key difference "
            "is the Strait of Hormuz choke point affects ~20% of global oil transit."
        )
    elif brent_premium > 5 and vix_current > 20:
        analog = (
            "Conditions echo early 2018 (Iran sanctions reimposition): moderate oil "
            "premium with contained but rising volatility. Markets eventually repriced "
            "after the threat became sustained over multiple weeks."
        )
    elif vix_current > 30:
        analog = (
            "Elevated VIX without a corresponding oil spike suggests broader market fear — "
            "similar to trade war episodes (2019) or banking stress events. "
            "The geopolitical oil thesis may not be the primary driver currently."
        )
    else:
        analog = (
            "No strong historical analog is active. Markets are in a relatively "
            "normal regime. Past episodes to watch if conditions deteriorate: "
            "1990 Gulf War, 2022 Ukraine shock, 2018 Iran sanctions."
        )

    # Risk Summary
    level = threat.get("level", "LOW")
    score = threat.get("score", 0)
    active = chain.get("active_count", 0)
    risk_summary = (
        f"Composite threat score: {score}/100 ({level}). "
        f"{active} of 5 transmission chain links are active. "
    )
    if level == "CRITICAL":
        risk_summary += "Multiple chain links firing simultaneously — highest alert posture."
    elif level == "HIGH":
        risk_summary += "Key risk indicators elevated — active monitoring warranted."
    elif level == "ELEVATED":
        risk_summary += "Some warning signals present but chain not fully engaged."
    else:
        risk_summary += "Baseline conditions — no immediate transmission chain activation."

    # One-line status
    chain_links = chain.get("links", {})
    active_names = [k for k, v in chain_links.items() if v in ("red", "yellow")]
    if active_names:
        status_line = (
            f"Threat level {level} (score {score}/100). "
            f"Active chain links: {', '.join(n.replace('_', ' ').title() for n in active_names)}."
        )
    else:
        status_line = f"Threat level {level} (score {score}/100). No transmission chain links currently active."

    return {
        "supply_demand": supply_demand,
        "fed_watch": fed_watch,
        "credit_signal": credit_signal,
        "historical_analog": analog,
        "risk_summary": risk_summary,
        "status_line": status_line,
    }


# ── Chart Data Builders ─────────────────────────────────────────────────────
def build_chart_data(data: Dict[str, Any], oil_risk: Dict) -> Dict[str, Any]:
    """Pre-format data for each chart section."""
    charts = {}

    # 1. Oil Price History (90d) with SMA
    brent_closes = data.get("brent", {}).get("closes", [])
    wti_closes = data.get("wti", {}).get("closes", [])
    oil_dates = data.get("brent", {}).get("dates", [])

    # Compute 20d SMA for both
    brent_sma20 = []
    wti_sma20 = []
    for i in range(len(brent_closes)):
        brent_sma20.append(round(sum(brent_closes[max(0,i-19):i+1]) / min(i+1, 20), 2))
    for i in range(len(wti_closes)):
        wti_sma20.append(round(sum(wti_closes[max(0,i-19):i+1]) / min(i+1, 20), 2))

    # SMA90 line for risk premium shading
    brent_sma90_line = []
    for i in range(len(brent_closes)):
        if i >= 89:
            brent_sma90_line.append(round(sum(brent_closes[i-89:i+1]) / 90, 2))
        else:
            brent_sma90_line.append(None)

    charts["oil_history"] = {
        "dates": oil_dates,
        "brent": brent_closes,
        "wti": wti_closes,
        "brent_sma20": brent_sma20,
        "wti_sma20": wti_sma20,
        "brent_sma90": brent_sma90_line,
    }

    # 2. Oil vs 10Y Yield
    tnx_closes = data.get("tnx", {}).get("closes", [])
    tnx_dates = data.get("tnx", {}).get("dates", [])
    charts["oil_vs_yield"] = {
        "dates": tnx_dates,
        "brent": brent_closes[:len(tnx_dates)],
        "tnx": tnx_closes,
    }

    # 3. Yield Curve
    charts["yield_curve"] = {
        "dates": data.get("tnx", {}).get("dates", []),
        "irx": data.get("irx", {}).get("closes", []),
        "fvx": data.get("fvx", {}).get("closes", []),
        "tnx": tnx_closes,
        "tyx": data.get("tyx", {}).get("closes", []),
    }

    # 4. Credit Spread Monitor (LQD inverse)
    lqd_closes = data.get("lqd", {}).get("closes", [])
    lqd_dates = data.get("lqd", {}).get("dates", [])
    spread_proxy_series = []
    lqd_sma90_val = sma(lqd_closes, 90)
    for v in lqd_closes:
        if lqd_sma90_val and v != 0:
            spread_proxy_series.append(round((lqd_sma90_val - v) / lqd_sma90_val * 100, 3))
        else:
            spread_proxy_series.append(0)
    charts["credit_spread"] = {
        "dates": lqd_dates,
        "spread_proxy": spread_proxy_series,
    }

    # 5. VIX + Gold
    vix_closes = data.get("vix", {}).get("closes", [])
    gold_closes = data.get("gold", {}).get("closes", [])
    charts["vix_gold"] = {
        "dates": data.get("vix", {}).get("dates", []),
        "vix": vix_closes,
        "gold": gold_closes,
    }

    # 6. Energy vs S&P relative performance
    xle_closes = data.get("xle", {}).get("closes", [])
    spx_closes = data.get("spx", {}).get("closes", [])
    xle_dates = data.get("xle", {}).get("dates", [])
    min_len = min(len(xle_closes), len(spx_closes), len(xle_dates))
    if min_len > 0:
        xle_base = xle_closes[0] or 1
        spx_base = spx_closes[0] or 1
        charts["relative_perf"] = {
            "dates": xle_dates[:min_len],
            "xle": [round(v / xle_base * 100, 2) for v in xle_closes[:min_len]],
            "spx": [round(v / spx_base * 100, 2) for v in spx_closes[:min_len]],
        }
    else:
        charts["relative_perf"] = {"dates": [], "xle": [], "spx": []}

    # 7. Big Picture: Oil → Yields → Equities
    charts["big_picture"] = {
        "dates": oil_dates,
        "wti": wti_closes,
        "tnx": tnx_closes[:len(oil_dates)],
        "spx": spx_closes[:len(oil_dates)],
    }

    # 8. HYG vs TLT
    hyg_closes = data.get("hyg", {}).get("closes", [])
    tlt_closes = data.get("tlt", {}).get("closes", [])
    hyg_dates = data.get("hyg", {}).get("dates", [])
    min_len2 = min(len(hyg_closes), len(tlt_closes), len(hyg_dates))
    if min_len2 > 0:
        hyg_base = hyg_closes[0] or 1
        tlt_base = tlt_closes[0] or 1
        charts["hyg_tlt"] = {
            "dates": hyg_dates[:min_len2],
            "hyg": [round(v / hyg_base * 100, 2) for v in hyg_closes[:min_len2]],
            "tlt": [round(v / tlt_base * 100, 2) for v in tlt_closes[:min_len2]],
        }
    else:
        charts["hyg_tlt"] = {"dates": [], "hyg": [], "tlt": []}

    return charts


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, "situation.json")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    ts = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    print(f"[{ts}] Starting Situation Monitor data refresh...")

    # Fetch all data
    data = fetch_all_data()
    aaii = fetch_aaii_sentiment()
    hy_spread = fetch_hy_spread()

    # Compute derived metrics
    kpis = compute_kpis(data)
    oil_risk = compute_oil_risk_premium(data)
    credit = compute_credit_spread(data)
    correlations = compute_correlations(data)
    yield_curve = compute_yield_curve(data)
    relative_perf = compute_relative_performance(data)
    chain = compute_transmission_chain(data, kpis, oil_risk, credit)
    threat = compute_threat_level(chain, kpis, oil_risk, credit)
    narrative = build_narrative(kpis, oil_risk, credit, chain, threat, correlations, yield_curve)
    charts = build_chart_data(data, oil_risk)

    # Assemble output
    payload = {
        "metadata": {
            "last_updated": ts,
            "refresh_cadence": "15 minutes",
            "sources": ["Yahoo Finance (yfinance)", "AAII Sentiment Survey"],
            "tickers": TICKERS,
        },
        "aaii": aaii,
        "hy_spread": hy_spread,
        "threat": threat,
        "narrative": narrative,
        "kpis": kpis,
        "oil_risk_premium": oil_risk,
        "credit_spread": credit,
        "correlations": correlations,
        "yield_curve": yield_curve,
        "relative_performance": relative_perf,
        "transmission_chain": chain,
        "key_levels": KEY_LEVELS,
        "charts": charts,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[{ts}] Wrote {output_path}")
    print(f"  Threat level: {threat['level']} (score: {threat['score']}/100)")
    print(f"  Chain: {chain['red_count']} red, {chain['yellow_count']} yellow")
    print("  Done.")


if __name__ == "__main__":
    main()
