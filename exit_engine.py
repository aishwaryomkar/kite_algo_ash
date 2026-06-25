"""
Exit logic, evaluated once per day for every open position, in priority
order: hard stop -> rank decay (tier-aware threshold) -> trend break ->
time stop -> partial profit booking.

Regime does NOT force an exit at any tier, including SEVERE - that's a
deliberate choice, not an oversight. Every exit here is driven by the
stock's own behavior; regime only ever affects entries and how tight the
rank threshold is.
"""
import datetime as dt
import config
from indicators import dma


def evaluate_exit(symbol, pos, hist, rank_df, regime, as_of=None):
    """
    as_of: the date to treat as "now" for the time-stop's days-held
    calculation. Defaults to the real current date for live use. A
    backtest MUST pass the simulated date here - without it, days_held
    would be computed against the real calendar date this code happens to
    run on, not the simulated one, making the time-stop fire almost
    immediately on every position regardless of how long it was actually
    "held" in the simulation.
    """
    current_date = as_of if as_of is not None else dt.date.today()

    close = hist["close"]
    last_price = close.iloc[-1]
    sma100 = dma(close, 100).iloc[-1]

    if last_price <= pos["stop_price"]:
        return "FULL_EXIT", "stop_hit"

    rank_threshold = regime["rank_exit_threshold"]
    rank_row = rank_df[rank_df["symbol"] == symbol] if rank_df is not None and not rank_df.empty else None
    if rank_row is not None and (rank_row.empty or rank_row.iloc[0]["rank"] > rank_threshold):
        return "FULL_EXIT", "rank_decayed"

    if last_price < sma100:
        return "FULL_EXIT", "below_100dma"

    entry_date = dt.date.fromisoformat(pos["entry_date"])
    if hasattr(current_date, "date"):
        current_date = current_date.date()  # pandas Timestamp -> date, for a clean subtraction
    days_held = (current_date - entry_date).days
    risk_per_share = pos["entry_price"] - pos["stop_price"]
    r_multiple = (last_price - pos["entry_price"]) / risk_per_share if risk_per_share > 0 else 0

    # ENHANCEMENT: time stop - if a name has gone nowhere (<1R either way)
    # for 20 sessions, it's dead capital sitting in a slot another
    # momentum name could use. Cut it loose rather than waiting for a stop.
    if days_held >= config.TIME_STOP_DAYS and abs(r_multiple) < 1.0:
        return "FULL_EXIT", "time_stop_flat"

    # ENHANCEMENT: partial profit booking at 1.5R locks in gains on names
    # that move fast, instead of giving the whole move back on the
    # inevitable pullback before the 100DMA/rank exit eventually triggers.
    if (not pos.get("partial_booked")) and r_multiple >= config.PARTIAL_BOOK_R_MULT:
        return "PARTIAL_EXIT", "partial_profit_booked"

    return "HOLD", None
