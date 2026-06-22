"""
Liquidity buffer: lets the system draw on a CAPPED percentage of a parked
liquid-fund ETF holding (e.g. LIQUIDCASE) as an on-demand top-up when cash
on hand falls short of what a sized trade needs.

Design constraints, deliberately strict:
  - SELL-ONLY. This module never buys the buffer symbol, and never adds it
    to positions.json - it is not a strategy position, it is parked cash
    being put to work.
  - CAPPED. Never redeems more than LIQUIDITY_BUFFER_MAX_UTILIZATION_PCT of
    the current holding value, and the cap is enforced per run (not
    per-trade), so it can't get drained across several trades in one day.
  - Respects T+1 settlement mechanics: only ~80% of a same-day sale's
    proceeds are usable for new buys same day (the rest is held back by
    exchange delivery-margin rules until the next session) - this module
    accounts for that rather than assuming the full sale value is spendable
    immediately.
"""
import config


def get_buffer_holding(kite):
    """Returns (qty, last_price, value) for the buffer symbol, or zeros if not held."""
    holdings = kite.holdings()
    for h in holdings:
        if h["tradingsymbol"] == config.LIQUIDITY_BUFFER_SYMBOL:
            qty = h["quantity"]
            price = h.get("last_price") or h.get("average_price", 0)
            return qty, price, qty * price
    return 0, 0, 0


def max_redeemable_value(kite):
    _, _, value = get_buffer_holding(kite)
    return value * config.LIQUIDITY_BUFFER_MAX_UTILIZATION_PCT


def redeem_for_shortfall(kite, place_sell_fn, shortfall_amount, already_redeemed_today):
    """
    Sells just enough buffer units to cover `shortfall_amount`, capped by
    the per-run redemption ceiling minus whatever's already been redeemed
    this run. Returns (cash_immediately_usable, sale_value) - use the first
    number for sizing, since only ~80% of the sale is usable same-day.
    """
    qty_held, price, value = get_buffer_holding(kite)
    if qty_held <= 0 or price <= 0:
        return 0, 0

    remaining_cap = max_redeemable_value(kite) - already_redeemed_today
    if remaining_cap <= 0:
        return 0, 0

    sale_target = min(shortfall_amount, remaining_cap, value)
    qty_to_sell = int(sale_target / price)
    if qty_to_sell <= 0:
        return 0, 0

    place_sell_fn(kite, config.LIQUIDITY_BUFFER_SYMBOL, qty_to_sell, price)
    sale_value = qty_to_sell * price
    usable_now = sale_value * config.SAME_DAY_SELL_PROCEEDS_USABLE_PCT
    print(
        f"LIQUIDITY BUFFER: sold {qty_to_sell} {config.LIQUIDITY_BUFFER_SYMBOL} "
        f"(~Rs{sale_value:.0f}), ~Rs{usable_now:.0f} usable today, "
        f"remainder settles next session."
    )
    return usable_now, sale_value
