import sys
import unittest

import pandas as pd

sys.path.insert(0, "/home/lufanfeng/Project-Hermes-Stock")
from scripts.backtest_ma25_rps_three_position_csi300_v1 import (
    build_signal_features,
    select_candidates,
    simulate_portfolio,
)


class CandidateSelectionTests(unittest.TestCase):
    def test_select_candidates_keeps_top_three_distinct_l2_industries(self):
        candidates = [
            {"code": "000001", "industry_l2": "银行", "rank_score": 400.0},
            {"code": "000002", "industry_l2": "银行", "rank_score": 399.0},
            {"code": "000003", "industry_l2": "半导体", "rank_score": 300.0},
            {"code": "000004", "industry_l2": "软件开发", "rank_score": 200.0},
            {"code": "000005", "industry_l2": "通信设备", "rank_score": 100.0},
        ]

        selected = select_candidates(candidates, available_slots=3)

        self.assertEqual(["000001", "000003", "000004"], [row["code"] for row in selected])
        self.assertEqual(3, len({row["industry_l2"] for row in selected}))

    def test_select_candidates_honors_available_slots_and_rank_order(self):
        candidates = [
            {"code": "000001", "industry_l2": "银行", "rank_score": 90.0},
            {"code": "000002", "industry_l2": "半导体", "rank_score": 100.0},
        ]

        selected = select_candidates(candidates, available_slots=1)

        self.assertEqual(["000002"], [row["code"] for row in selected])

    def test_select_candidates_returns_empty_for_no_slots_or_candidates(self):
        self.assertEqual([], select_candidates([], available_slots=3))
        self.assertEqual([], select_candidates([{"code": "000001", "industry_l2": "银行", "rank_score": 1.0}], available_slots=0))


class QfqSignalTests(unittest.TestCase):
    def test_build_signal_features_requires_every_ma25_rps_and_candle_rule(self):
        dates = pd.bdate_range("2026-01-01", periods=61)
        close = [100.0] * 35 + [100.0 + 8.0 * index / 25 for index in range(26)]
        qfq = pd.DataFrame(
            {
                "open": [99.5] * 60 + [103.0],
                "high": [100.5] * 60 + [110.0],
                "low": [99.0] * 60 + [101.2],
                "close": close,
                "volume": [100.0] * 56 + [150.0] * 5,
            },
            index=dates,
        )
        rps = pd.DataFrame(
            {
                "date": [dates[-1]],
                "rps_20": [70.0],
                "rps_50": [71.0],
                "rps_120": [72.0],
                "rps_250": [73.0],
            }
        ).set_index("date")

        result = build_signal_features(qfq, rps)

        self.assertTrue(result.loc[dates[-1], "entry_signal"])
        self.assertGreater(result.loc[dates[-1], "rank_score"], 0)
        self.assertFalse(result.loc[dates[-1], "dead_cross"])

    def test_build_signal_features_never_accepts_missing_or_sub70_rps(self):
        dates = pd.bdate_range("2026-01-01", periods=61)
        qfq = pd.DataFrame(
            {"open": [100.0] * 61, "high": [101.0] * 61, "low": [99.0] * 61,
             "close": [100.0] * 35 + [100.0 + 8.0 * index / 25 for index in range(26)],
             "volume": [100.0] * 56 + [150.0] * 5}, index=dates,
        )
        rps = pd.DataFrame({"date": [dates[-1]], "rps_20": [69.99], "rps_50": [90], "rps_120": [90], "rps_250": [90]}).set_index("date")

        result = build_signal_features(qfq, rps)

        self.assertFalse(result.loc[dates[-1], "entry_signal"])


class ChronologicalPortfolioTests(unittest.TestCase):
    def test_signal_close_creates_t_plus_one_entries_with_three_slot_cap_and_strict_mtm(self):
        dates = pd.bdate_range("2026-04-01", periods=3)

        def frame(signal, score):
            return pd.DataFrame(
                {"raw_open": [10.0, 10.0, 11.0], "raw_close": [10.0, 10.5, 11.0],
                 "signal_close": [10.0, 10.5, 11.0],
                 "entry_signal": [signal, False, False], "rank_score": [score, None, None],
                 "ma10": [9.0, 9.0, 9.0], "ma25": [9.0, 9.0, 9.0],
                 "dead_cross": [False, False, False]}, index=dates,
            )

        result = simulate_portfolio(
            {"000001": frame(True, 400), "000002": frame(True, 300),
             "000003": frame(True, 200), "000004": frame(True, 100)},
            {"000001": "银行", "000002": "半导体", "000003": "软件开发", "000004": "通信设备"},
            initial_cash=300.0,
            lot_cash=100.0,
        )

        self.assertEqual(0, result["daily_equity"][0]["positions"])
        self.assertEqual(3, result["daily_equity"][1]["positions"])
        self.assertEqual(3, len(result["positions"]))
        self.assertEqual(3, result["orders_executed"])
        for row in result["daily_equity"]:
            self.assertAlmostEqual(row["equity"], row["cash"] + row["market_value"])
            self.assertGreaterEqual(row["cash"], 0.0)


if __name__ == "__main__":
    unittest.main()
