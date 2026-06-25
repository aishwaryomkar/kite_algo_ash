import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import fundamentals
from fundamentals import institutional_sponsorship_trend, eps_growth_estimate


class TestInstitutionalSponsorship(unittest.TestCase):
    def test_stable_promoter_holding_passes(self):
        client = MagicMock()
        client.shareholding.return_value = [
            {"date": "2026-03-31", "pr_and_prgrp": "55.0", "public_val": "44.5", "employeeTrusts": "0.5"},
            {"date": "2025-12-31", "pr_and_prgrp": "55.2", "public_val": "44.3", "employeeTrusts": "0.5"},
        ]
        passes, details = institutional_sponsorship_trend(client, "TESTSTOCK")
        self.assertTrue(passes)
        self.assertAlmostEqual(details["change_pct"], -0.2, places=2)

    def test_significant_promoter_drop_fails(self):
        client = MagicMock()
        client.shareholding.return_value = [
            {"date": "2026-03-31", "pr_and_prgrp": "40.0", "public_val": "59.5", "employeeTrusts": "0.5"},
            {"date": "2025-12-31", "pr_and_prgrp": "55.0", "public_val": "44.5", "employeeTrusts": "0.5"},
        ]
        passes, details = institutional_sponsorship_trend(client, "TESTSTOCK")
        self.assertFalse(passes)
        self.assertLess(details["change_pct"], -config.MAX_PROMOTER_HOLDING_DROP_PCT)

    def test_promoter_increase_passes(self):
        client = MagicMock()
        client.shareholding.return_value = [
            {"date": "2026-03-31", "pr_and_prgrp": "58.0", "public_val": "41.5", "employeeTrusts": "0.5"},
            {"date": "2025-12-31", "pr_and_prgrp": "55.0", "public_val": "44.5", "employeeTrusts": "0.5"},
        ]
        passes, details = institutional_sponsorship_trend(client, "TESTSTOCK")
        self.assertTrue(passes)

    def test_fetch_error_returns_none_not_a_guess(self):
        client = MagicMock()
        client.shareholding.side_effect = Exception("network error")
        passes, details = institutional_sponsorship_trend(client, "TESTSTOCK")
        self.assertIsNone(passes)
        self.assertIn("error", details)

    def test_insufficient_history_returns_none(self):
        client = MagicMock()
        client.shareholding.return_value = [{"date": "2026-03-31", "pr_and_prgrp": "55.0"}]
        passes, details = institutional_sponsorship_trend(client, "TESTSTOCK")
        self.assertIsNone(passes)

    def test_unexpected_field_names_returns_none_not_a_crash(self):
        """If NSE changes their response shape, this must fail safe (skip
        the name) rather than crash the whole run or silently misread data."""
        client = MagicMock()
        client.shareholding.return_value = [
            {"date": "2026-03-31", "totally_different_field": "55.0"},
            {"date": "2025-12-31", "totally_different_field": "55.2"},
        ]
        passes, details = institutional_sponsorship_trend(client, "TESTSTOCK")
        self.assertIsNone(passes)
        self.assertIn("error", details)


class TestEpsGrowthStub(unittest.TestCase):
    def test_stub_always_returns_none_not_a_fabricated_number(self):
        """eps_growth_estimate is explicitly superseded/unverified - it must
        never return a confident-looking number."""
        client = MagicMock()
        result, details = eps_growth_estimate(client, "TESTSTOCK")
        self.assertIsNone(result)
        self.assertIn("error", details)


class TestScreenerCanslimCheck(unittest.TestCase):
    """Built from real, observed Avantel data (fetched and verified against
    the actual https://www.screener.in/company/AVANTEL/consolidated/ page)
    - these are hand-calculated expected values, not guesses."""

    MOCK_HTML = """
    <html><body>
    <table>
    <tr><td>EPS in Rs</td>
    <td>0.36</td><td>0.30</td><td>0.61</td><td>0.62</td>
    <td>0.46</td><td>0.28</td><td>0.87</td><td>0.76</td>
    <td>0.23</td><td>0.12</td><td>0.16</td><td>0.10</td><td>0.18</td>
    </tr>
    </table>
    <table>
    <tr><td>10 Years:</td><td></td></tr>
    <tr><td>5 Years:</td><td>0%</td></tr>
    <tr><td>3 Years:</td><td>-17%</td></tr>
    <tr><td>TTM:</td><td>-73%</td></tr>
    </table>
    <table>
    <tr><td>Promoters +</td><td>40.10%</td><td>40.06%</td><td>38.57%</td><td>37.15%</td><td>37.08%</td><td>37.04%</td></tr>
    <tr><td>FIIs +</td><td>0.00%</td><td>0.01%</td><td>0.48%</td><td>0.47%</td><td>0.60%</td><td>0.55%</td></tr>
    <tr><td>DIIs +</td><td>0.01%</td><td>0.00%</td><td>0.43%</td><td>0.18%</td><td>0.00%</td><td>0.92%</td></tr>
    </table>
    </body></html>
    """

    def test_parses_all_three_canslim_fields_correctly(self):
        with patch("fundamentals._fetch_screener_page", return_value=self.MOCK_HTML):
            result, error = fundamentals.screener_canslim_check("AVANTEL")
        self.assertIsNone(error)
        self.assertAlmostEqual(result["quarterly_eps_growth_pct"], -21.74, places=1)
        self.assertEqual(result["annual_profit_cagr_3yr_pct"], -17.0)
        self.assertAlmostEqual(result["institutional_holding_change_pct"], 0.87, places=2)

    def test_fetch_failure_returns_error_not_a_guess(self):
        with patch("fundamentals._fetch_screener_page", side_effect=Exception("connection error")):
            result, error = fundamentals.screener_canslim_check("AVANTEL")
        self.assertIsNone(result)
        self.assertIn("connection error", error)

    def test_completely_unrecognized_page_returns_error(self):
        with patch("fundamentals._fetch_screener_page", return_value="<html><body>nothing here</body></html>"):
            result, error = fundamentals.screener_canslim_check("AVANTEL")
        self.assertIsNone(result)
        self.assertIsNotNone(error)

    def test_parse_numeric_handles_commas_and_percent_signs(self):
        self.assertEqual(fundamentals._parse_numeric("1,234.56"), 1234.56)
        self.assertEqual(fundamentals._parse_numeric("37.04%"), 37.04)
        self.assertIsNone(fundamentals._parse_numeric(""))


class TestCanslimPassesDispatcher(unittest.TestCase):
    def test_routes_to_screener_by_default(self):
        with patch.object(config, "CANSLIM_SOURCE", "screener"), \
             patch.object(fundamentals, "screener_canslim_check", return_value=(
                 {"quarterly_eps_growth_pct": 10.0, "annual_profit_cagr_3yr_pct": 15.0,
                  "institutional_holding_change_pct": 0.5}, None)):
            passes, details = fundamentals.canslim_passes("TESTSTOCK")
        self.assertTrue(passes)

    def test_fails_if_any_configured_threshold_is_not_met(self):
        with patch.object(config, "CANSLIM_SOURCE", "screener"), \
             patch.object(fundamentals, "screener_canslim_check", return_value=(
                 {"quarterly_eps_growth_pct": -5.0, "annual_profit_cagr_3yr_pct": 15.0,
                  "institutional_holding_change_pct": 0.5}, None)):
            passes, details = fundamentals.canslim_passes("TESTSTOCK")
        self.assertFalse(passes)
        self.assertFalse(details["quarterly_eps_growth_ok"])

    def test_routes_to_nse_when_configured(self):
        client = MagicMock()
        client.shareholding.return_value = [
            {"date": "2026-03-31", "pr_and_prgrp": "55.0"},
            {"date": "2025-12-31", "pr_and_prgrp": "55.2"},
        ]
        with patch.object(config, "CANSLIM_SOURCE", "nse"):
            passes, details = fundamentals.canslim_passes("TESTSTOCK", nse_client=client)
        self.assertTrue(passes)

    def test_nse_source_without_client_fails_safe(self):
        with patch.object(config, "CANSLIM_SOURCE", "nse"):
            passes, details = fundamentals.canslim_passes("TESTSTOCK", nse_client=None)
        self.assertIsNone(passes)
        self.assertIn("error", details)


if __name__ == "__main__":
    unittest.main()
