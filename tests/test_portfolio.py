import sys
import os
import unittest
import tempfile
import shutil
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import portfolio
from portfolio import (
    load_positions, save_positions, can_add_position, sector_counts,
    total_equity_estimate,
)


class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load_roundtrip(self):
        positions = {"RELIANCE": {"qty": 10, "entry_price": 1200}}
        save_positions(positions)
        self.assertEqual(load_positions(), positions)

    def test_load_with_no_file_returns_empty_dict(self):
        self.assertEqual(load_positions(), {})

    def test_max_positions_cap_enforced(self):
        sector_map = {f"SYM{i}": "Sector" + str(i) for i in range(10)}
        positions = {f"SYM{i}": {} for i in range(config.MAX_POSITIONS)}
        ok, reason = can_add_position("NEWSTOCK", positions, sector_map)
        self.assertFalse(ok)
        self.assertEqual(reason, "max_positions_reached")

    def test_sector_cap_enforced(self):
        sector_map = {"RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy"}
        positions = {f"SYM{i}": {} for i in range(config.MAX_PER_SECTOR)}
        with patch.object(portfolio, "sector_counts", return_value={"Energy": config.MAX_PER_SECTOR}):
            ok, reason = can_add_position("BPCL", positions, sector_map)
        self.assertFalse(ok)
        self.assertIn("sector_cap_reached", reason)

    def test_sector_counts_tallies_correctly(self):
        positions = {"RELIANCE": {}, "ONGC": {}, "TCS": {}}
        sector_map = {"RELIANCE": "Energy", "ONGC": "Energy", "TCS": "IT"}
        counts = sector_counts(positions, sector_map)
        self.assertEqual(counts, {"Energy": 2, "IT": 1})

    def test_unmapped_symbol_falls_back_to_unknown_sector(self):
        positions = {}
        sector_map = {}  # symbol not in the map at all
        ok, reason = can_add_position("MYSTERYSTOCK", positions, sector_map)
        self.assertTrue(ok)  # should not crash or block - just treated as UNKNOWN sector

    def test_total_equity_estimate_uses_ltp_when_available(self):
        positions = {"RELIANCE": {"qty": 10, "entry_price": 1200}}
        ltp_map = {"RELIANCE": 1300}
        equity = total_equity_estimate(positions, ltp_map, cash=5000)
        self.assertEqual(equity, 5000 + 10 * 1300)

    def test_total_equity_estimate_falls_back_to_entry_price_if_no_ltp(self):
        positions = {"RELIANCE": {"qty": 10, "entry_price": 1200}}
        equity = total_equity_estimate(positions, ltp_map={}, cash=5000)
        self.assertEqual(equity, 5000 + 10 * 1200)


if __name__ == "__main__":
    unittest.main()
