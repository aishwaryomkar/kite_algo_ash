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
    return df.head(n)
