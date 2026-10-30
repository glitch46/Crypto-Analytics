#!/usr/bin/env python3
"""Backtest Trading-Indicators signals against forward price moves.

Evaluates whether each stored signal (depth imbalance, CVD slope, composite
long-readiness) predicts the direction of subsequent price action.

Usage:
    python backtest_indicators.py [path/to/indicators.json]

Reads the local data file by default. Outputs a per-signal / per-asset /
per-horizon accuracy table (hit rate, mean forward return, edge vs baseline).

Methodology notes:
    - Signals are evaluated strictly on data available at bar t (no lookahead).
    - Forward return is measured from bar t to the closest bar >= t + horizon
      using timestamps, so gaps in the recorded history are handled correctly.
    - Hit rate = % of fired signals whose predicted direction matches the sign
      of the realized forward return (zero returns excluded from the denominator
      only for sign-match; reported both with and without zero returns).
"""
import argparse
import datetime
import json
import math
import os

# Horizons in hours -> label
HORIZONS = {
    "1h": 1.0,
    "4h": 4.0,
    "24h": 24.0,
}

# Composite thresholds mirroring confluence_signal()
CONSTRUCTIVE_THRESHOLD = 65.0
CAUTION_THRESHOLD = 40.0


def ts_to_epoch(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M UTC").replace(tzinfo=datetime.UTC).timestamp()


def zscore(values):
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    var = sum((x - avg) ** 2 for x in values) / (len(values) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (values[-1] - avg) / std


def parse_asset(asset_data):
    """Build an aligned, time-ordered list of bars for one asset."""
    depth_rows = asset_data.get("depth_delta_history", [])
    cvd_rows = asset_data.get("cvd_history", [])
    commercials = asset_data.get("commercials", [])

    cvd_by_ts = {r["timestamp"]: r for r in cvd_rows}
    cvd_ts_sorted = sorted(cvd_by_ts.keys())
    # running list of aggregate values in chronological order for slope calc
    cvd_agg_series = [cvd_by_ts[t]["aggregate"] for t in cvd_ts_sorted]

    # commercial caution series (weekly, sparse) -> list of (date_ts, ratio)
    def parse_date(d):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.datetime.strptime(d, fmt).replace(tzinfo=datetime.UTC).timestamp()
            except ValueError:
                continue
        return ts_to_epoch(d)

    com_ratios = [{"ts": parse_date(r["date"]),
                   "ratio": r.get("commercial_short_ratio", 0.0)}
                  for r in commercials if r.get("commercial_short_ratio") is not None]
    com_ratios.sort(key=lambda x: x["ts"])

    bars = []
    for d in depth_rows:
        ts = d["timestamp"]
        epoch = ts_to_epoch(ts)
        combined = d.get("combined", {})
        d5 = (combined.get("5.0%") or {}).get("normalized_delta", 0.0)
        d10 = (combined.get("10.0%") or {}).get("normalized_delta", 0.0)
        d25 = (combined.get("25.0%") or {}).get("normalized_delta", 0.0)

        cvd_agg = cvd_by_ts.get(ts, {}).get("aggregate")
        # cvd slope over last 8 15-min bars
        cvd_slope = None
        if cvd_ts_sorted:
            idx = None
            for i, t in enumerate(cvd_ts_sorted):
                if t >= ts:
                    idx = i
                    break
            if idx is not None and idx >= 8:
                cvd_slope = cvd_agg_series[idx] - cvd_agg_series[idx - 8]

        # commercial caution z-score at time t (uses only history <= t)
        caution = None
        past = [c["ratio"] for c in com_ratios if c["ts"] <= epoch]
        if len(past) >= 3:
            z = zscore(past)
            caution = max(0.0, min(100.0, 50.0 + z * 18.0))

        bars.append({
            "ts": ts,
            "epoch": epoch,
            "mid": d.get("mid_price", 0.0),
            "d5": d5,
            "d10": d10,
            "d25": d25,
            "cvd_agg": cvd_agg,
            "cvd_slope": cvd_slope,
            "caution": caution,
        })
    return bars


def compute_composite(bar):
    """Replicate confluence_signal() long_readiness using one bar's data."""
    depth_score = max(0.0, min(100.0, (bar["d5"] + bar["d10"] + 1.0) * 50.0))
    cvd_score = 50.0
    if bar["cvd_slope"] is not None:
        recent_last = bar["cvd_agg"] or 0.0
        scale = max(1.0, abs(recent_last) * 0.1)
        cvd_norm = max(-1.0, min(1.0, bar["cvd_slope"] / scale))
        cvd_score = (cvd_norm + 1.0) * 50.0
    wall_score = 50.0  # wall persistence is only stored for the latest snapshot
    commercial_caution = bar["caution"] if bar["caution"] is not None else 50.0
    return 0.35 * depth_score + 0.35 * cvd_score + 0.20 * wall_score + 0.10 * (100.0 - commercial_caution)


def evaluate_signal(bars, name, direction_fn, require_ts=8):
    """Evaluate a signal that returns +1 (bullish), -1 (bearish), or 0 (neutral) per bar."""
    results = []
    for i, bar in enumerate(bars):
        if i < require_ts:
            continue
        direction = direction_fn(bar)
        if direction == 0:
            continue
        for label, hours in HORIZONS.items():
            target = bar["epoch"] + hours * 3600
            fwd = None
            for j in range(i + 1, len(bars)):
                if bars[j]["epoch"] >= target:
                    fwd = bars[j]
                    break
            if not fwd or fwd["mid"] <= 0 or bar["mid"] <= 0:
                continue
            ret = (fwd["mid"] - bar["mid"]) / bar["mid"]
            results.append({"signal": name, "side": direction, "horizon": label,
                            "ret": ret})
    return results


def aggregate(results):
    out = []
    seen = set()
    for r in results:
        key = (r["signal"], r["side"], r["horizon"])
        if key in seen:
            continue
        seen.add(key)
        subset = [x for x in results if (x["signal"], x["side"], x["horizon"]) == key]
        n = len(subset)
        hits = sum(1 for x in subset if (x["ret"] > 0) == (x["side"] > 0) and x["ret"] != 0)
        zeros = sum(1 for x in subset if x["ret"] == 0)
        mean_ret = sum(x["ret"] for x in subset) / n if n else 0.0
        out.append({
            "signal": r["signal"],
            "side": "bullish" if r["side"] > 0 else "bearish",
            "horizon": r["horizon"],
            "n": n,
            "hits": hits,
            "zeros": zeros,
            "hit_rate_excl_flat": (hits / (n - zeros)) if (n - zeros) else None,
            "hit_rate_incl_flat": hits / n if n else None,
            "mean_fwd_ret": mean_ret * 100.0,
        })
    return out


def baseline_returns(bars):
    """Unconditional mean forward return per horizon for comparison."""
    base = []
    for i, bar in enumerate(bars):
        if bar["mid"] <= 0:
            continue
        for label, hours in HORIZONS.items():
            target = bar["epoch"] + hours * 3600
            fwd = None
            for j in range(i + 1, len(bars)):
                if bars[j]["epoch"] >= target:
                    fwd = bars[j]
                    break
            if not fwd or fwd["mid"] <= 0:
                continue
            base.append({"horizon": label, "ret": (fwd["mid"] - bar["mid"]) / bar["mid"]})
    agg = {}
    for b in base:
        agg.setdefault(b["horizon"], []).append(b["ret"])
    return {k: (sum(v) / len(v)) * 100.0 for k, v in agg.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", default=os.path.join(
        os.path.dirname(__file__), "..", "data", "indicators.json"))
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    print(f"# Backtest report — Trading Indicators")
    print(f"Data last updated: {meta.get('last_updated')}")
    print(f"Source: {args.input}")
    print()

    for asset, asset_data in data.get("assets", {}).items():
        bars = parse_asset(asset_data)
        bars.sort(key=lambda b: b["epoch"])
        if len(bars) < 10:
            print(f"== {asset}: insufficient data ({len(bars)} bars) ==")
            continue

        results = []
        # Signal 1: depth 5% imbalance
        results += evaluate_signal(bars, "Depth 5%", lambda b: 1 if b["d5"] > 0 else (-1 if b["d5"] < 0 else 0), require_ts=1)
        # Signal 2: depth 25% imbalance
        results += evaluate_signal(bars, "Depth 25%", lambda b: 1 if b["d25"] > 0 else (-1 if b["d25"] < 0 else 0), require_ts=1)
        # Signal 3: CVD aggregate slope (8-bar)
        results += evaluate_signal(bars, "CVD Slope", lambda b: 1 if (b["cvd_slope"] or 0) > 0 else (-1 if (b["cvd_slope"] or 0) < 0 else 0), require_ts=9)
        # Signal 4: composite long-readiness
        results += evaluate_signal(bars, "Composite",
                                   lambda b: 1 if compute_composite(b) >= CONSTRUCTIVE_THRESHOLD else (-1 if compute_composite(b) <= CAUTION_THRESHOLD else 0),
                                   require_ts=9)

        print(f"== {asset} — {len(bars)} bars ==")
        base = baseline_returns(bars)
        print(f"  Baseline mean forward return: " + ", ".join(f"{h}: {v:+.3f}%" for h, v in sorted(base.items())))
        print()

        rows = sorted(aggregate(results), key=lambda r: (r["signal"], r["horizon"], r["side"]))
        header = f"{'Signal':<14} {'Side':<8} {'Horizon':<7} {'n':>4} {'HitRate':>8} {'HitRate*':>8} {'MeanFwd':>9}"
        print("  " + header)
        print("  " + "-" * len(header))
        for r in rows:
            hr = f"{r['hit_rate_incl_flat']:.1%}" if r["hit_rate_incl_flat"] is not None else "-"
            hrx = f"{r['hit_rate_excl_flat']:.1%}" if r["hit_rate_excl_flat"] is not None else "-"
            print(f"  {r['signal']:<14} {r['side']:<8} {r['horizon']:<7} {r['n']:>4} {hr:>8} {hrx:>8} {r['mean_fwd_ret']:>+8.3f}%")
        print("  * HitRate excludes flat (zero) forward returns.")
        print()


if __name__ == "__main__":
    main()
