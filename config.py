"""
Single source of truth for every tunable parameter in the system.
Change behaviour here, not by editing logic in the other modules.
"""
import os

# ---- Kite Connect credentials (set as environment variables, never hardcode) ----
KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")
KITE_ACCESS_TOKEN_FILE = "access_token.txt"

# ---- Universe filters ----
MIN_AVG_TURNOVER = 5_00_00_000        # Rs 5 crore, 20-day average
MIN_PRICE = 100
TURNOVER_LOOKBACK_DAYS = 20

# ---- Market regime filter ----
REGIME_INDEX = "NIFTYBEES"            # use a tradable proxy with full history via Kite;
                                       # swap for "NIFTY 50" index token if you prefer the raw index
REGIME_DMA_PERIOD = 200
REGIME_SLOPE_LOOKBACK = 10            # days over which 200DMA slope is measured
BREADTH_CONFIRM = True                # ENHANCEMENT: secondary breadth filter, see regime_filter.py
BREADTH_MIN_PCT_ABOVE_200DMA = 0.40   # >=40% of universe above own 200DMA to confirm "bullish"

# ---- Monthly ranking ----
MOM_WEIGHTS = {"12m": 0.50, "6m": 0.30, "3m": 0.20}
TOP_N_RANK = 20
RANK_EXIT_THRESHOLD = 50              # exit if rank falls below this

# ---- Entry filter ----
RSI_PERIOD = 14
RSI_LOW, RSI_HIGH = 45, 60
PULLBACK_LOW, PULLBACK_HIGH = 0.03, 0.10   # 3%-10% off the 20-day high

# ---- Position sizing ----
EQUITY = 10_00_000
RISK_PER_TRADE_PCT = 0.005            # 0.5% of equity per trade
ATR_PERIOD = 14
ATR_STOP_MULT = 2.5
MAX_POSITIONS = 10
MAX_PER_SECTOR = 2
MAX_CAPITAL_PCT_PER_STOCK = 0.10
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
SECTOR_MAP_CSV = "sector_map.csv"     # symbol,sector - populate from NSE classification data
