"""
Portfolio state: persisted open positions, sector exposure caps, and
equity estimation helpers. positions.json is this script's bookkeeping -
always reconcile it against kite.positions()/kite.holdings() periodically
in case a manual trade or a missed cron run desyncs it.
"""
import json
import os
import csv
import datetime as dt
import config

POSITIONS_FILE = "positions.json"


def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)


def load_sector_map():
    if not os.path.exists(config.SECTOR_MAP_CSV):
        return {}
    with open(config.SECTOR_MAP_CSV) as f:
        return {row["symbol"]: row["sector"] for row in csv.DictReader(f)}


def sector_counts(positions, sector_map):
    counts = {}
    for sym in positions:
        sec = sector_map.get(sym, "UNKNOWN")
        counts[sec] = counts.get(sec, 0) + 1
    return counts


def can_add_position(symbol, positions, sector_map):
    if len(positions) >= config.MAX_POSITIONS:
        return False, "max_positions_reached"
    sec = sector_map.get(symbol, "UNKNOWN")
    counts = sector_counts(positions, sector_map)
    if counts.get(sec, 0) >= config.MAX_PER_SECTOR:
        return False, f"sector_cap_reached:{sec}"
    return True, "ok"


def add_position(symbol, qty, entry_price, stop_price, atr_value, sector):
    positions = load_positions()
    positions[symbol] = {
        "qty": qty,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "atr": atr_value,
        "sector": sector,
        "entry_date": dt.date.today().isoformat(),
        "partial_booked": False,
    }
    save_positions(positions)


def remove_position(symbol):
    positions = load_positions()
    positions.pop(symbol, None)
    save_positions(positions)


def total_equity_estimate(positions, ltp_map, cash):
    invested_value = sum(
        p["qty"] * ltp_map.get(sym, p["entry_price"]) for sym, p in positions.items()
    )
    return cash + invested_value
