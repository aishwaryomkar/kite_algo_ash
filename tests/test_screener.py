import sys
import os
import unittest
import pandas as pd
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from screener import add_conviction


class TestConviction(unittest.TestCase):
    def test_dominant_leader_clamped_at_max_not_unbounded(self):
        scores = [0.85] + [0.30 + i * 0.01 for i in range(19)]
        df = pd.DataFrame({"symbol": [f"S{i}" for i in range(20)], "score": scores})
        df = add_conviction(df)
        self.assertTrue((df["conviction_mult"] <= config.CONVICTION_MAX_MULT).all())
        self.assertTrue((df["conviction_mult"] >= config.CONVICTION_MIN_MULT).all())
        # the dominant outlier should hit the ceiling, not just be "high"
        self.assertEqual(df.loc[0, "conviction_mult"], config.CONVICTION_MAX_MULT)

    def test_laggard_in_a_strong_field_gets_shrunk(self):
        scores = [0.85, 0.84, 0.83, 0.30]  # three strong leaders, one barely-qualifying laggard
        df = pd.DataFrame({"symbol": ["A", "B", "C", "LAGGARD"], "score": scores})
        df = add_conviction(df)
        laggard_mult = df.loc[df["symbol"] == "LAGGARD", "conviction_mult"].iloc[0]
        self.assertLess(laggard_mult, 1.0)

    def test_disabled_via_config_returns_neutral_multiplier(self):
        df = pd.DataFrame({"symbol": ["A", "B"], "score": [0.5, 0.9]})
        with patch.object(config, "CONVICTION_SCALING_ENABLED", False):
            df = add_conviction(df)
        self.assertTrue((df["conviction_mult"] == 1.0).all())

    def test_zero_variance_field_returns_neutral_not_nan(self):
        # every candidate has the identical score - std is 0, must not divide by zero
        df = pd.DataFrame({"symbol": ["A", "B", "C"], "score": [0.5, 0.5, 0.5]})
        df = add_conviction(df)
        self.assertTrue((df["conviction_mult"] == 1.0).all())
        self.assertFalse(df["conviction_mult"].isna().any())

    def test_single_candidate_returns_neutral(self):
        df = pd.DataFrame({"symbol": ["A"], "score": [0.7]})
        df = add_conviction(df)
        self.assertEqual(df.loc[0, "conviction_mult"], 1.0)


if __name__ == "__main__":
    unittest.main()
