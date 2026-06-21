"""
Simplified, DIRECTIONAL backtest. This is a sanity check, not a precision
simulator: no slippage, no partial fills, no intraday stop-hit detection
(stops are only checked at month-end marks), and rank-decay/100DMA exits
are not modelled. Use it to confirm the ranking + entry filter logic
produces a sensible-looking equity curve before paper trading - then
paper-trade live for at least one full regime cycle before real capital.
"""
import pandas as pd
import config
from indicators import atr
from entry_filter import passes_entry_filter


def backtest(fetcher, universe, months=24):
    history = {sym: fetcher.historical(sym, days=900) for sym in universe}
    history = {k: v for k, v in history.items() if not v.empty}

    cash = config.EQUITY
    open_positions = {}  # symbol -> {entry, stop, qty}
    equity_curve = []

    all_dates = sorted(set().union(*[h.index for h in history.values()]))
    month_ends = (
        pd.Series(all_dates)
        .groupby(pd.Series(all_dates).dt.to_period("M"))
        .max()
        .tolist()[-months:]
    )

    for as_of in month_ends:
        # 1. mark-to-market + month-end stop check on existing positions
        for sym in list(open_positions):
            h = history.get(sym)
            if h is None or as_of not in h.index:
                continue
            pos = open_positions[sym]
            price = h.loc[:as_of, "close"].iloc[-1]
            if price <= pos["stop"]:
                cash += pos["qty"] * price
                del open_positions[sym]

        # 2. rank universe as of this month-end
        rows = []
        for sym, h in history.items():
            sl = h.loc[:as_of]
            if len(sl) < 260:
                continue
            close = sl["close"]
            score = (
                config.MOM_WEIGHTS["12m"] * close.pct_change(252).iloc[-1]
                + config.MOM_WEIGHTS["6m"] * close.pct_change(126).iloc[-1]
                + config.MOM_WEIGHTS["3m"] * close.pct_change(63).iloc[-1]
            )
            rows.append({"symbol": sym, "score": score})
        ranked = pd.DataFrame(rows)
        if not ranked.empty:
            ranked = ranked.sort_values("score", ascending=False).head(config.TOP_N_RANK)

        # 3. new entries
        unrealized = sum(
            open_positions[s]["qty"] * history[s].loc[:as_of, "close"].iloc[-1]
            for s in open_positions
        )
        equity_now = cash + unrealized

        for _, row in ranked.iterrows() if not ranked.empty else []:
            sym = row["symbol"]
            if sym in open_positions or len(open_positions) >= config.MAX_POSITIONS:
                continue
            h = history[sym].loc[:as_of]
            passed, details = passes_entry_filter(h)
            if not passed:
                continue
            a = atr(h, config.ATR_PERIOD).iloc[-1]
            entry = details["price"]
            stop = entry - config.ATR_STOP_MULT * a
            if entry <= stop:
                continue
            qty = int((equity_now * config.RISK_PER_TRADE_PCT) / (entry - stop))
            cost = qty * entry
            if qty > 0 and cost <= cash:
                cash -= cost
                open_positions[sym] = {"entry": entry, "stop": stop, "qty": qty}

        unrealized = sum(
            open_positions[s]["qty"] * history[s].loc[:as_of, "close"].iloc[-1]
            for s in open_positions
        )
        equity_curve.append({"date": as_of, "equity": cash + unrealized})

    return pd.DataFrame(equity_curve)


if __name__ == "__main__":
    from kite_auth import get_kite
    from data_fetcher import DataFetcher
    from universe import build_universe

    kite = get_kite()
    fetcher = DataFetcher(kite)
    universe = build_universe(fetcher)
    curve = backtest(fetcher, universe)
    print(curve)
    curve.to_csv("backtest_equity_curve.csv", index=False)
