"""
Logging + telemetry for monitoring the live bot.

Telemetry deliberately APPENDS to two persistent CSVs
(telemetry/equity_history.csv, telemetry/trades_history.csv) rather than
writing a fresh timestamped file every run. A fresh-file-per-run design
means each file only ever has ONE row of data - an "equity curve" built
that way is a single point re-plotted daily, not a curve. Appending is
what makes "watch this over time" actually possible.
"""
import logging
import os
import csv
import datetime as dt

LOG_DIR = "logs"
TELEMETRY_DIR = "telemetry"
EQUITY_HISTORY_FILE = os.path.join(TELEMETRY_DIR, "equity_history.csv")
TRADES_HISTORY_FILE = os.path.join(TELEMETRY_DIR, "trades_history.csv")


class TradingLogger:
    def __init__(self, log_dir=LOG_DIR):
        os.makedirs(log_dir, exist_ok=True)
        self.logger = logging.getLogger("trading_system")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()  # avoid duplicate lines if instantiated more than once in a process

        file_handler = logging.FileHandler(
            os.path.join(log_dir, f"trading_{dt.date.today().isoformat()}.log")
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.logger.addHandler(console_handler)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)


class TelemetryCollector:
    def __init__(self):
        os.makedirs(TELEMETRY_DIR, exist_ok=True)

    def log_equity(self, trading_equity, sizing_equity, cash, drawdown, kill_switch,
                    regime_tier, breadth_pct, positions_count, date=None):
        row = {
            "date": date or dt.date.today().isoformat(),
            "trading_equity": trading_equity,
            "sizing_equity": sizing_equity,
            "cash": cash,
            "drawdown": drawdown,
            "kill_switch": kill_switch or "",
            "regime_tier": regime_tier,
            "breadth_pct": breadth_pct,
            "positions_count": positions_count,
        }
        self._append_row(EQUITY_HISTORY_FILE, row)

    def log_trade(self, symbol, action, qty, price, reason, date=None):
        row = {
            "date": date or dt.date.today().isoformat(),
            "symbol": symbol, "action": action, "qty": qty, "price": price, "reason": reason,
        }
        self._append_row(TRADES_HISTORY_FILE, row)

    @staticmethod
    def _append_row(path, row):
        file_exists = os.path.exists(path)
        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
