"""
Entry conditions. Two genuinely different, mutually exclusive styles -
config.ENTRY_STYLE picks one, since they want opposite things from price
action and merging them into one filter would be incoherent (a stock can't
simultaneously be "3-10% off its high" and "making a new high"):

  "pullback" (default) - trend-aligned, not overbought, bought on a
    controlled dip rather than chased on a spike. Lower turnover, avoids
    buying extension.
  "breakout" - CANSLIM-style: buy strength at/near new highs, confirmed by
    a volume surge (the "N" and "S" of CANSLIM - new highs, supply/demand).
    Higher turnover, accepts chasing in exchange for catching moves earlier.
    NOTE: this only covers what Kite's price/volume data can support. Real
    CANSLIM also leans heavily on fundamentals - quarterly/annual EPS
    growth, institutional sponsorship trends - which Kite Connect doesn't
    provide at all (it's a trading API, not a fundamentals API). Those
    letters (C, A, I) aren't implemented here; this is the technical subset
    only, not the full methodology.
"""
import config
from indicators import dma, rsi, pullback_from_high


def passes_entry_filter(hist):
    if config.ENTRY_STYLE == "breakout":
        return _passes_breakout_filter(hist)
    return _passes_pullback_filter(hist)


def _passes_pullback_filter(hist):
    if hist.empty or len(hist) < 210:
        return False, {}
    close = hist["close"]
    sma200 = dma(close, 200).iloc[-1]
    sma50 = dma(close, 50).iloc[-1]
    rsi14 = rsi(close, config.RSI_PERIOD).iloc[-1]
    pullback = pullback_from_high(close, 20).iloc[-1]
    last = close.iloc[-1]

    checks = {
        "above_200dma": last > sma200,
        "above_50dma": last > sma50,
        "rsi_in_range": config.RSI_LOW <= rsi14 <= config.RSI_HIGH,
        "pullback_in_range": config.PULLBACK_LOW <= pullback <= config.PULLBACK_HIGH,
    }
    return all(checks.values()), {**checks, "rsi": rsi14, "pullback": pullback, "price": last}


def _passes_breakout_filter(hist):
    if hist.empty or len(hist) < config.BREAKOUT_LOOKBACK_DAYS:
        return False, {}
    close = hist["close"]
    volume = hist["volume"]
    last = close.iloc[-1]

    lookback_high = close.iloc[-config.BREAKOUT_LOOKBACK_DAYS:-1].max() if len(close) > 1 else last
    avg_volume = volume.iloc[-21:-1].mean()  # trailing 20 sessions, excluding today
    today_volume = volume.iloc[-1]
    sma50 = dma(close, 50).iloc[-1]

    checks = {
        "at_or_near_new_high": last >= lookback_high * (1 - config.BREAKOUT_PROXIMITY_PCT),
        "above_50dma": last > sma50,
        "volume_surge": (today_volume >= avg_volume * config.BREAKOUT_VOLUME_MULT) if avg_volume > 0 else False,
    }
    details = {
        **checks, "price": last, "lookback_high": lookback_high,
        "volume_ratio": (today_volume / avg_volume) if avg_volume > 0 else 0,
    }
    return all(checks.values()), details
