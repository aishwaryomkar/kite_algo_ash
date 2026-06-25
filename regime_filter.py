"""
Market regime filter - 3 tiers, not a binary on/off.

A single "Nifty > 200DMA" rule whipsaws hard right at the cross itself.
The original fix (breadth confirmation) helped, but treating "index and
breadth disagree" identically to "index and breadth both confirm a real
breakdown" was still too blunt - both used to map to the same hard "exit
everything" response. This version separates those:

  BULLISH - index trend ok AND breadth confirms. Normal operation.
  CAUTION - index and breadth DISAGREE. A genuinely mixed signal, not a
    confirmed breakdown. New entries allowed at reduced size; OPEN
    POSITIONS ARE NOT FORCE-EXITED - left to their own stop/rank/100DMA
    exits, just with a tighter rank threshold.
  SEVERE - index AND breadth both confirm a broad breakdown. No new
    entries, and existing positions ARE force-exited. This is the only
    tier with hard liquidation, by design - a long-only momentum book has
    no real edge in a confirmed broad-based breakdown, and in a fast
    crash, speed matters more than waiting for individual stock signals
    to catch up.
"""
import config
from indicators import dma, dma_slope


def index_regime_bullish(fetcher):
    try:
        hist = fetcher.historical(config.REGIME_INDEX, days=400)
        if hist.empty or len(hist) < config.REGIME_DMA_PERIOD + config.REGIME_SLOPE_LOOKBACK:
            print(f"WARNING: {config.REGIME_INDEX} returned insufficient history "
                  f"({len(hist) if not hist.empty else 0} rows) - treating regime as not-bullish "
                  f"rather than crashing. Check the symbol is correct and Kite is returning data for it.")
            return False
        close = hist["close"]
        sma200 = dma(close, config.REGIME_DMA_PERIOD)
        slope = dma_slope(close, config.REGIME_DMA_PERIOD, config.REGIME_SLOPE_LOOKBACK)
        price_above = close.iloc[-1] > sma200.iloc[-1]
        slope_positive = slope.iloc[-1] > 0
        return bool(price_above and slope_positive)
    except Exception as e:
        print(f"WARNING: index_regime_bullish failed ({e}) - treating regime as not-bullish "
              f"rather than crashing the whole run. This needs investigating, not ignoring.")
        return False


def breadth_above_200dma_pct(fetcher, universe):
    """Continuous % of the universe above its own 200DMA - not just a bool,
    so the tier logic below can distinguish 'breadth weak' from 'breadth
    collapsed'."""
    if not config.BREADTH_CONFIRM:
        return 1.0
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
    return (above / total) if total else 0.0


def classify_tier(idx_ok, breadth_pct, equity=None):
    """
    Pure classification logic - no fetcher, no I/O. Both the live path
    (regime_state, using today's data) and the backtest (using point-in-time
    sliced historical data) call this SAME function, so the tier thresholds
    can't drift out of sync between live and backtest the way duplicated
    logic eventually does.

    Regime NEVER force-sells an existing position, at any tier - that
    decision moved entirely to exit_engine.py's own stop/rank/trend/time
    signals. Regime's only lever is gating NEW entries (entry_size_mult).
    A real, broad-based breakdown still shows up - just as "stop adding
    risk," not "panic-liquidate everything regardless of how each name
    individually looks."
    """
    if not config.REGIME_FILTER_ENABLED:
        return {
            "tier": "BULLISH", "bullish": True, "index_ok": True, "breadth_pct": 1.0,
            "graduated_mode": False, "entry_size_mult": 1.0,
            "rank_exit_threshold": config.RANK_EXIT_THRESHOLD,
        }

    graduated = equity is not None and equity < config.REGIME_SOFTEN_BELOW_EQUITY

    if graduated and config.REGIME_FULLY_BYPASS_BELOW_EQUITY:
        tier = "BULLISH"
    elif idx_ok and (breadth_pct >= config.BREADTH_MIN_PCT_ABOVE_200DMA or graduated):
        tier = "BULLISH"
    elif idx_ok or breadth_pct >= config.BREADTH_SEVERE_PCT:
        tier = "CAUTION"
    else:
        tier = "SEVERE"

    return {
        "tier": tier,
        "bullish": tier == "BULLISH",
        "index_ok": idx_ok,
        "breadth_pct": round(breadth_pct, 3),
        "graduated_mode": graduated,
        "entry_size_mult": {"BULLISH": 1.0, "CAUTION": config.CAUTION_ENTRY_SIZE_MULT, "SEVERE": 0.0}[tier],
        "rank_exit_threshold": (
            config.RANK_EXIT_THRESHOLD_CAUTION if tier in ("CAUTION", "SEVERE") else config.RANK_EXIT_THRESHOLD
        ),
    }


def regime_state(fetcher, universe, equity=None):
    idx_ok = index_regime_bullish(fetcher)
    breadth_pct = breadth_above_200dma_pct(fetcher, universe)
    return classify_tier(idx_ok, breadth_pct, equity)
