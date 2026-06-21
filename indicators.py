"""
Technical indicators in plain pandas/numpy - no TA-Lib install headaches.
"""
import pandas as pd
import numpy as np


def dma(series, period):
    return series.rolling(period).mean()


def dma_slope(series, period, lookback):
    sma = dma(series, period)
    return (sma - sma.shift(lookback)) / lookback


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def pullback_from_high(series, window=20):
    rolling_high = series.rolling(window).max()
    return (rolling_high - series) / rolling_high


def returns(series, period):
    return series.pct_change(period)
