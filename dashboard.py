"""
Monitoring dashboard. Run with:

    streamlit run dashboard.py

Shows two things, deliberately kept separate:
  - LIVE STATE: read directly from positions.json / risk_state.json - this
    is "what is true right now", independent of telemetry having run.
  - HISTORY: read from telemetry/equity_history.csv and trades_history.csv
    - this is "how did we get here", built up one row per daily run.
"""
import json
import os
import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Trading Bot Monitor", layout="wide")
st.title("Trading Bot Monitor")


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_csv(path):
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


# ---- Live state ----
st.header("Live State")
positions = load_json("positions.json")
risk_state = load_json("risk_state.json")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Open positions", len(positions) if positions else 0)
with col2:
    peak = risk_state.get("equity_peak") if risk_state else None
    st.metric("Recorded equity peak", f"Rs{peak:,.0f}" if peak else "no data yet")
with col3:
    cooldowns = risk_state.get("cooldowns", {}) if risk_state else {}
    active_cooldowns = sum(1 for v in cooldowns.values() if v >= pd.Timestamp.today().strftime("%Y-%m-%d"))
    st.metric("Symbols in cooldown", active_cooldowns)

if positions:
    st.subheader("Current positions")
    pos_rows = [{"symbol": sym, **details} for sym, details in positions.items()]
    st.dataframe(pd.DataFrame(pos_rows), use_container_width=True)
else:
    st.info("No open positions right now.")

# ---- History ----
st.header("History")
equity_df = load_csv("telemetry/equity_history.csv")
trades_df = load_csv("telemetry/trades_history.csv")

if equity_df is not None and not equity_df.empty:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Latest trading equity", f"Rs{equity_df['trading_equity'].iloc[-1]:,.0f}")
    with col2:
        st.metric("Latest drawdown", f"{equity_df['drawdown'].iloc[-1]:.1%}")
    with col3:
        st.metric("Latest regime tier", equity_df["regime_tier"].iloc[-1])

    fig = px.line(equity_df, x="date", y=["trading_equity", "sizing_equity"],
                   title="Equity over time (trading vs. sizing base)")
    st.plotly_chart(fig, use_container_width=True)

    fig2 = px.bar(equity_df, x="date", y="drawdown", title="Drawdown over time")
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Regime tier history")
    st.dataframe(equity_df[["date", "regime_tier", "breadth_pct", "kill_switch"]].tail(30),
                 use_container_width=True)
else:
    st.info("No equity history yet - this fills in after main.py has run at least once with monitoring.py wired in.")

if trades_df is not None and not trades_df.empty:
    st.subheader("Trade history")
    st.dataframe(trades_df.sort_values("date", ascending=False), use_container_width=True)

    buys = trades_df[trades_df["action"] == "BUY"]
    sells = trades_df[trades_df["action"] == "SELL"]
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total buys", len(buys))
    with col2:
        st.metric("Total sells", len(sells))
else:
    st.info("No trades logged yet.")
