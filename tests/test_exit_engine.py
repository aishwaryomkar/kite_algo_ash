import sys
import os
import unittest
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exit_engine import evaluate_exit


def make_healthy_hist(last_price=150):
    """A flat 100-bar base followed by one strong bar - last_price ends up
    clearly above the trailing 100DMA (~100.5), unambiguously 'healthy'."""
    closes = [100] * 100 + [last_price]
    return pd.DataFrame({"close": closes})


CAUTION_REGIME = {"force_exit_all": False, "rank_exit_threshold": 25}
SEVERE_REGIME = {"force_exit_all": True, "rank_exit_threshold": 50}
BULLISH_REGIME = {"force_exit_all": False, "rank_exit_threshold": 50}


class TestExitEngine(unittest.TestCase):
    def setUp(self):
        self.hist = make_healthy_hist()
        self.pos = {"stop_price": 90, "entry_price": 100, "entry_date": "2026-06-01", "partial_booked": True}
        self.rank_df = pd.DataFrame({"symbol": ["GOODSTOCK"], "rank": [3]})

    def test_severe_tier_force_exits_regardless_of_stock_health(self):
        decision, reason = evaluate_exit("GOODSTOCK", self.pos, self.hist, self.rank_df, SEVERE_REGIME)
        self.assertEqual(decision, "FULL_EXIT")
        self.assertEqual(reason, "market_filter_severe")

    def test_caution_tier_does_not_force_exit_a_healthy_position(self):
        """This is the core behavioral fix from the original binary design:
        a stock still in a clean uptrend, ranked top-3, should NOT get
        force-sold just because the regime is in CAUTION."""
        decision, reason = evaluate_exit("GOODSTOCK", self.pos, self.hist, self.rank_df, CAUTION_REGIME)
        self.assertNotEqual(reason, "market_filter_severe")
        self.assertNotEqual(decision, "FULL_EXIT")

    def test_stop_hit_still_exits_even_in_bullish_regime(self):
        hist = make_healthy_hist(last_price=85)  # below the 90 stop
        decision, reason = evaluate_exit("X", self.pos, hist, self.rank_df, BULLISH_REGIME)
        self.assertEqual(decision, "FULL_EXIT")
        self.assertEqual(reason, "stop_hit")

    def test_caution_uses_tighter_rank_threshold(self):
        rank_df = pd.DataFrame({"symbol": ["X"], "rank": [30]})  # inside 50, outside 25
        pos = {"stop_price": 50, "entry_price": 100, "entry_date": "2026-06-01", "partial_booked": True}
        hist = make_healthy_hist(last_price=150)

        decision_bullish, _ = evaluate_exit("X", pos, hist, rank_df, BULLISH_REGIME)
        decision_caution, reason_caution = evaluate_exit("X", pos, hist, rank_df, CAUTION_REGIME)

        self.assertNotEqual(decision_bullish, "FULL_EXIT")
        self.assertEqual(decision_caution, "FULL_EXIT")
        self.assertEqual(reason_caution, "rank_decayed")

    def test_rank_decay_uses_regime_supplied_threshold_not_a_hardcoded_one(self):
        rank_df = pd.DataFrame({"symbol": ["X"], "rank": [40]})
        pos = {"stop_price": 50, "entry_price": 100, "entry_date": "2026-06-01", "partial_booked": True}
        hist = make_healthy_hist(last_price=150)
        custom_regime = {"force_exit_all": False, "rank_exit_threshold": 100}
        decision, _ = evaluate_exit("X", pos, hist, rank_df, custom_regime)
        self.assertNotEqual(decision, "FULL_EXIT")


if __name__ == "__main__":
    unittest.main()
