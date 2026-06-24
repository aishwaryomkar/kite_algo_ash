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
    hist = fetcher.historical(config.REGIME_INDEX, days=400)
    close = hist["close"]
    sma200 = dma(close, config.REGIME_DMA_PERIOD)
    slope = dma_slope(close, config.REGIME_DMA_PERIOD, config.REGIME_SLOPE_LOOKBACK)
    price_above = close.iloc[-1] > sma200.iloc[-1]
    slope_positive = slope.iloc[-1] > 0
    return bool(price_above and slope_positive)


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


def regime_state(fetcher, universe, equity=None):
    idx_ok = index_regime_bullish(fetcher)
    breadth_pct = breadth_above_200dma_pct(fetcher, universe)

    graduated = equity is not None and equity < config.REGIME_SOFTEN_BELOW_EQUITY

    if graduated and config.REGIME_FULLY_BYPASS_BELOW_EQUITY:
        tier = "BULLISH"  # idx_ok/breadth_pct still computed above for visibility, just don't gate anything
    elif idx_ok and (breadth_pct >= config.BREADTH_MIN_PCT_ABOVE_200DMA or graduated):
        # At small equity, breadth weakness alone doesn't downgrade the
        # tier - mirrors the prior softened-mode behavior.
        tier = "BULLISH"
    elif idx_ok or breadth_pct >= config.BREADTH_SEVERE_PCT:
        tier = "CAUTION"   # signals disagree, or both mildly weak - not a confirmed breakdown
    else:
        tier = "SEVERE"    # both confirm a broad breakdown

    return {
        "tier": tier,
        "bullish": tier == "BULLISH",  # kept for any code/printouts checking this directly
        "index_ok": idx_ok,
        "breadth_pct": round(breadth_pct, 3),
        "graduated_mode": graduated,
        "entry_size_mult": {"BULLISH": 1.0, "CAUTION": config.CAUTION_ENTRY_SIZE_MULT, "SEVERE": 0.0}[tier],
        "force_exit_all": tier == "SEVERE",
        "rank_exit_threshold": (
            config.RANK_EXIT_THRESHOLD_CAUTION if tier == "CAUTION" else config.RANK_EXIT_THRESHOLD
        ),
    }
