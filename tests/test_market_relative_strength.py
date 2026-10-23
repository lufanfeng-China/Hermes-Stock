from __future__ import annotations

import unittest

import pandas as pd


class MarketRelativeStrengthTests(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        # Both securities have 251+ QFQ bars.  In the final 20 sessions, A
        # gains +0.1% daily while B falls -2.0% daily: daily equal-weight
        # benchmark is negative, so A must register a positive anti-fall edge.
        dates = pd.bdate_range("2025-01-01", periods=271)
        rows = []
        for market, symbol, daily_return in (("sh", "600001", 0.001), ("sz", "000001", -0.02)):
            close = 10.0
            for index, date in enumerate(dates):
                if index >= 251:
                    close *= 1.0 + daily_return
                rows.append({"date": date, "market": market, "symbol": symbol, "close": close})
        return pd.DataFrame(rows)

    def test_builds_qfq_daily_equal_weight_benchmark_and_auditable_excess(self) -> None:
        from app.market_relative_strength import build_market_relative_strength

        payload = build_market_relative_strength(self._frame(), min_eligible_universe=2)
        stock = payload["stocks"]["sh:600001"]

        self.assertEqual("tdx_export_qfq", stock["price_basis"])
        self.assertEqual("all_a_daily_equal_weight_rps_universe", stock["benchmark_method"])
        self.assertGreater(stock["mrs_score"], 70)
        self.assertGreater(stock["excess_return_20_pp"], 0)
        self.assertEqual(20, stock["down_market_days_20"])
        self.assertEqual(20, stock["down_market_outperform_days_20"])
        self.assertEqual(100.0, stock["down_market_win_rate_20"])
        self.assertGreater(stock["down_market_avg_excess_pp_20"], 0)
        detail = stock["down_market_detail_20"]
        self.assertEqual(20, len(detail))
        self.assertEqual(sorted(item["date"] for item in detail), [item["date"] for item in detail])
        self.assertTrue(all(item["market_return_pct"] < 0 for item in detail))
        self.assertTrue(all(item["stock_return_pct"] > 0 for item in detail))
        self.assertTrue(all(item["excess_return_pp"] > 0 for item in detail))

    def test_marks_antifall_as_insufficient_when_fewer_than_five_down_days(self) -> None:
        from app.market_relative_strength import build_market_relative_strength

        frame = self._frame()
        # Make the broad benchmark non-negative in 16 of the final 20 days.
        mask = (frame["symbol"] == "000001") & (frame["date"] >= frame["date"].max() - pd.Timedelta(days=21))
        frame.loc[mask, "close"] = 10.0
        payload = build_market_relative_strength(frame, min_eligible_universe=2)

        self.assertLess(payload["stocks"]["sh:600001"]["down_market_days_20"], 5)
        self.assertEqual("sample_insufficient", payload["stocks"]["sh:600001"]["anti_fall_status"])

    def test_classifies_conflict_between_long_term_mrs_and_recent_er20(self) -> None:
        from app.market_relative_strength import classify_relative_strength_state

        self.assertEqual("high_level_weakening", classify_relative_strength_state(82, -0.1))
        self.assertEqual("low_level_strengthening", classify_relative_strength_state(40, 0.1))
        self.assertEqual("trend_aligned", classify_relative_strength_state(82, 1.0))


if __name__ == "__main__":
    unittest.main()
