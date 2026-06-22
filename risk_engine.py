"""
Risk engine. Sits between signal generation and order placement - nothing
in this system is allowed to place an order without passing through here
first. Owns: position sizing (with a liquidity cap on top of the risk-based
cap), ATR-based stops, the kill switch state machine, and re-entry cooldowns.
"""
import json
import os
import datetime as dt
import config
from indicators import atr

STATE_FILE = "risk_state.json"


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return None  # signals "no state yet" - caller must seed from real equity


def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_equity_peak(current_equity):
    """
    Called once per run with the REAL, live-computed equity (cash + holdings
    value). On the very first run ever, this is what seeds equity_peak - not
    config.EQUITY, which is just a sizing fallback and may not match actual
    capital deployed. Seeding from a static config constant instead of real
    equity is exactly how a small/growing account gets a phantom drawdown.
    """
    state = _load_state() or {"equity_peak": current_equity, "cooldowns": {}}
    state["equity_peak"] = max(state["equity_peak"], current_equity)
    _save_state(state)
    return state["equity_peak"]


def current_drawdown(current_equity):
    state = _load_state()
    if state is None:
        return 0.0  # no history yet - can't be in drawdown on the first observation
    peak = max(state["equity_peak"], current_equity)
    return (peak - current_equity) / peak if peak > 0 else 0.0


def kill_switch_action(current_equity):
    """Returns (most_severe_action_or_None, drawdown_fraction)."""
    dd = current_drawdown(current_equity)
    triggered = [action for level, action in config.KILL_SWITCH_LEVELS if dd >= level]
    return (triggered[-1] if triggered else None), dd


def size_position(entry_price, stop_price, equity, fetcher, symbol):
    """
    Risk-based size, capped by:
      - max capital per stock (config.MAX_CAPITAL_PCT_PER_STOCK)
      - max participation in 20-day average daily volume (ENHANCEMENT -
        this is the slippage control; risk-based sizing alone can size you
        into 2-3 days of a thin stock's volume, which is how "the model
        was right but the fill killed it" happens)
    """
    risk_amount = equity * config.RISK_PER_TRADE_PCT
    stop_distance = entry_price - stop_price
    if stop_distance <= 0:
        return 0
    qty_risk = int(risk_amount / stop_distance)
    qty_capital_cap = int((equity * config.MAX_CAPITAL_PCT_PER_STOCK) / entry_price)

    hist = fetcher.historical(symbol, days=30)
    avg_vol = hist["volume"].tail(20).mean() if not hist.empty else 0
    qty_liquidity_cap = int(avg_vol * config.MAX_ADV_PARTICIPATION) if avg_vol > 0 else qty_risk

    return max(min(qty_risk, qty_capital_cap, qty_liquidity_cap), 0)


def atr_stop(hist):
    a = atr(hist, config.ATR_PERIOD).iloc[-1]
    entry = hist["close"].iloc[-1]
    return entry - config.ATR_STOP_MULT * a, a


def apply_kill_switch_to_size(qty, action):
    if action == "REDUCE_25":
        return int(qty * 0.75)
    if action == "REDUCE_50":
        return int(qty * 0.50)
    if action in ("NO_NEW_ENTRIES", "EXIT_WEAKEST_HALF", "EXIT_ALL"):
        return 0
    return qty


def is_in_cooldown(symbol):
    state = _load_state()
    if state is None:
        return False
    until = state["cooldowns"].get(symbol)
    if not until:
        return False
    return dt.date.today() < dt.date.fromisoformat(until)


def start_cooldown(symbol):
    state = _load_state() or {"equity_peak": config.EQUITY, "cooldowns": {}}
    until = dt.date.today() + dt.timedelta(days=config.REENTRY_COOLDOWN_DAYS)
    state["cooldowns"][symbol] = until.isoformat()
    _save_state(state)
