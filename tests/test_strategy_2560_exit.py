import unittest

from scripts.strategy_2560_exit import exit_reason


class Strategy2560ExitTests(unittest.TestCase):
    def test_does_not_exit_on_dead_cross_before_20_percent_profit(self):
        self.assertIsNone(exit_reason(armed=False, pnl_pct=12.0, macd_dead_cross=True))

    def test_arms_once_close_reaches_20_percent_profit(self):
        self.assertEqual(exit_reason(armed=False, pnl_pct=20.0, macd_dead_cross=False), "armed")

    def test_exits_on_macd_dead_cross_after_target_has_been_armed(self):
        self.assertEqual(exit_reason(armed=True, pnl_pct=18.0, macd_dead_cross=True), "macd_dead_cross")

    def test_exits_when_profit_retraces_to_15_percent_after_target_armed(self):
        self.assertEqual(exit_reason(armed=True, pnl_pct=15.0, macd_dead_cross=False), "profit_floor")

    def test_does_not_exit_on_15_percent_floor_before_target_has_been_armed(self):
        self.assertIsNone(exit_reason(armed=False, pnl_pct=15.0, macd_dead_cross=False))


if __name__ == "__main__":
    unittest.main()
