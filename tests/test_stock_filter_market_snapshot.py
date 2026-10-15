import unittest

import pandas as pd


class StockFilterMarketSnapshotTest(unittest.TestCase):
    def test_qfq_metrics_use_close_return_and_float_share_turnover(self):
        from app.stock_filter_snapshot import calculate_qfq_market_metrics
        bars = pd.DataFrame({"close": [10.0, 11.0, 12.0, 15.0], "volume": [100.0, 200.0, 300.0, 400.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]))
        row = calculate_qfq_market_metrics(bars, free_float_shares=10_000.0, turnover_days=2)
        self.assertEqual(row["returns"]["1d"], 25.0)
        self.assertIsNone(row["returns"]["5d"])
        self.assertEqual(row["turnover"]["days"], 2)
        self.assertEqual(row["turnover"]["sum_pct"], 7.0)
        self.assertEqual(row["turnover"]["avg_pct"], 3.5)

    def test_qfq_metrics_never_treat_missing_float_shares_as_zero_turnover(self):
        from app.stock_filter_snapshot import calculate_qfq_market_metrics
        bars = pd.DataFrame({"close": [10.0, 11.0], "volume": [100.0, 200.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
        row = calculate_qfq_market_metrics(bars, free_float_shares=None, turnover_days=2)
        self.assertIsNone(row["turnover"])


if __name__ == "__main__":
    unittest.main()
