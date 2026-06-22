"""
Monthly momentum ranking: 50/30/20 weighting on 12-month/6-month/3-month
returns, exactly as specified.
"""
import pandas as pd
import config
from indicators import returns


def rank_universe(fetcher, universe):
    rows = []
    for sym in universe:
        try:
            hist = fetcher.historical(sym, days=400)
            if hist.empty or len(hist) < 260:
                continue
            close = hist["close"]
            r12 = returns(close, 252).iloc[-1]
            r6 = returns(close, 126).iloc[-1]
            r3 = returns(close, 63).iloc[-1]
            if pd.isna(r12) or pd.isna(r6) or pd.isna(r3):
                continue
            score = (
                config.MOM_WEIGHTS["12m"] * r12
                + config.MOM_WEIGHTS["6m"] * r6
                + config.MOM_WEIGHTS["3m"] * r3
            )
            rows.append({"symbol": sym, "r12": r12, "r6": r6, "r3": r3, "score": score})
        except Exception as e:
            print(f"Skipping {sym} in ranking: {e}")
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def top_n(df, n=None):
    n = n or config.TOP_N_RANK
    selected = df.head(n).copy()
    return add_conviction(selected)


def add_conviction(df):
    """
    Z-scores each selected leader's momentum score against the OTHER
    selected leaders this month - not against the full universe, and never
    against the account's own equity curve. This answers "is this name's
    signal unusually dominant even among this month's already-strong
    field," which is the Dionysian read: differentiate within the winners
    rather than treating all 20 as equally convicted.

    Output is a bounded multiplier (config.CONVICTION_MIN_MULT to
    CONVICTION_MAX_MULT) meant to scale ONLY the risk-derived component of
    sizing in risk_engine.size_position - it must never be used to bypass
    the separate, fixed capital/liquidity caps or the kill switch.
    """
    if not config.CONVICTION_SCALING_ENABLED or df.empty or len(df) < 2:
        df["conviction_mult"] = 1.0
        return df
    mean, std = df["score"].mean(), df["score"].std()
    if not std or pd.isna(std):
        df["conviction_mult"] = 1.0
        return df
    z = (df["score"] - mean) / std
    raw_mult = 1 + 0.5 * z  # each 1 std-dev above peer mean -> +50% risk budget
    df["conviction_mult"] = raw_mult.clip(config.CONVICTION_MIN_MULT, config.CONVICTION_MAX_MULT)
    return df
