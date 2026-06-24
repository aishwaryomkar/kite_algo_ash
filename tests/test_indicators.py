import sys
import os
import unittest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from indicators import dma, rsi, atr, pullback_from_high, returns


class TestIndicators(unittest.TestCase):
    def setUp(self):
        self.series = pd.Series([100, 101, 102, 101, 100, 99, 100, 101, 102, 103])
        self.df = pd.DataFrame({
            "high": [105, 106, 107, 106, 105, 104, 105, 106, 107, 108],
            "low": [95, 96, 97, 96, 95, 94, 95, 96, 97, 98],
            "close": [100, 101, 102, 101, 100, 99, 100, 101, 102, 103],
        })

    def test_dma(self):
        result = dma(self.series, 3)
        expected = pd.Series([np.nan, np.nan, 101.0, 101.333333, 101.0, 100.0,
                               99.666667, 100.0, 101.0, 102.0])
        pd.testing.assert_series_equal(result.round(4), expected.round(4), check_names=False)

    def test_rsi_bounded(self):
        result = rsi(self.series, 3)
        self.assertEqual(len(result), len(self.series))
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 100).all())

    def test_atr_nonnegative(self):
        result = atr(self.df, 3)
        self.assertEqual(len(result), len(self.df))
        self.assertTrue((result.dropna() >= 0).all())

    def test_pullback_from_high_bounded(self):
        result = pullback_from_high(self.series, 3)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 1).all())
        # at the series' own running high, pullback should be ~0
        self.assertAlmostEqual(result.iloc[2], 0.0, places=4)

    def test_returns(self):
        result = returns(self.series, 1)
        self.assertAlmostEqual(result.iloc[1], 0.01, places=4)  # 100 -> 101


if __name__ == "__main__":
    unittest.main()
