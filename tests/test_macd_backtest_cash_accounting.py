import sys
import unittest

import pandas as pd

sys.path.insert(0, "/home/lufanfeng/Project-Hermes-Stock")
from app.strategy.macd_backtest_engine import simulate_portfolio


def _bars(rows):
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")


class TestMacdBacktestCashAccounting(unittest.TestCase):
    def assert_accounting(self, result, initial_capital):
        summary = result["summary"]
        self.assertAlmostEqual(
            summary["equity"],
            initial_capital + summary["realized_pnl"] + summary["unrealized_pnl"],
        )
        self.assertAlmostEqual(summary["equity"], summary["cash"] + summary["market_value"])

    def test_t1_entry_and_exit_reconcile_cash_and_realized_pnl(self):
        bars = _bars([
            {"date": "2020-01-02", "open": 100, "close": 100, "buy_signal": True, "replenish_signal": False, "dead_cross": False},
            {"date": "2020-01-03", "open": 100, "close": 100, "buy_signal": False, "replenish_signal": False, "dead_cross": False},
            {"date": "2020-01-06", "open": 130, "close": 130, "buy_signal": False, "replenish_signal": False, "dead_cross": False},
            {"date": "2020-01-07", "open": 130, "close": 130, "buy_signal": False, "replenish_signal": False, "dead_cross": True},
            {"date": "2020-01-08", "open": 120, "close": 120, "buy_signal": False, "replenish_signal": False, "dead_cross": False},
        ])

        result = simulate_portfolio({"000001": bars}, initial_capital=10_000, lot_cash=10_000)

        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["buy_cost"], 10_000)
        self.assertEqual(result["history"][0]["sell_rev"], 12_000)
        self.assertEqual(result["summary"]["realized_pnl"], 2_000)
        self.assertEqual(result["summary"]["cash"], 12_000)
        self.assertEqual(result["positions"], {})
        self.assert_accounting(result, 10_000)

    def test_t1_replenish_is_debited_and_included_in_exit_pnl(self):
        bars = _bars([
            {"date": "2020-01-02", "open": 100, "close": 100, "buy_signal": True, "replenish_signal": False, "dead_cross": False},
            {"date": "2020-01-03", "open": 100, "close": 100, "buy_signal": False, "replenish_signal": False, "dead_cross": False},
            {"date": "2020-01-06", "open": 70, "close": 70, "buy_signal": True, "replenish_signal": True, "dead_cross": False},
            {"date": "2020-01-07", "open": 70, "close": 150, "buy_signal": False, "replenish_signal": False, "dead_cross": False},
            {"date": "2020-01-08", "open": 150, "close": 150, "buy_signal": False, "replenish_signal": False, "dead_cross": True},
            {"date": "2020-01-09", "open": 150, "close": 150, "buy_signal": False, "replenish_signal": False, "dead_cross": False},
        ])

        result = simulate_portfolio({"000001": bars}, initial_capital=20_000, lot_cash=10_000)

        history = result["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["buy_cost"], 19_940)
        self.assertEqual(history[0]["sell_rev"], 36_300)
        self.assertEqual(history[0]["pnl"], 16_360)
        self.assertEqual(result["summary"]["cash"], 36_360)
        self.assertEqual(result["summary"]["realized_pnl"], 16_360)
        self.assertEqual(result["positions"], {})
        self.assert_accounting(result, 20_000)


if __name__ == "__main__":
    unittest.main()
