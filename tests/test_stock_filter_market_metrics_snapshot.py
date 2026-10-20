import unittest

import pandas as pd


class StockFilterMarketMetricsSnapshotTest(unittest.TestCase):
    def test_build_market_metrics_emits_one_record_per_stock_with_qfq_metrics(self):
        from app.stock_filter_market_snapshot import build_market_metrics

        dates = pd.bdate_range("2026-01-01", periods=25)
        frame = pd.DataFrame({
            "date": list(dates) * 2,
            "market": ["sh"] * 25 + ["sz"] * 25,
            "symbol": ["600001"] * 25 + ["000001"] * 25,
            "open": list(range(9, 34)) + list(range(19, 44)),
            "close": list(range(10, 35)) + list(range(20, 45)),
            "volume": [100.0] * 50,
            "free_float_shares": [10_000.0] * 50,
        })

        payload = build_market_metrics(frame)

        self.assertEqual(payload["schema_version"], "stock-filter-market-metrics-v1")
        self.assertEqual(payload["stocks"], 2)
        self.assertEqual(payload["metrics"]["sh:600001"]["return_1d"], round((34 / 33 - 1) * 100, 4))
        self.assertEqual(payload["metrics"]["sh:600001"]["turnover_5_sum"], 5.0)
        self.assertIsNone(payload["metrics"]["sh:600001"]["trend_weekly"])
        self.assertEqual(payload["metrics"]["sz:000001"]["qfq_as_of"], "2026-02-04")

    def test_build_market_metrics_records_auditable_blowup_break_evidence(self):
        from app.stock_filter_market_snapshot import build_market_metrics

        dates = pd.bdate_range("2026-01-01", periods=11)
        # V6-V10 establish VA=100; V1-V5 are 阳线且每一天放量超过3xVA.
        frame = pd.DataFrame({
            "date": dates,
            "market": ["sz"] * 11,
            "symbol": ["000001"] * 11,
            "open": [9.0] * 6 + [9.9, 10.0, 10.1, 10.2, 10.3],
            "close": [9.0] * 5 + [10.0, 10.1, 10.2, 10.3, 10.4, 11.0],
            "volume": [100.0] * 6 + [301.0] * 5,
            "free_float_shares": [10_000.0] * 11,
        })

        item = build_market_metrics(frame)["metrics"]["sz:000001"]

        self.assertTrue(item["blowup_break_volume_price_ok"])
        self.assertEqual(item["blowup_break_va"], 100.0)
        self.assertEqual(item["blowup_break_vol_ratios"], [3.01] * 5)
        self.assertEqual(item["blowup_break_return_5d"], 10.0)

    def test_build_market_metrics_emits_daily_and_short_trends_for_historical_blowup_validation(self):
        from app.stock_filter_market_snapshot import build_market_metrics

        dates = pd.bdate_range("2025-01-01", periods=260)
        closes = [10.0 + index * 0.1 for index in range(260)]
        frame = pd.DataFrame({
            "date": dates, "market": ["sz"] * 260, "symbol": ["000001"] * 260,
            "open": [value - 0.05 for value in closes], "close": closes,
            "volume": [100.0] * 260, "free_float_shares": [10_000.0] * 260,
        })

        item = build_market_metrics(frame)["metrics"]["sz:000001"]

        self.assertIn(item["trend_daily"], {"strong_bullish", "bullish", "recovering"})
        self.assertIn(item["short_trend"], {"strong_bullish", "bullish", "recovering"})


if __name__ == "__main__":
    unittest.main()
