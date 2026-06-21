"""
Order engine. This is the ONLY module allowed to call kite.place_order.
Signal engine and risk engine never touch the broker API directly - that
separation is what makes the kill switch actually enforceable: it can
block this module from being called at all, rather than relying on every
upstream piece of logic to remember to check it.

Orders are LIMIT, not MARKET - on a 10-name momentum book, market orders
into anything below top-50 liquidity are where a chunk of "backtest looked
great, live account didn't" comes from.
"""
import config


def _limit_price(ltp, side):
    buffer = ltp * config.LIMIT_BUFFER_PCT
    return round(ltp + buffer, 1) if side == "BUY" else round(ltp - buffer, 1)


def place_buy(kite, symbol, qty, ltp):
    if qty <= 0:
        return None
    price = _limit_price(ltp, "BUY")
    return kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=config.EXCHANGE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_BUY,
        quantity=qty,
        product=config.PRODUCT,
        order_type=config.ORDER_TYPE,
        price=price,
    )


def place_sell(kite, symbol, qty, ltp):
    if qty <= 0:
        return None
    price = _limit_price(ltp, "SELL")
    return kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=config.EXCHANGE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_SELL,
        quantity=qty,
        product=config.PRODUCT,
        order_type=config.ORDER_TYPE,
        price=price,
    )


def place_stop_loss(kite, symbol, qty, trigger_price):
    """SL-M resting order, placed right after a position goes live."""
    if qty <= 0:
        return None
    return kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=config.EXCHANGE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_SELL,
        quantity=qty,
        product=config.PRODUCT,
        order_type=kite.ORDER_TYPE_SLM,
        trigger_price=round(trigger_price, 1),
    )
