"""
Market regime filter.

ENHANCEMENT over the plain "Nifty > 200DMA + slope positive" rule: that
single condition whipsaws hard right around the cross itself - the index
can ping-pong across its 200DMA for weeks in a choppy transition. Adding a
breadth requirement (a minimum % of the *universe*, not just the index,
also above its own 200DMA) filters out a meaningful chunk of those false
starts, at the cost of being a little late on regime changes. Set
BREADTH_CONFIRM = False in config.py to go back to the simple version.
"""
import config
from indicators import dma, dma_slope


def index_regime_bullish(fetcher):
    hist = fetcher.historical(config.REGIME_INDEX, days=400)
    close = hist["close"]
    sma200 = dma(close, config.REGIME_DMA_PERIOD)
    slope = dma_slope(close, config.REGIME_DMA_PERIOD, config.REGIME_SLOPE_LOOKBACK)
    price_above = close.iloc[-1] > sma200.iloc[-1]
    slope_positive = slope.iloc[-1] > 0
    return bool(price_above and slope_positive)


def breadth_bullish(fetcher, universe):
    if not config.BREADTH_CONFIRM:
        return True
    above, total = 0, 0
    for sym in universe:
        try:
            hist = fetcher.historical(sym, days=250)
            if hist.empty or len(hist) < config.REGIME_DMA_PERIOD:
                continue
            sma200 = dma(hist["close"], config.REGIME_DMA_PERIOD)
            total += 1
            if hist["close"].iloc[-1] > sma200.iloc[-1]:
                above += 1
        except Exception:
            continue
    if total == 0:
        return False
    return (above / total) >= config.BREADTH_MIN_PCT_ABOVE_200DMA


def regime_state(fetcher, universe, equity=None):
    idx_ok = index_regime_bullish(fetcher)

    graduated = equity is not None and equity < config.REGIME_SOFTEN_BELOW_EQUITY

    if graduated and config.REGIME_FULLY_BYPASS_BELOW_EQUITY:
        # Full bypass - intentionally NOT the default. idx_ok is still
        # computed and reported above for visibility even though it
        # doesn't gate anything in this mode.
        bullish = True
        breadth_ok = None
    elif graduated:
        # Softened: breadth confirmation dropped, but the core trend check
        # still has to pass.
        breadth_ok = None
        bullish = idx_ok
    else:
        breadth_ok = breadth_bullish(fetcher, universe)
        bullish = idx_ok and breadth_ok

    return {
        "bullish": bullish,
        "index_ok": idx_ok,
        "breadth_ok": breadth_ok,
        "cash_target_pct": 0.0 if bullish else 0.90,
        "graduated_mode": graduated,
    }
