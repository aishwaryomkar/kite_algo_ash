import sys
import os
import unittest
import tempfile
import shutil
import pandas as pd
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import risk_engine
from risk_engine import size_position, atr_stop, kill_switch_action, update_equity_peak


class FakeFetcher:
    """size_position calls fetcher.historical(symbol, days=30) for the liquidity cap."""
    def __init__(self, volume=1000):
        self.volume = volume

    def historical(self, symbol, days=30):
        return pd.DataFrame({"volume": [self.volume] * 20})


class TestRiskEngine(unittest.TestCase):
    def setUp(self):
        # risk_engine persists state to a file in the cwd - isolate each test
        # in its own temp dir so tests can't see each other's state.
        self.tmpdir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_size_position_respects_all_three_caps(self):
        equity = 100000
        entry_price, stop_price = 100, 95  # stop distance 5

        with patch.object(config, "RISK_PER_TRADE_PCT", 0.01), \
             patch.object(config, "MAX_CAPITAL_PCT_PER_STOCK", 0.25), \
             patch.object(config, "MAX_ADV_PARTICIPATION", 0.05):
            qty = size_position(entry_price, stop_price, equity, FakeFetcher(volume=1000), "TEST", 1.0)

        # risk-based: (100000*0.01)/5 = 200
        # capital cap: (100000*0.25)/100 = 250
        # liquidity cap: 1000*0.05 = 50  <- this is the binding constraint
        self.assertEqual(qty, 50)

    def test_conviction_mult_scales_risk_amount_only(self):
        equity = 100000
        entry_price, stop_price = 100, 95
        fetcher = FakeFetcher(volume=1_000_000)  # liquidity cap deliberately not binding here

        with patch.object(config, "RISK_PER_TRADE_PCT", 0.01), \
             patch.object(config, "MAX_CAPITAL_PCT_PER_STOCK", 0.25):
            qty_normal = size_position(entry_price, stop_price, equity, fetcher, "TEST", 1.0)
            qty_high = size_position(entry_price, stop_price, equity, fetcher, "TEST", 2.0)
            qty_low = size_position(entry_price, stop_price, equity, fetcher, "TEST", 0.5)

        self.assertGreater(qty_high, qty_normal)
        self.assertLess(qty_low, qty_normal)
        # capital cap = (100000*0.25)/100 = 250, must never be exceeded regardless of conviction
        self.assertLessEqual(qty_high, 250)

    def test_zero_or_negative_stop_distance_returns_zero(self):
        qty = size_position(100, 100, 100000, FakeFetcher(), "TEST", 1.0)
        self.assertEqual(qty, 0)
        qty2 = size_position(100, 105, 100000, FakeFetcher(), "TEST", 1.0)  # stop ABOVE entry
        self.assertEqual(qty2, 0)

    def test_kill_switch_seeds_peak_from_real_equity_not_config_constant(self):
        # Regression test for the bug where a fresh risk_state.json seeded
        # equity_peak from config.EQUITY (a static constant) instead of the
        # real starting equity, producing a false ~100% drawdown on the very
        # first run for any account smaller than config.EQUITY.
        peak = update_equity_peak(7479)
        self.assertEqual(peak, 7479)
        action, dd = kill_switch_action(7479)
        self.assertIsNone(action)
        self.assertEqual(dd, 0.0)

    def test_kill_switch_levels_match_actual_config(self):
        update_equity_peak(100000)

        action, dd = kill_switch_action(100000)
        self.assertIsNone(action)

        action, dd = kill_switch_action(95000)  # -5%
        self.assertEqual(action, "REDUCE_25")
        self.assertAlmostEqual(dd, 0.05)

        action, dd = kill_switch_action(92000)  # -8%
        self.assertEqual(action, "REDUCE_50")

        action, dd = kill_switch_action(88000)  # -12%
        self.assertEqual(action, "NO_NEW_ENTRIES")

        action, dd = kill_switch_action(85000)  # -15%
        self.assertEqual(action, "EXIT_WEAKEST_HALF")

        action, dd = kill_switch_action(80000)  # -20%
        self.assertEqual(action, "EXIT_ALL")

    def test_apply_kill_switch_to_size(self):
        from risk_engine import apply_kill_switch_to_size
        self.assertEqual(apply_kill_switch_to_size(100, "REDUCE_25"), 75)
        self.assertEqual(apply_kill_switch_to_size(100, "REDUCE_50"), 50)
        self.assertEqual(apply_kill_switch_to_size(100, "NO_NEW_ENTRIES"), 0)
        self.assertEqual(apply_kill_switch_to_size(100, "EXIT_ALL"), 0)
        self.assertEqual(apply_kill_switch_to_size(100, None), 100)


if __name__ == "__main__":
    unittest.main()
