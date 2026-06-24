"""
Exit logic, evaluated once per day for every open position, in priority
order: SEVERE-tier market filter -> hard stop -> rank decay (tier-aware
threshold) -> trend break -> time stop -> partial profit booking.

Only the SEVERE tier forces an exit regardless of how the individual stock
looks - see regime_filter.py for why CAUTION deliberately does not.
"""
import datetime as dt
import config
from indicators import dma


def evaluate_exit(symbol, pos, hist, rank_df, regime):
    close = hist["close"]
    last_price = close.iloc[-1]
    sma100 = dma(close, 100).iloc[-1]

    if regime["force_exit_all"]:
        return "FULL_EXIT", "market_filter_severe"

    if last_price <= pos["stop_price"]:
        return "FULL_EXIT", "stop_hit"

    rank_threshold = regime["rank_exit_threshold"]
    rank_row = rank_df[rank_df["symbol"] == symbol] if rank_df is not None and not rank_df.empty else None
    if rank_row is not None and (rank_row.empty or rank_row.iloc[0]["rank"] > rank_threshold):
        return "FULL_EXIT", "rank_decayed"

    if last_price < sma100:
        return "FULL_EXIT", "below_100dma"

    entry_date = dt.date.fromisoformat(pos["entry_date"])
    days_held = (dt.date.today() - entry_date).days
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
