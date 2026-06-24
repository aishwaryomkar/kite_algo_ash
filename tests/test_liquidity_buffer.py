import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from liquidity_buffer import get_buffer_holding, max_redeemable_value, redeem_for_shortfall


class FakeKite:
    def __init__(self, symbol_qty=None, price=1000):
        self.symbol_qty = symbol_qty or {}
        self.price = price
        self.sell_calls = []

    def holdings(self):
        return [
            {"tradingsymbol": sym, "quantity": qty, "last_price": self.price}
            for sym, qty in self.symbol_qty.items()
        ]


def fake_place_sell(kite, symbol, qty, price):
    kite.sell_calls.append((symbol, qty, price))


class TestLiquidityBuffer(unittest.TestCase):
    def setUp(self):
        self.orig_symbol = config.LIQUIDITY_BUFFER_SYMBOL
        self.orig_cap_pct = config.LIQUIDITY_BUFFER_MAX_UTILIZATION_PCT
        self.orig_haircut = config.SAME_DAY_SELL_PROCEEDS_USABLE_PCT
        config.LIQUIDITY_BUFFER_SYMBOL = "LIQUIDCASE"
        config.LIQUIDITY_BUFFER_MAX_UTILIZATION_PCT = 0.50
        config.SAME_DAY_SELL_PROCEEDS_USABLE_PCT = 0.80

    def tearDown(self):
        config.LIQUIDITY_BUFFER_SYMBOL = self.orig_symbol
        config.LIQUIDITY_BUFFER_MAX_UTILIZATION_PCT = self.orig_cap_pct
        config.SAME_DAY_SELL_PROCEEDS_USABLE_PCT = self.orig_haircut

    def test_get_buffer_holding_reads_real_holdings_shape(self):
        kite = FakeKite(symbol_qty={"LIQUIDCASE": 35}, price=1000)
        qty, price, value = get_buffer_holding(kite)
        self.assertEqual((qty, price, value), (35, 1000, 35000))

    def test_get_buffer_holding_absent_returns_zeros(self):
        kite = FakeKite(symbol_qty={"SOMEOTHERFUND": 10}, price=1000)
        self.assertEqual(get_buffer_holding(kite), (0, 0, 0))

    def test_regression_does_not_round_to_zero_at_high_unit_price(self):
        """
        Bug found in production: flooring the unit quantity (int() instead
        of ceil()) meant a shortfall smaller than one unit's price sold ZERO
        units and silently failed the whole trade, even though one extra
        unit would have covered it easily.
        """
        kite = FakeKite(symbol_qty={"LIQUIDCASE": 14}, price=2500)  # 14 * 2500 = 35000
        usable, sale_value = redeem_for_shortfall(kite, fake_place_sell, shortfall_amount=2400,
                                                    already_redeemed_today=0)
        self.assertGreater(usable, 0, "should have sold at least 1 unit to cover the shortfall")
        self.assertEqual(len(kite.sell_calls), 1)
        sold_qty = kite.sell_calls[0][1]
        self.assertGreaterEqual(sold_qty, 1)

    def test_regression_targets_gross_amount_accounting_for_haircut(self):
        """
        Bug found in production: redemption targeted the shortfall itself as
        the GROSS sale amount, but only 80% of any sale is usable same-day -
        so it always fell ~20% short of actually covering the shortfall,
        even with perfect unit-price rounding. Fixed version should target
        enough gross sale value that the NET usable amount actually covers
        the shortfall, where the cap allows.
        """
        kite = FakeKite(symbol_qty={"LIQUIDCASE": 1000}, price=10)  # plenty of units, no rounding pressure
        shortfall = 2400
        usable, sale_value = redeem_for_shortfall(kite, fake_place_sell, shortfall_amount=shortfall,
                                                    already_redeemed_today=0)
        self.assertGreaterEqual(usable, shortfall - 1,  # -1 for integer-unit rounding slack
                                 f"usable cash {usable} should cover the Rs{shortfall} shortfall after the haircut")

    def test_redemption_never_exceeds_cap_across_calls_in_one_run(self):
        kite = FakeKite(symbol_qty={"LIQUIDCASE": 1000}, price=10)  # value = 10,000; cap = 50% = 5,000
        already_redeemed = 0
        total_sale_value = 0
        for _ in range(10):  # repeatedly ask for far more than the cap allows
            usable, sale_value = redeem_for_shortfall(kite, fake_place_sell, shortfall_amount=5000,
                                                        already_redeemed_today=already_redeemed)
            already_redeemed += sale_value
            total_sale_value += sale_value
        cap = max_redeemable_value(kite)
        self.assertLessEqual(total_sale_value, cap + 10,  # +10 = one unit's price of rounding slack
                              "cumulative redemption across a run must respect the per-run cap")

    def test_zero_holding_returns_nothing(self):
        kite = FakeKite(symbol_qty={}, price=1000)
        usable, sale_value = redeem_for_shortfall(kite, fake_place_sell, shortfall_amount=5000,
                                                    already_redeemed_today=0)
        self.assertEqual((usable, sale_value), (0, 0))


if __name__ == "__main__":
    unittest.main()
