"""
Builds the tradeable universe: Nifty 500 constituents, minus illiquid or
low-priced names, names above the price ceiling, and anything on the
excluded-holdings list. NSE publishes the official constituent list as a
CSV; we cache it locally because the hosting path occasionally moves, and
because hammering NSE's site on every run is unnecessary and rate-limited.
"""
import csv
import os
import pandas as pd
import requests
import config

NIFTY500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
LOCAL_CACHE = "nifty500.csv"


def fetch_nifty500_list():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(NIFTY500_URL, headers=headers, timeout=10)
        r.raise_for_status()
        with open(LOCAL_CACHE, "wb") as f:
            f.write(r.content)
    except Exception as e:
        print(f"Live NSE fetch failed ({e}); falling back to local cache '{LOCAL_CACHE}'.")
    df = pd.read_csv(LOCAL_CACHE)
    return df["Symbol"].tolist()


def load_excluded_holdings():
    """
    Symbols this algo must never touch - existing discretionary holdings,
    ETFs, SGBs, etc. This is checked BEFORE any historical data is even
    pulled for a symbol, so an excluded name can never enter the ranking
    pool, let alone get bought or sold.
    """
    if not os.path.exists(config.EXCLUDED_HOLDINGS_CSV):
        return set()
    with open(config.EXCLUDED_HOLDINGS_CSV) as f:
        return {row["symbol"].strip().upper() for row in csv.DictReader(f)}


def apply_liquidity_filter(symbols, fetcher):
    """Drop symbols below the turnover floor, outside the price band, or
    on the exclusion list."""
    excluded = load_excluded_holdings()
    keep = []
    for sym in symbols:
        if sym.strip().upper() in excluded:
            continue
        try:
            hist = fetcher.historical(sym, days=40)
            if hist.empty or len(hist) < config.TURNOVER_LOOKBACK_DAYS:
                continue
            recent = hist.tail(config.TURNOVER_LOOKBACK_DAYS)
            avg_turnover = (recent["close"] * recent["volume"]).mean()
            last_price = recent["close"].iloc[-1]
            if not (config.MIN_PRICE <= last_price <= config.MAX_PRICE):
                continue
            if avg_turnover >= config.MIN_AVG_TURNOVER:
                keep.append(sym)
        except Exception as e:
            print(f"Skipping {sym} in universe build: {e}")
            continue
    return keep


def build_universe(fetcher):
    raw = fetch_nifty500_list()
    return apply_liquidity_filter(raw, fetcher)
