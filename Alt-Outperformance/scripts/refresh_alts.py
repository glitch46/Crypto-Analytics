#!/usr/bin/env python3
"""Build BTC-relative performance dataset from CoinGecko top liquid alts."""
import datetime
import json
import os
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
MAX_COINS = 100

EXCLUDE_IDS = {
    "bitcoin",
    "tether", "usd-coin", "dai", "binance-usd", "true-usd", "first-digital-usd",
    "paypal-usd", "usdd", "frax", "susd", "gho", "crvusd", "liquity-usd",
    "gemini-dollar", "pax-dollar", "ethena-usde", "usual-usd", "dola-usd",
    "wrapped-bitcoin", "wrapped-ether", "wrapped-steth", "staked-ether",
    "coinbase-wrapped-staked-eth", "rocket-pool-eth", "coinbase-wrapped-btc",
    "binance-bitcoin", "mantle-staked-ether", "wrapped-eeth",
    "binance-staked-sol", "marinade-staked-sol", "jito-staked-sol",
}

EXCLUDE_SYMBOLS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "PYUSD", "USDD",
    "FRAX", "SUSD", "GHO", "LUSD", "GUSD", "USDP", "USDE",
    "WBTC", "WETH", "WSTETH", "STETH", "CBETH", "RETH", "CBBTC", "BTCB",
}

SECTOR_MAP = {
    "ethereum": "L1", "binancecoin": "L1", "solana": "L1", "cardano": "L1",
    "avalanche-2": "L1", "polkadot": "L1", "tron": "L1", "near": "L1",
    "internet-computer": "L1", "aptos": "L1", "sui": "L1", "kaspa": "L1",
    "cosmos": "L1", "algorand": "L1", "hedera-hashgraph": "L1", "stellar": "L1",
    "matic-network": "L2", "arbitrum": "L2", "optimism": "L2", "starknet": "L2",
    "mantle": "L2", "immutable-x": "L2", "polygon-ecosystem-token": "L2",
    "uniswap": "DeFi", "aave": "DeFi", "chainlink": "DeFi", "maker": "DeFi",
    "lido-dao": "DeFi", "raydium": "DeFi", "pancakeswap-token": "DeFi",
    "curve-dao-token": "DeFi", "the-graph": "DeFi", "thorchain": "DeFi",
    "pendle": "DeFi", "ondo-finance": "DeFi", "ethena": "DeFi", "hyperliquid": "DeFi",
    "dogecoin": "Meme", "shiba-inu": "Meme", "pepe": "Meme", "dogwifcoin": "Meme",
    "floki": "Meme", "bonk": "Meme", "brett": "Meme", "official-trump": "Meme",
    "render-token": "AI", "fetch-ai": "AI", "bittensor": "AI",
    "artificial-superintelligence-alliance": "AI", "akash-network": "AI",
    "the-sandbox": "Gaming", "axie-infinity": "Gaming", "decentraland": "Gaming",
    "gala": "Gaming", "illuvium": "Gaming",
    "crypto-com-chain": "Exchange", "leo-token": "Exchange", "okb": "Exchange",
    "kucoin-shares": "Exchange", "bitget-token": "Exchange", "gate-token": "Exchange",
    "monero": "Privacy", "zcash": "Privacy",
    "filecoin": "Infra", "arweave": "Infra", "theta-token": "Infra", "helium": "Infra",
    "ripple": "Payments", "litecoin": "Payments", "bitcoin-cash": "Payments",
    "vechain": "Supply Chain", "quant-network": "Interop",
}


def fetch_json(url, retries=6):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "alt-outperformance-dashboard/1.0",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as err:
            if err.code == 429 and attempt < retries - 1:
                wait = 25 + (attempt * 20)
                print(f"429 rate-limit hit. Waiting {wait}s.")
                time.sleep(wait)
                continue
            raise


def fetch_top_market_coins():
    query = urllib.parse.urlencode({
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 250,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "7d,14d,30d",
    })
    return fetch_json(f"{COINGECKO_BASE}/coins/markets?{query}")


def fetch_price_history(coin_id, days=30):
    query = urllib.parse.urlencode({"vs_currency": "usd", "days": days, "interval": "daily"})
    payload = fetch_json(f"{COINGECKO_BASE}/coins/{coin_id}/market_chart?{query}")
    output = []
    for ts, price in payload.get("prices", []):
        date = datetime.datetime.fromtimestamp(ts / 1000, datetime.UTC).strftime("%Y-%m-%d")
        output.append({"date": date, "price": price})
    return output


def should_exclude(coin):
    cid = coin.get("id", "")
    sym = (coin.get("symbol") or "").upper()
    name = (coin.get("name") or "").lower()
    volume = float(coin.get("total_volume") or 0)

    if cid in EXCLUDE_IDS or sym in EXCLUDE_SYMBOLS:
        return True
    if volume < 8_000_000:
        return True

    blocks = ("usd", "dollar", "treasury", "fund", "yield", "bond", "cash", "money")
    if any(token in cid for token in blocks) or any(token in name for token in blocks):
        return True
    return False


def compute_relative_return(alt_map, btc_map, days):
    dates = sorted(set(alt_map.keys()) & set(btc_map.keys()))
    if len(dates) < 2:
        return None
    end_date = dates[-1]
    target = (datetime.datetime.strptime(end_date, "%Y-%m-%d") - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    start_date = next((d for d in dates if d >= target), None)
    if not start_date or start_date == end_date:
        return None

    alt_start, alt_end = alt_map.get(start_date), alt_map.get(end_date)
    btc_start, btc_end = btc_map.get(start_date), btc_map.get(end_date)
    if not alt_start or not btc_start:
        return None
    alt_ret = (alt_end - alt_start) / alt_start * 100
    btc_ret = (btc_end - btc_start) / btc_start * 100
    return round(alt_ret - btc_ret, 2)


def build_daily_relative(alt_map, btc_map):
    dates = sorted(set(alt_map.keys()) & set(btc_map.keys()))
    if len(dates) < 2:
        return []
    base = dates[0]
    alt_base = alt_map.get(base)
    btc_base = btc_map.get(base)
    if not alt_base or not btc_base:
        return []
    series = []
    for d in dates:
        alt_ret = (alt_map[d] - alt_base) / alt_base * 100
        btc_ret = (btc_map[d] - btc_base) / btc_base * 100
        series.append({"date": d, "relative_pct": round(alt_ret - btc_ret, 3)})
    return series


def collect_alt_data(candidates, btc_map):
    alts = []
    backlog = list(candidates)
    round_num = 1

    while backlog and len(alts) < MAX_COINS and round_num <= 5:
        print(f"Round {round_num}: attempting {len(backlog)} coins")
        failed = []
        for coin in backlog:
            if len(alts) >= MAX_COINS:
                break
            cid = coin["id"]
            sym = (coin.get("symbol") or "").upper()
            print(f"  fetch {sym} ({cid})")
            try:
                history = fetch_price_history(cid, 30)
            except Exception as err:
                print(f"    failed: {err}")
                failed.append(coin)
                time.sleep(8)
                continue

            alt_map = {row["date"]: row["price"] for row in history}
            daily_relative = build_daily_relative(alt_map, btc_map)
            if not daily_relative:
                failed.append(coin)
                time.sleep(6)
                continue

            alts.append({
                "id": cid,
                "symbol": sym,
                "name": coin.get("name", ""),
                "market_cap_rank": coin.get("market_cap_rank"),
                "market_cap": coin.get("market_cap", 0),
                "current_price": coin.get("current_price", 0),
                "sector": SECTOR_MAP.get(cid, "Other"),
                "relative_7d": compute_relative_return(alt_map, btc_map, 7),
                "relative_14d": compute_relative_return(alt_map, btc_map, 14),
                "relative_30d": compute_relative_return(alt_map, btc_map, 30),
                "daily_relative": daily_relative,
            })

            if len(alts) % 10 == 0:
                time.sleep(20)
            else:
                time.sleep(4)

        backlog = failed
        if backlog and len(alts) < MAX_COINS:
            cooloff = 70 * round_num
            print(f"Round cooldown: {cooloff}s, backlog={len(backlog)}")
            time.sleep(cooloff)
        round_num += 1

    return alts


def main():
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(output_dir, exist_ok=True)

    print("Fetching market universe from CoinGecko...")
    markets = fetch_top_market_coins()
    if not isinstance(markets, list):
        raise RuntimeError("Could not fetch market list")

    candidates = [coin for coin in markets if not should_exclude(coin)]
    candidates.sort(key=lambda c: c.get("market_cap_rank") or 9999)
    print(f"Candidates after filters: {len(candidates)}")

    print("Fetching BTC history...")
    btc_history = fetch_price_history("bitcoin", 30)
    btc_map = {row["date"]: row["price"] for row in btc_history}

    alts = collect_alt_data(candidates, btc_map)
    alts.sort(key=lambda c: c.get("relative_30d") if c.get("relative_30d") is not None else -9999, reverse=True)

    output = {
        "btc_prices": btc_history,
        "alts": alts,
    }
    with open(os.path.join(output_dir, "alt_performance.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    meta = {
        "last_updated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "sources": ["CoinGecko"],
        "coin_count": len(alts),
    }
    with open(os.path.join(output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"Done. Stored {len(alts)} alts.")


if __name__ == "__main__":
    main()
