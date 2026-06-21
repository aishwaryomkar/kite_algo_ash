"""
Entry conditions: trend-aligned, not overbought, bought on a controlled
pullback rather than chased on a breakout spike.
"""
import config
from indicators import dma, rsi, pullback_from_high


def passes_entry_filter(hist):
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
