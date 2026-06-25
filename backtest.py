"""
Sanity-check backtest - DIRECTIONAL, not execution-precise. No slippage, no
partial fills. Exit logic now calls the REAL exit_engine.evaluate_exit()
(stop, rank decay, 100DMA break, time stop, partial booking) instead of a
simplified month-end-stop-only approximation - that gap was a real source
of pessimistic bias versus what the live bot would actually do, since the
live bot exits decaying/broken-trend positions much faster than "wait for
either a hard stop or the next month's rebalance." Ranking also now
replicates screener.py's actual relative-strength scoring and reuses the
real add_conviction() function, point-in-time-sliced rather than refetched
live (fetcher.historical() always returns up to TODAY, with no way to pass
a historical cutoff - see _point_in_time_regime's docstring for the same
issue solved the same way).

Use this to see whether the ranking + entry filter + regime + exit logic
together produce a sensible-looking equity curve - then paper-trade live
for at least one full regime cycle before real capital. This does NOT run
by itself - it needs a live Kite session (real historical data), so run it
on your EC2 box where Kite Connect is actually authenticated:

    python backtest.py --universe nifty50 --years 2

Two sizing modes:
  --fixed-buy AMOUNT   Buy exactly AMOUNT (rupees, rounded to whole shares)
    of every signal that passes the filters, ignoring risk-based sizing,
    conviction scaling, and the capital-per-stock cap (MAX_POSITIONS still
    applies).
  (default, no --fixed-buy)   Uses the same risk-based sizing as the live
    bot (ATR stop distance, RISK_PER_TRADE_PCT, conviction scaling, capital
    cap).
"""
import argparse
import pandas as pd
import config
from indicators import atr, dma, returns
from entry_filter import passes_entry_filter
from regime_filter import classify_tier
from risk_engine import size_position, atr_stop
from exit_engine import evaluate_exit
from screener import add_conviction


def _point_in_time_rank(history, universe, as_of):
    """
    Replicates screener.rank_universe()'s scoring exactly (including
    relative-strength-vs-benchmark when enabled), but sliced to `as_of`
    instead of calling fetcher.historical() (which always returns data up
    to TODAY - the same point-in-time problem _point_in_time_regime solves
    for the regime check). Returns the FULL ranked dataframe, not just the
    top N - evaluate_exit's rank-decay check needs to know a HELD
    position's actual rank even if it has fallen out of the top 20.
    """
    bench = None
    if config.RANK_BY_RELATIVE_STRENGTH:
        bench_hist = history.get(config.REGIME_INDEX)
        if bench_hist is not None and as_of in bench_hist.index:
            bsl = bench_hist.loc[:as_of, "close"]
            if len(bsl) >= 260:
                bench = {252: returns(bsl, 252).iloc[-1], 126: returns(bsl, 126).iloc[-1], 63: returns(bsl, 63).iloc[-1]}

    rows = []
    for sym in universe:
        h = history.get(sym)
        if h is None or as_of not in h.index:
            continue
        sl = h.loc[:as_of]
        if len(sl) < 260:
            continue
        close = sl["close"]
        r12, r6, r3 = returns(close, 252).iloc[-1], returns(close, 126).iloc[-1], returns(close, 63).iloc[-1]
        if pd.isna(r12) or pd.isna(r6) or pd.isna(r3):
            continue
        if bench:
            r12, r6, r3 = r12 - bench[252], r6 - bench[126], r3 - bench[63]
        score = config.MOM_WEIGHTS["12m"] * r12 + config.MOM_WEIGHTS["6m"] * r6 + config.MOM_WEIGHTS["3m"] * r3
        rows.append({"symbol": sym, "score": score})

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def _point_in_time_regime(history, universe, as_of, equity):
    """
    Regime read AS OF a specific historical date, not today. fetcher.historical()
    always fetches up to the CURRENT date with no way to pass a cutoff, so
    calling regime_state(fetcher, ...) inside a backtest loop silently
    computes TODAY's regime on every iteration regardless of which month is
    being evaluated - a real bug found in production: a 24-month backtest
    showed "24/24 months SEVERE" because it was reading today's regime 24
    times, not 24 different historical months. This slices the ALREADY
    historical-fetched `history` dict up to `as_of` instead, and reuses the
    exact same tier-classification logic as the live bot via classify_tier().
    """
    idx_hist = history.get(config.REGIME_INDEX)
    if idx_hist is None or as_of not in idx_hist.index:
        idx_ok = False  # no data yet this far back - treat conservatively
    else:
        close = idx_hist.loc[:as_of, "close"]
        if len(close) < config.REGIME_DMA_PERIOD + config.REGIME_SLOPE_LOOKBACK:
            idx_ok = False
        else:
            sma200 = dma(close, config.REGIME_DMA_PERIOD)
            slope = (sma200 - sma200.shift(config.REGIME_SLOPE_LOOKBACK)) / config.REGIME_SLOPE_LOOKBACK
            idx_ok = bool(close.iloc[-1] > sma200.iloc[-1] and slope.iloc[-1] > 0)

    above, total = 0, 0
    for sym in universe:
        h = history.get(sym)
        if h is None or as_of not in h.index:
            continue
        sl = h.loc[:as_of, "close"]
        if len(sl) < config.REGIME_DMA_PERIOD:
            continue
        sma200 = dma(sl, config.REGIME_DMA_PERIOD)
        total += 1
        if sl.iloc[-1] > sma200.iloc[-1]:
            above += 1
    breadth_pct = (above / total) if total else 0.0

    return classify_tier(idx_ok, breadth_pct, equity)


def backtest(fetcher, universe, months=24, fixed_buy_amount=None,
             starting_capital=0, monthly_contribution=0):
    """
    starting_capital / monthly_contribution simulate a growing account fed by
    real monthly top-ups (e.g. Rs8-10k/month) rather than assuming a single
    lump sum was deployed on day one - closer to how this account actually
    gets funded in practice.
    """
    # Fetch enough history to cover the requested backtest window PLUS the
    # ~260-day momentum lookback the ranking needs at the very first
    # evaluated month - a hardcoded 900 days here silently truncated any
    # --years request longer than ~30 months to whatever was available,
    # with no warning that it had done so.
    fetch_days = max(900, months * 31 + 280)
    history = {sym: fetcher.historical(sym, days=fetch_days) for sym in universe}
    history = {k: v for k, v in history.items() if not v.empty}
    if config.REGIME_INDEX not in history:
        history[config.REGIME_INDEX] = fetcher.historical(config.REGIME_INDEX, days=fetch_days)

    cash = starting_capital
    total_contributed = starting_capital
    open_positions = {}  # symbol -> {entry, stop, qty}
    equity_curve = []
    trade_log = []

    # Benchmark: same monthly contribution schedule, but just buys the
    # regime index every month instead of running the strategy. Without
    # this, a negative "gain/loss vs contributed" number is unanchored -
    # it doesn't tell you whether the strategy did better or worse than
    # simply not running it at all.
    bench_hist = history.get(config.REGIME_INDEX)
    bench_units = 0.0

    all_dates = sorted(set().union(*[h.index for h in history.values()]))
    month_ends = (
        pd.Series(all_dates)
        .groupby(pd.Series(all_dates).dt.to_period("M"))
        .max()
        .tolist()
    )
    if len(month_ends) < months:
        print(
            f"WARNING: requested {months} months but only {len(month_ends)} are "
            f"available from the fetched history - results below cover "
            f"{len(month_ends)} months, not {months}. This is most likely Kite's "
            f"historical data simply not going back further for these symbols."
        )
    month_ends = month_ends[-months:]

    for as_of in month_ends:
        # 0. monthly capital injection - happens before that month's trading
        if monthly_contribution:
            cash += monthly_contribution
            total_contributed += monthly_contribution

        # 1. rank universe as of this month-end - FULL ranking, not just
        # top N, since evaluate_exit's rank-decay check needs a held
        # position's actual current rank even if it fell out of the top 20
        full_ranked = _point_in_time_rank(history, universe, as_of)

        # 2. regime check AS OF this month-end (point-in-time, not today's
        # date - see _point_in_time_regime's docstring for why this matters)
        regime = _point_in_time_regime(history, universe, as_of, equity=cash)

        # 3. manage existing positions through the REAL exit_engine logic -
        # stop, rank decay, 100DMA break, time stop, partial booking. This
        # replaces a much cruder "only checked at month-end stop-hit"
        # approximation that under-modeled how fast the live bot actually
        # cuts decaying positions.
        for sym in list(open_positions):
            h = history.get(sym)
            if h is None or as_of not in h.index:
                continue
            pos = open_positions[sym]
            hist_slice = h.loc[:as_of]
            decision, reason = evaluate_exit(sym, pos, hist_slice, full_ranked, regime, as_of=as_of)
            price = hist_slice["close"].iloc[-1]

            if decision == "FULL_EXIT":
                cash += pos["qty"] * price
                trade_log.append({"date": as_of, "symbol": sym, "action": "SELL",
                                   "qty": pos["qty"], "price": price, "reason": reason})
                del open_positions[sym]
            elif decision == "PARTIAL_EXIT":
                partial_qty = int(pos["qty"] * config.PARTIAL_BOOK_PCT)
                if partial_qty > 0:
                    cash += partial_qty * price
                    pos["qty"] -= partial_qty
                    trade_log.append({"date": as_of, "symbol": sym, "action": "SELL",
                                       "qty": partial_qty, "price": price, "reason": reason})
                pos["partial_booked"] = True

        # 4. new entries - top N of the full ranking, with the SAME
        # conviction scoring the live bot uses (z-scored against this
        # month's other selected leaders, not reimplemented separately)
        entry_mult = regime["entry_size_mult"]
        ranked = add_conviction(full_ranked.head(config.TOP_N_RANK).copy()) if not full_ranked.empty else full_ranked

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

                conviction_mult = row.get("conviction_mult", 1.0)
                combined_mult = conviction_mult * entry_mult  # same combination main.py uses

                if fixed_buy_amount is not None:
                    qty = int(fixed_buy_amount / entry)
                else:
                    qty = size_position(entry, stop, equity_now, fetcher, sym, conviction_mult=combined_mult)

                cost = qty * entry
                if qty > 0 and cost <= cash:
                    cash -= cost
                    open_positions[sym] = {
                        "entry_price": entry, "stop_price": stop, "qty": qty,
                        "entry_date": as_of.strftime("%Y-%m-%d"), "partial_booked": False,
                    }
                    trade_log.append({"date": as_of, "symbol": sym, "action": "BUY",
                                       "qty": qty, "price": entry, "reason": f"tier={regime['tier']}"})

        unrealized = sum(
            open_positions[s]["qty"] * history[s].loc[:as_of, "close"].iloc[-1]
            for s in open_positions
        )

        # Benchmark gets the SAME monthly_contribution that was added to
        # cash above, deployed in full into the index at this month-end's
        # close - simple, deterministic, no cash drag, so any gap between
        # this and the strategy's result is attributable to the strategy's
        # stock selection/timing, not to contribution timing differences.
        bench_value = None
        if bench_hist is not None and as_of in bench_hist.index and monthly_contribution:
            bench_price = bench_hist.loc[as_of, "close"]
            bench_units += monthly_contribution / bench_price
            bench_value = bench_units * bench_price

        equity_curve.append({
            "date": as_of, "equity": cash + unrealized, "cash": cash,
            "positions": len(open_positions), "regime_tier": regime["tier"],
            "total_contributed": total_contributed,
            "benchmark_equity": bench_value,
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
    print(
        "NOTE: this drawdown is computed on the raw equity curve, which gets "
        "topped up every month regardless of performance - fresh contributions "
        "can mask real underlying losses, making this number look tamer than "
        "the strategy's actual performance. The benchmark comparison below is "
        "the more honest read."
    )
    print(f"Months with SEVERE regime tier: {(equity_df['regime_tier'] == 'SEVERE').sum()} / {len(equity_df)}")

    bench_end = equity_df["benchmark_equity"].iloc[-1] if "benchmark_equity" in equity_df else None
    if bench_end is not None and pd.notna(bench_end):
        print(f"\nBenchmark (same monthly contributions into {config.REGIME_INDEX} instead): Rs{bench_end:,.0f}")
        if contributed > 0:
            print(f"Benchmark gain/loss vs. what you put in: {(bench_end / contributed - 1):+.1%}")
        edge = end - bench_end
        verdict = "OUTPERFORMED" if edge > 0 else "UNDERPERFORMED"
        print(f"Strategy {verdict} the benchmark by Rs{abs(edge):,.0f} on the same contributions.")


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
    parser.add_argument("--no-price-cap", action="store_true",
                         help="Ignore config.MAX_PRICE when building the universe. The live bot's "
                              "Rs1000 ceiling exists for affordability on a small account, not because "
                              "expensive stocks are bad signals - without this flag, testing 'nifty50' "
                              "silently shrinks to whichever third of it happens to be cheap.")
    args = parser.parse_args()

    from kite_auth import get_kite
    from data_fetcher import DataFetcher
    from universe import build_universe

    kite = get_kite()
    fetcher = DataFetcher(kite)
    universe = build_universe(fetcher, universe_choice=args.universe,
                               max_price=(None if not args.no_price_cap else float("inf")))
    print(f"Universe ({args.universe}): {len(universe)} symbols after liquidity/price filters"
          + (" (price cap disabled)" if args.no_price_cap else f" (price cap Rs{config.MAX_PRICE})"))

    months = int(args.years * 12)
    equity_df, trades_df = backtest(
        fetcher, universe, months=months, fixed_buy_amount=args.fixed_buy,
        starting_capital=args.starting_capital, monthly_contribution=args.monthly_contribution,
    )
    summarize(equity_df)
    equity_df.to_csv("backtest_equity_curve.csv", index=False)
    trades_df.to_csv("backtest_trades.csv", index=False)
    print("\nSaved backtest_equity_curve.csv and backtest_trades.csv")
