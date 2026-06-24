"""
Sanity-check backtest - DIRECTIONAL, not execution-precise. No slippage, no
partial fills, intraday stop-hits only checked at month-end marks. Use this
to see whether the ranking + entry filter + regime logic produces a
sensible-looking equity curve - then paper-trade live for at least one full
regime cycle before real capital. This does NOT run by itself - it needs a
live Kite session (real historical data), so run it on your EC2 box where
Kite Connect is actually authenticated:

    python backtest.py --universe nifty50 --fixed-buy 10000 --years 2

Two sizing modes:
  --fixed-buy AMOUNT   Buy exactly AMOUNT (rupees, rounded to whole shares)
    of every signal that passes the filters, ignoring risk-based sizing,
    conviction scaling, and the capital-per-stock cap (MAX_POSITIONS still
    applies). Useful for answering "what if I just put a flat Rs10k into
    every signal" directly, without the risk-engine math in between.
  (default, no --fixed-buy)   Uses the same risk-based sizing as the live
    bot (ATR stop distance, RISK_PER_TRADE_PCT, conviction scaling, capital
    cap) - closer to what main.py would actually have done historically.
"""
import argparse
import pandas as pd
import config
from indicators import atr
from entry_filter import passes_entry_filter
from regime_filter import regime_state
from risk_engine import size_position, atr_stop


def backtest(fetcher, universe, months=24, fixed_buy_amount=None,
             starting_capital=0, monthly_contribution=0):
    """
    starting_capital / monthly_contribution simulate a growing account fed by
    real monthly top-ups (e.g. Rs8-10k/month) rather than assuming a single
    lump sum was deployed on day one - closer to how this account actually
    gets funded in practice.
    """
    history = {sym: fetcher.historical(sym, days=900) for sym in universe}
    history = {k: v for k, v in history.items() if not v.empty}

    cash = starting_capital
    total_contributed = starting_capital
    open_positions = {}  # symbol -> {entry, stop, qty}
    equity_curve = []
    trade_log = []

    all_dates = sorted(set().union(*[h.index for h in history.values()]))
    month_ends = (
        pd.Series(all_dates)
        .groupby(pd.Series(all_dates).dt.to_period("M"))
        .max()
        .tolist()[-months:]
    )

    for as_of in month_ends:
        # 0. monthly capital injection - happens before that month's trading
        if monthly_contribution:
            cash += monthly_contribution
            total_contributed += monthly_contribution

        # 1. mark-to-market + month-end stop check on existing positions
        for sym in list(open_positions):
            h = history.get(sym)
            if h is None or as_of not in h.index:
                continue
            pos = open_positions[sym]
            price = h.loc[:as_of, "close"].iloc[-1]
            if price <= pos["stop"]:
                cash += pos["qty"] * price
                trade_log.append({"date": as_of, "symbol": sym, "action": "SELL",
                                   "qty": pos["qty"], "price": price, "reason": "stop_hit"})
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

        # 3. regime check as of this month-end (uses the SAME 3-tier logic
        # as the live bot - SEVERE blocks entries entirely, CAUTION halves size)
        regime = regime_state(fetcher, universe, equity=cash)
        entry_mult = regime["entry_size_mult"]

        # 4. new entries
        unrealized = sum(
            open_positions[s]["qty"] * history[s].loc[:as_of, "close"].iloc[-1]
            for s in open_positions
        )
        equity_now = cash + unrealized

        if entry_mult > 0:
            for _, row in (ranked.iterrows() if not ranked.empty else []):
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

                if fixed_buy_amount is not None:
                    qty = int(fixed_buy_amount / entry)
                else:
                    qty = size_position(entry, stop, equity_now, fetcher, sym, conviction_mult=entry_mult)

                cost = qty * entry
                if qty > 0 and cost <= cash:
                    cash -= cost
                    open_positions[sym] = {"entry": entry, "stop": stop, "qty": qty}
                    trade_log.append({"date": as_of, "symbol": sym, "action": "BUY",
                                       "qty": qty, "price": entry, "reason": f"tier={regime['tier']}"})

        unrealized = sum(
            open_positions[s]["qty"] * history[s].loc[:as_of, "close"].iloc[-1]
            for s in open_positions
        )
        equity_curve.append({
            "date": as_of, "equity": cash + unrealized, "cash": cash,
            "positions": len(open_positions), "regime_tier": regime["tier"],
            "total_contributed": total_contributed,
        })

    return pd.DataFrame(equity_curve), pd.DataFrame(trade_log)


def summarize(equity_df):
    if equity_df.empty:
        print("No data produced - check universe/date range.")
        return
    end = equity_df["equity"].iloc[-1]
    contributed = equity_df["total_contributed"].iloc[-1]
    running_max = equity_df["equity"].cummax()
    drawdown = (equity_df["equity"] - running_max) / running_max.replace(0, pd.NA)
    print(f"\nTotal contributed over the period: Rs{contributed:,.0f}")
    print(f"Final equity: Rs{end:,.0f}")
    if contributed > 0:
        print(f"Gain/loss vs. what you put in: {(end / contributed - 1):+.1%}")
    print(f"Max drawdown (peak-to-trough on the equity curve itself): {drawdown.min():.1%}")
    print(f"Months with SEVERE regime tier: {(equity_df['regime_tier'] == 'SEVERE').sum()} / {len(equity_df)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the sanity-check backtest against real Kite historical data.")
    parser.add_argument("--universe", choices=["nifty50", "nifty500"], default="nifty50")
    parser.add_argument("--fixed-buy", type=float, default=None,
                         help="Flat rupee amount per signal, e.g. 10000. Omit to use risk-based sizing instead.")
    parser.add_argument("--years", type=float, default=2.0, help="Lookback period in years (1-3 typical).")
    parser.add_argument("--starting-capital", type=float, default=0,
                         help="Capital already in the account before the backtest period starts.")
    parser.add_argument("--monthly-contribution", type=float, default=10000,
                         help="Rupees added to cash at the start of each month, simulating real top-ups. Set to 0 to disable.")
    args = parser.parse_args()

    from kite_auth import get_kite
    from data_fetcher import DataFetcher
    from universe import build_universe

    kite = get_kite()
    fetcher = DataFetcher(kite)
    universe = build_universe(fetcher, universe_choice=args.universe)
    print(f"Universe ({args.universe}): {len(universe)} symbols after liquidity/price filters")

    months = int(args.years * 12)
    equity_df, trades_df = backtest(
        fetcher, universe, months=months, fixed_buy_amount=args.fixed_buy,
        starting_capital=args.starting_capital, monthly_contribution=args.monthly_contribution,
    )
    summarize(equity_df)
    equity_df.to_csv("backtest_equity_curve.csv", index=False)
    trades_df.to_csv("backtest_trades.csv", index=False)
    print("\nSaved backtest_equity_curve.csv and backtest_trades.csv")
