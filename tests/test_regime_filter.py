import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import regime_filter
from regime_filter import regime_state


class TestRegimeTiers(unittest.TestCase):
    def test_both_confirm_bullish(self):
        with patch.object(regime_filter, "index_regime_bullish", return_value=True), \
             patch.object(regime_filter, "breadth_above_200dma_pct", return_value=0.55):
            r = regime_state(None, [], equity=200000)
        self.assertEqual(r["tier"], "BULLISH")
        self.assertEqual(r["entry_size_mult"], 1.0)
        self.assertFalse(r["force_exit_all"])

    def test_signals_disagree_is_caution_not_severe(self):
        with patch.object(regime_filter, "index_regime_bullish", return_value=True), \
             patch.object(regime_filter, "breadth_above_200dma_pct", return_value=0.25):
            r = regime_state(None, [], equity=200000)
        self.assertEqual(r["tier"], "CAUTION")
        self.assertEqual(r["entry_size_mult"], config.CAUTION_ENTRY_SIZE_MULT)
        self.assertFalse(r["force_exit_all"], "CAUTION must never force-exit existing positions")

    def test_both_confirm_breakdown_is_severe(self):
        with patch.object(regime_filter, "index_regime_bullish", return_value=False), \
             patch.object(regime_filter, "breadth_above_200dma_pct", return_value=0.10):
            r = regime_state(None, [], equity=200000)
        self.assertEqual(r["tier"], "SEVERE")
        self.assertEqual(r["entry_size_mult"], 0.0)
        self.assertTrue(r["force_exit_all"])

    def test_small_equity_softens_breadth_requirement(self):
        # below REGIME_SOFTEN_BELOW_EQUITY, weak breadth alone shouldn't
        # downgrade from BULLISH as long as the index trend itself holds
        with patch.object(regime_filter, "index_regime_bullish", return_value=True), \
             patch.object(regime_filter, "breadth_above_200dma_pct", return_value=0.10):
            small = regime_state(None, [], equity=10000)
            large = regime_state(None, [], equity=200000)
        self.assertEqual(small["tier"], "BULLISH")
        self.assertEqual(large["tier"], "CAUTION")

    def test_small_equity_softening_does_not_override_bad_index_trend(self):
        with patch.object(regime_filter, "index_regime_bullish", return_value=False), \
             patch.object(regime_filter, "breadth_above_200dma_pct", return_value=0.10):
            r = regime_state(None, [], equity=10000)
        self.assertNotEqual(r["tier"], "BULLISH",
                             "softening for small accounts must not bypass a confirmed bad index trend")

    def test_full_bypass_flag_only_active_when_explicitly_enabled(self):
        with patch.object(config, "REGIME_FULLY_BYPASS_BELOW_EQUITY", True), \
             patch.object(regime_filter, "index_regime_bullish", return_value=False), \
             patch.object(regime_filter, "breadth_above_200dma_pct", return_value=0.0):
            r = regime_state(None, [], equity=10000)
        self.assertEqual(r["tier"], "BULLISH")
        self.assertEqual(r["entry_size_mult"], 1.0)


if __name__ == "__main__":
    unittest.main()
