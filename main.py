"""
Daily orchestration. Run once after market open via cron/Task Scheduler,
e.g. 9:20am IST (after the opening auction settles):

    20 9 * * 1-5 cd /path/to/kite_algo && /usr/bin/python3 main.py >> run.log 2>&1

Every trading day this script: refreshes the regime read, manages exits
and the kill switch on existing positions, and - only on the first
trading session of the month - re-ranks the universe and looks for new
entries. On every other day it only manages risk on what's already open;
it does not re-screen.
"""
import datetime as dt

import config
from kite_auth import get_kite
from data_fetcher import DataFetcher
from universe import build_universe, load_excluded_holdings
from regime_filter import regime_state
from screener import rank_universe, top_n
from entry_filter import passes_entry_filter
from risk_engine import (
    kill_switch_action, size_position, atr_stop, apply_kill_switch_to_size,
    is_in_cooldown, start_cooldown, update_equity_peak,
)
from portfolio import (
    load_positions, save_positions, load_sector_map, can_add_position,
    add_position, remove_position, total_equity_estimate,
)
from order_engine import place_buy, place_sell, place_stop_loss
from exit_engine import evaluate_exit
from liquidity_buffer import redeem_for_shortfall, get_buffer_holding


def is_first_trading_day_of_month():
    # Crude check - good enough for a monthly cron job. Swap in an actual
    # NSE trading-calendar lookup if a holiday ever lands on day 1-3.
    return dt.date.today().day <= 3


def run():
    kite = get_kite()
    fetcher = DataFetcher(kite)
    sector_map = load_sector_map()
    positions = load_positions()

    margins = kite.margins("equity")
    # Use available.cash specifically, not "net" - net can include collateral
    # from pledged holdings, which is NOT usable for CNC (delivery) buys.
    # Sizing/equity tracking against "net" would silently overstate what
    # this system can actually deploy.
    cash = margins["available"]["cash"]
    ltp_map = fetcher.ltp(list(positions.keys()))

    # TWO different numbers, used for two different purposes - do not merge
    # them:
    #   trading_equity - real cash + this algo's own positions only. This is
    #     what the kill switch / drawdown tracking AND the regime-softening
    #     threshold below use. Never diluted by the LIQUIDCASE buffer, so a
    #     real trading loss always shows up as a real % drawdown, not
    #     softened by a stable side-pool.
    #   sizing_equity - trading_equity PLUS a capped fraction of the
    #     LIQUIDCASE buffer's value. This wider number is what position
    #     sizing (risk_amount, capital-per-stock cap) is computed against,
    #     so positions can be sized more usably without that cushion ever
    #     affecting whether the kill switch thinks you're in a drawdown.
    trading_equity = total_equity_estimate(positions, ltp_map, cash)
    _, _, liquidcase_value = get_buffer_holding(kite)
    sizing_equity = trading_equity + (liquidcase_value * config.LIQUIDCASE_SIZING_INCLUSION_PCT)

    # No open positions AND no cash AND nothing in the buffer is genuinely
    # zero deployable capital - different from a real drawdown, even though
    # the math would otherwise read 100%. Most likely either the equity
    # segment isn't funded yet, or sale proceeds are still settling.
    if not positions and cash == 0 and liquidcase_value == 0:
        print(
            "Equity reads 0 with no open positions and no buffer balance - "
            "not a drawdown event. Check Console > Funds > Equity > "
            "Available Cash to confirm whether this segment is funded yet, "
            "or whether a prior sale's proceeds are still settling (T+1). "
            "Skipping kill-switch evaluation - nothing to manage with zero "
            "deployable capital."
        )
        return

    universe = build_universe(fetcher)
    # Graduated regime enforcement: while trading_equity is small, the full
    # breadth-confirmed gate means real stretches of zero buys, at a time
    # when the absolute rupee cost of "buying into a soft market" is also
    # small. Below the threshold this drops the breadth requirement (still
    # requires the Nifty trend check, unless fully bypassed below); above
    # it, both checks are enforced exactly as originally designed.
    regime = regime_state(fetcher, universe, equity=trading_equity)
    print(f"Regime: {regime}")

    update_equity_peak(trading_equity)
    action, dd = kill_switch_action(trading_equity)
    print(
        f"Trading equity: {trading_equity:.0f}  Sizing equity: {sizing_equity:.0f}  "
        f"Drawdown: {dd:.2%}  Kill switch: {action}"
    )


    rebalance_day = is_first_trading_day_of_month()
    rank_df = rank_universe(fetcher, universe) if rebalance_day else None

    # ---- 1. Manage existing positions: exits + partial booking ----
    for symbol, pos in list(positions.items()):
        hist = fetcher.historical(symbol, days=300)
        if hist.empty:
            continue
        # if it's not a rebalance day we still need *this* symbol's rank
        # for the rank-decay check, so fetch it narrowly rather than
        # re-ranking the whole universe every day
        rank_for_check = rank_df if rank_df is not None else rank_universe(fetcher, [symbol])
        decision, reason = evaluate_exit(symbol, pos, hist, rank_for_check, regime["bullish"])
        ltp = ltp_map.get(symbol, hist["close"].iloc[-1])

        if decision == "FULL_EXIT":
            place_sell(kite, symbol, pos["qty"], ltp)
            remove_position(symbol)
            start_cooldown(symbol)
            print(f"EXIT {symbol}: {reason}")
        elif decision == "PARTIAL_EXIT":
            partial_qty = int(pos["qty"] * config.PARTIAL_BOOK_PCT)
            if partial_qty > 0:
                place_sell(kite, symbol, partial_qty, ltp)
                pos["qty"] -= partial_qty
            pos["partial_booked"] = True
            positions[symbol] = pos
            print(f"PARTIAL EXIT {symbol}: booked {partial_qty}, {pos['qty']} remaining")

    save_positions(positions)
    positions = load_positions()

    # ---- 2. Kill switch: forced de-risking beyond normal exits ----
    if action == "EXIT_WEAKEST_HALF" and positions:
        open_syms = list(positions.keys())
        current_rank = rank_universe(fetcher, open_syms)
        if not current_rank.empty:
            current_rank = current_rank.sort_values("score")  # weakest first
            half = max(1, len(current_rank) // 2)
            for _, row in current_rank.head(half).iterrows():
                symbol = row["symbol"]
                pos = positions[symbol]
                ltp = ltp_map.get(symbol, pos["entry_price"])
                place_sell(kite, symbol, pos["qty"], ltp)
                remove_position(symbol)
                print(f"KILL SWITCH (EXIT_WEAKEST_HALF): {symbol}")

    if action == "EXIT_ALL":
        for symbol, pos in list(load_positions().items()):
            ltp = ltp_map.get(symbol, pos["entry_price"])
            place_sell(kite, symbol, pos["qty"], ltp)
            remove_position(symbol)
        print("KILL SWITCH (EXIT_ALL): book fully closed, standing aside.")
        return

    # ---- 3. New entries ----
    if not regime["bullish"]:
        print("Regime bearish - holding cash, no new entries today.")
        return
    if action in ("NO_NEW_ENTRIES", "EXIT_WEAKEST_HALF"):
        print(f"Kill switch state '{action}' blocks new entries today.")
        return
    if not rebalance_day:
        return

    positions = load_positions()
    candidates = top_n(rank_df)
    excluded = load_excluded_holdings()  # belt-and-suspenders: re-check even though
                                          # build_universe() already filtered these out
    running_cash = cash           # decremented as buys are placed this run
    liquidcase_redeemed_today = 0  # tracked against the per-run cap in liquidity_buffer.py

    for _, row in candidates.iterrows():
        symbol = row["symbol"]
        if symbol.strip().upper() in excluded:
            continue
        if symbol in positions or is_in_cooldown(symbol):
            continue
        ok, _ = can_add_position(symbol, positions, sector_map)
        if not ok:
            continue

        hist = fetcher.historical(symbol, days=300)
        passed, details = passes_entry_filter(hist)
        if not passed:
            continue

        stop_price, atr_val = atr_stop(hist)
        entry_price = details["price"]
        conviction_mult = row.get("conviction_mult", 1.0)  # bounded 0.5-2.0, see screener.py
        qty = size_position(entry_price, stop_price, sizing_equity, fetcher, symbol, conviction_mult)
        qty = apply_kill_switch_to_size(qty, action)  # Apollo has final say, always - conviction never bypasses this
        if qty <= 0:
            continue

        # Cash check + liquidity-buffer top-up: the sizing above caps by
        # risk/capital%/liquidity, but doesn't know actual cash on hand.
        # If the sized trade costs more than what's available, try topping
        # up from the buffer (capped) before shrinking the order.
        cost = qty * entry_price
        if cost > running_cash:
            shortfall = cost - running_cash
            usable, sale_value = redeem_for_shortfall(kite, place_sell, shortfall, liquidcase_redeemed_today)
            liquidcase_redeemed_today += sale_value  # cap tracks actual units sold, not the smaller same-day-usable amount
            running_cash += usable
            if cost > running_cash:
                qty = int(running_cash / entry_price)
        if qty <= 0:
            continue

        place_buy(kite, symbol, qty, entry_price)
        place_stop_loss(kite, symbol, qty, stop_price)
        add_position(symbol, qty, entry_price, stop_price, atr_val, sector_map.get(symbol, "UNKNOWN"))
        running_cash -= qty * entry_price
        positions = load_positions()
        print(f"ENTRY {symbol}: qty={qty} entry~{entry_price:.1f} stop={stop_price:.1f}")


if __name__ == "__main__":
    run()
