# Momentum + Trend + Kill Switch — Kite Connect implementation

A monthly-rebalanced, trend-filtered momentum system for NSE cash equity.
No intraday, no F&O — every order is `CNC` (delivery), placed as `LIMIT`,
never `MARKET`.

## What's in here

| File | Role |
|---|---|
| `config.py` | every threshold, all in one place |
| `kite_auth.py` | daily login flow (access tokens expire each morning) |
| `data_fetcher.py` | rate-limited wrapper around Kite historical/quote calls |
| `universe.py` | Nifty 500 list + turnover/price liquidity filter |
| `indicators.py` | DMA, RSI, ATR, pullback — plain pandas, no TA-Lib |
| `regime_filter.py` | Nifty trend filter + breadth confirmation |
| `screener.py` | monthly 12m/6m/3m momentum ranking |
| `entry_filter.py` | trend + RSI + pullback entry gate |
| `risk_engine.py` | position sizing, ATR stops, kill switch state machine |
| `portfolio.py` | persisted open positions, sector caps |
| `order_engine.py` | the *only* module that calls `kite.place_order` |
| `exit_engine.py` | daily exit checks for every open position |
| `main.py` | daily orchestration — run this via cron |
| `backtest.py` | rough directional sanity check, see caveats in its docstring |
| `sector_map.csv` | starter template — extend to your full universe |

## Setup

```bash
pip install -r requirements.txt
export KITE_API_KEY="your_api_key"
export KITE_API_SECRET="your_api_secret"
python kite_auth.py          # one-time interactive login for today's session
```

Kite access tokens expire daily (~6am IST), so `kite_auth.py` needs to run
once each morning before market open — `main.py` calls `get_kite()`
automatically and will fall back to an interactive login if the saved
token is dead, but that obviously can't run unattended inside a cron job.
For a fully hands-off setup you'd need to script the TOTP-based login
(Kite supports this with `pyotp`) — not included here since it means
storing your 2FA secret on disk, which is its own risk decision.

Fill out `sector_map.csv` properly before going live — the 27-row starter
only covers large caps. Pull the full classification from NSE's sector
index pages or your existing screener.

## Running it

```bash
python main.py
```

Schedule daily, after the opening auction settles:

```
20 9 * * 1-5 cd /path/to/kite_algo && /usr/bin/python3 main.py >> run.log 2>&1
```

Every run: refreshes the regime read, manages exits + kill switch on open
positions. Only on the 1st–3rd of the month does it re-rank and look for
new entries.

## Before running with real capital

1. Run `backtest.py` first — it's a rough sanity check (see its docstring
   for exactly what it does and doesn't model), not a validated backtest.
2. Paper-trade for at least one full regime cycle (a bull leg *and* a
   correction) before committing capital — the kill switch and exit logic
   are the parts most worth watching live before you trust them.
3. Reconcile `positions.json` against `kite.positions()`/`kite.holdings()`
   periodically — it's local bookkeeping, not the broker's source of truth.

## Enhancements over the original spec

- **Breadth-confirmed regime filter** — reduces whipsaw right at the
  Nifty/200DMA cross (`regime_filter.py`).
- **Liquidity-capped sizing** — risk-based size is also capped at 5% of
  20-day average volume, so a name's risk math doesn't size you into a
  position you can't exit cleanly (`risk_engine.size_position`).
- **Re-entry cooldown** — 15 sessions after a stop-out before the same
  name can be re-bought, to cut down on chop-driven overtrading.
- **Time stop** — exits a position that's still flat (<1R either way)
  after 20 sessions, freeing the slot for an actual mover.
- **Partial profit booking** — locks in 30% of a position at 1.5R rather
  than giving the whole move back waiting for the trend exit to trigger.
- **Graduated kill switch** — added a 5% "reduce size 25%" soft-pause
  step before the original 8% level, so de-risking is a ramp, not a cliff.

