import sys
import os
import unittest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from universe import load_excluded_holdings, apply_liquidity_filter


class FakeHist:
    def __init__(self, price, vol=200000, n=25):
        import pandas as pd
        self.df = pd.DataFrame({"close": [price] * n, "volume": [vol] * n})
        self.empty = False

    def tail(self, n):
        return self.df.tail(n)

    def __len__(self):
        return len(self.df)


class FakeFetcher:
    def __init__(self, prices):
        self.prices = prices

    def historical(self, symbol, days=40):
        return FakeHist(self.prices[symbol])


class TestExclusionList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmpdir)
        with open(config.EXCLUDED_HOLDINGS_CSV, "w") as f:
            f.write("symbol\nITC\nARROWGREEN-T\nSKMEGGPROD\n")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_excluded_symbols_loaded_correctly(self):
        excluded = load_excluded_holdings()
        self.assertEqual(excluded, {"ITC", "ARROWGREEN-T", "SKMEGGPROD"})

    def test_excluded_symbol_never_enters_universe_even_if_otherwise_eligible(self):
        """Core safety guarantee: an existing discretionary holding must
        never appear as a candidate, even if its price/turnover would
        otherwise easily pass every other filter."""
        fetcher = FakeFetcher({"ITC": 280, "RELIANCE": 600})  # ITC excluded, RELIANCE not
        result = apply_liquidity_filter(["ITC", "RELIANCE"], fetcher)
        self.assertNotIn("ITC", result)
        self.assertIn("RELIANCE", result)

    def test_no_exclusion_file_means_nothing_excluded(self):
        os.remove(config.EXCLUDED_HOLDINGS_CSV)
        self.assertEqual(load_excluded_holdings(), set())

    def test_exclusion_check_is_case_insensitive_and_trims_whitespace(self):
        with open(config.EXCLUDED_HOLDINGS_CSV, "w") as f:
            f.write("symbol\n itc \n")
        excluded = load_excluded_holdings()
        self.assertIn("ITC", excluded)


if __name__ == "__main__":
    unittest.main()
