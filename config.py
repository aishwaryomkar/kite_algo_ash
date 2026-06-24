"""
Single source of truth for every tunable parameter in the system.
Change behaviour here, not by editing logic in the other modules.
"""
import os

# ---- Kite Connect credentials (set as environment variables, never hardcode) ----
KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN_FILE = "access_token.txt"

# ---- Automated login (optional - only needed for unattended/scheduled runs) ----
# If all three are set, kite_auth.get_kite() uses TOTP-based automated login
# instead of the interactive paste-a-token flow. SECURITY NOTE: this is your
# actual account password and 2FA seed, not just API-scoped credentials - a
# meaningfully bigger blast radius than the API key/secret alone if these
# secrets were ever exposed. Only set these in a private repo's GitHub
# Secrets (or equivalent), never committed to the repo itself.
KITE_USER_ID = os.environ.get("KITE_USER_ID", "")
KITE_PASSWORD = os.environ.get("KITE_PASSWORD", "")
KITE_TOTP_SECRET = os.environ.get("KITE_TOTP_SECRET", "")

# ---- Universe filters ----
MIN_AVG_TURNOVER = 5_00_00_000        # Rs 5 crore, 20-day average
MIN_PRICE = 100
MAX_PRICE = 1000                      # hard ceiling - only trade names below this
TURNOVER_LOOKBACK_DAYS = 20

# Symbols this algo must NEVER buy or sell - your existing discretionary
# holdings, ETFs, SGBs, etc. Keeps the two books completely separate.
# Populate/maintain via excluded_holdings.csv (one symbol per line).
EXCLUDED_HOLDINGS_CSV = "excluded_holdings.csv"

# ---- Market regime filter ----
REGIME_INDEX = "NIFTYBEES"            # use a tradable proxy with full history via Kite;
                                       # swap for "NIFTY 50" index token if you prefer the raw index
REGIME_DMA_PERIOD = 200
REGIME_SLOPE_LOOKBACK = 10            # days over which 200DMA slope is measured
BREADTH_CONFIRM = True                # ENHANCEMENT: secondary breadth filter, see regime_filter.py
BREADTH_MIN_PCT_ABOVE_200DMA = 0.40   # >=40% of universe above own 200DMA -> BULLISH tier
BREADTH_SEVERE_PCT = 0.20             # <20% AND index also broken -> SEVERE tier (the only tier that forces an exit)

# ---- Graduated regime enforcement (3 tiers, not 2 binary states) ----
# BULLISH: index trend ok AND breadth confirms -> normal operation.
# CAUTION: index and breadth DISAGREE (one ok, one not) - genuinely mixed
#   signal, not a confirmed breakdown. New entries allowed at reduced size;
#   existing positions are NOT force-exited - left to stop/rank/100DMA
#   exits, just with a tighter rank threshold so decaying names roll off
#   faster without a blanket sale.
# SEVERE: index AND breadth both agree things are bad - the one case this
#   filter was actually built for. No new entries, and existing positions
#   ARE force-exited. This is deliberately the only tier with hard
#   liquidation - a real, broad-based breakdown is exactly the situation
#   where a long-only momentum book has no edge and speed matters more
#   than nuance.
CAUTION_ENTRY_SIZE_MULT = 0.5
RANK_EXIT_THRESHOLD_CAUTION = 25      # tighter than RANK_EXIT_THRESHOLD (50) while in CAUTION

# Below this trading_equity, drop the breadth confirmation requirement for
# the BULLISH/CAUTION boundary (still requires the Nifty index trend check,
# unless fully bypassed below) - the absolute rupee cost of a soft-market
# entry is small while capital is small. Above this threshold, the full
# 3-tier logic is enforced exactly as designed - no exceptions.
REGIME_SOFTEN_BELOW_EQUITY = 50_000
# Set True to drop the regime filter ENTIRELY below the threshold above,
# rather than softening it. NOT the default - this also removes the Nifty
# trend check, i.e. the single rule most responsible for avoiding the
# worst drawdowns, regardless of how small the capital at stake is right
# now. Softening (the default) keeps that check; this does not.
REGIME_FULLY_BYPASS_BELOW_EQUITY = False

# ---- Monthly ranking ----
MOM_WEIGHTS = {"12m": 0.50, "6m": 0.30, "3m": 0.20}
TOP_N_RANK = 20
RANK_EXIT_THRESHOLD = 50              # exit if rank falls below this

# ---- Entry filter ----
RSI_PERIOD = 14
RSI_LOW, RSI_HIGH = 45, 60
PULLBACK_LOW, PULLBACK_HIGH = 0.03, 0.10   # 3%-10% off the 20-day high

# ---- Position sizing ----
# NOTE: tuned for small/growing capital (e.g. ~Rs 8k/month additions).
# Fewer, more meaningfully-sized positions instead of spreading thin
# capital across 10 slots where risk-based qty rounds to 0-1 shares.
EQUITY = 10_00_000
RISK_PER_TRADE_PCT = 0.018            # 1.8% of equity per trade (was 0.5%)
ATR_PERIOD = 14
ATR_STOP_MULT = 2.5
MAX_POSITIONS = 4                     # was 10
MAX_PER_SECTOR = 2
MAX_CAPITAL_PCT_PER_STOCK = 0.25      # was 0.10 - with only 4 slots, 25% each allows full deployment
MAX_ADV_PARTICIPATION = 0.05          # ENHANCEMENT: never size > 5% of 20d avg daily volume (slippage control)

# ---- Trade-management enhancements ----
REENTRY_COOLDOWN_DAYS = 15            # don't re-buy a stopped-out name for 15 sessions (anti-whipsaw)
TIME_STOP_DAYS = 20                   # exit if a position is still <1R either way after 20 sessions (dead capital)
PARTIAL_BOOK_R_MULT = 1.5             # book partial profit at 1.5R
PARTIAL_BOOK_PCT = 0.30               # ...30% of the position

# ---- Kill switch (drawdown from equity peak) ----
# Ordered from mildest to most severe; main.py applies the most severe
# triggered level. The 5% "soft pause" is an addition to the original
# four-step ladder so de-risking is gradual rather than a step function.
KILL_SWITCH_LEVELS = [
    (0.05, "REDUCE_25"),
    (0.08, "REDUCE_50"),
    (0.12, "NO_NEW_ENTRIES"),
    (0.15, "EXIT_WEAKEST_HALF"),
    (0.20, "EXIT_ALL"),
]

# ---- Execution ----
ORDER_TYPE = "LIMIT"                  # never MARKET on this book - this is the slippage control
LIMIT_BUFFER_PCT = 0.002              # 0.2% through last traded price
EXCHANGE = "NSE"
PRODUCT = "CNC"                       # delivery only - never MIS/intraday

# ---- Sector classification ----
SECTOR_MAP_CSV = "sector_map.csv"     # symbol,sector - populate from NSE classification

# ---- Liquidity buffer (on-demand capital top-up) ----
# Treats a CAPPED percentage of a parked liquid-fund ETF as a same-day cash
# top-up source for trades, instead of letting it sit fully untouched.
# This is sell-only and capped - it is never bought into a directional
# position, and is separate from EXCLUDED_HOLDINGS_CSV (which still blocks
# it from ever being a screener/entry candidate; this is purely a funding
# mechanism, not a strategy signal).
#
# VERIFY the exact tradingsymbol via kite.holdings() before relying on this
# - Console/app display names (e.g. "LIQUIDCASE-F") don't always match the
# exact API tradingsymbol.
LIQUIDITY_BUFFER_SYMBOL = "LIQUIDCASE"
LIQUIDITY_BUFFER_MAX_UTILIZATION_PCT = 0.50   # never redeem more than 50% of current holding value
# Zerodha credits only ~80% of same-day sale proceeds as immediately usable
# for new buys; the remaining ~20% ("delivery margin") is held back until
# the next trading day. Sizing math below uses this so it doesn't assume
# cash that isn't actually available yet.
SAME_DAY_SELL_PROCEEDS_USABLE_PCT = 0.80

# ---- Conviction-scaled sizing (Dionysian sizing inside an Apollonian cage) ----
# Lets risk-per-trade scale UP for standout monthly momentum scores and DOWN
# for marginal ones, instead of every name in the top 20 getting identical
# risk regardless of how dominant its signal is.
#
# Hard rule this must never violate: the multiplier only scales the
# RISK-DERIVED component of sizing (risk_engine.size_position's risk_amount).
# It is applied BEFORE, and is always subordinate to, the unchanged
# MAX_CAPITAL_PCT_PER_STOCK cap, MAX_ADV_PARTICIPATION liquidity cap, and the
# kill switch - none of which scale with conviction, ever. Conviction can
# only move within the cage, never widen it.
#
# Also deliberately NOT derived from the account's own equity curve or win
# streak - it's a z-score against THIS month's own selected leaders'
# distribution, so it reflects how strong this month's signal dispersion is,
# not whether the account has been on a hot streak (sizing up after winning
# is leverage dressed as conviction - a known way books blow up).
CONVICTION_SCALING_ENABLED = True
CONVICTION_MIN_MULT = 0.5
CONVICTION_MAX_MULT = 2.0

# What fraction of the LIQUIDCASE buffer's CURRENT VALUE counts toward the
# equity base used for position SIZING (risk_amount, capital-per-stock cap)
# only. Deliberately separate from LIQUIDITY_BUFFER_MAX_UTILIZATION_PCT
# (which caps actual redemption) and kept LOWER than it (30% vs 50%) - you
# size as if some of the cushion is capital, but the ceiling on what can
# actually ever be redeemed stays more conservative than what sizing assumes.
#
# Critically, this does NOT touch the kill switch / drawdown tracking, which
# stays anchored to real trading capital only (cash + this algo's own
# positions). Diluting the drawdown denominator with a stable side-pool
# would make real trading losses look smaller as a % of "equity" - that's
# loosening the part of the system that isn't supposed to flex.
LIQUIDCASE_SIZING_INCLUSION_PCT = 0.30
