import unittest

import pandas as pd


class StockFilterFundamentalHistoryTest(unittest.TestCase):
    def test_as_of_snapshot_excludes_reports_announced_after_signal_day(self):
        from app.stock_filter_fundamental_history import build_historical_fundamental_snapshot

        periods = {
            "2020A": pd.DataFrame({"announce_date": [20210401], "基本每股收益": [1.0], "营业总收入TTM(万元)": [100000], "总股本": [100000000]}, index=["000001"]),
            "2021A": pd.DataFrame({"announce_date": [20220401], "基本每股收益": [1.1], "营业总收入TTM(万元)": [110000], "总股本": [100000000]}, index=["000001"]),
            "2022A": pd.DataFrame({"announce_date": [20230401], "基本每股收益": [1.2], "营业总收入TTM(万元)": [120000], "总股本": [100000000]}, index=["000001"]),
            "2023A": pd.DataFrame({"announce_date": [20240401], "基本每股收益": [1.3], "营业总收入TTM(万元)": [130000], "总股本": [100000000]}, index=["000001"]),
            "2024A": pd.DataFrame({"announce_date": [20250425], "基本每股收益": [2.0], "营业总收入TTM(万元)": [200000], "总股本": [100000000]}, index=["000001"]),
        }
        prices = {"000001": 10.0}

        payload = build_historical_fundamental_snapshot(
            as_of_date="2025-04-20", period_frames=periods, raw_close_by_symbol=prices,
            market_by_symbol={"000001": "sz"}, industry_by_key={},
        )

        row = payload["stocks"]["sz:000001"]
        self.assertEqual(row["annual_period"], "2023A")
        self.assertEqual(row["latest_announce_date"], "2024-04-01")
        self.assertEqual(row["pe_ttm"], round(10.0 / 1.3, 4))
        self.assertEqual(row["ps_ttm"], round((10.0 * 100000000) / (130000 * 10000), 4))

    def test_negative_ttm_eps_and_missing_ttm_revenue_are_unavailable(self):
        from app.stock_filter_fundamental_history import valuation_from_available_report

        record = valuation_from_available_report(
            raw_close=12.0,
            report_row=pd.Series({"基本每股收益": -0.2, "营业总收入TTM(万元)": None, "总股本": 100000000}),
        )

        self.assertIsNone(record["pe_ttm"])
        self.assertIsNone(record["ps_ttm"])
        self.assertEqual(record["pe_ttm_reason"], "ttm_eps_non_positive")
        self.assertEqual(record["ps_ttm_reason"], "ttm_revenue_or_share_capital_unavailable")
    def test_snapshot_merges_historical_blowup_evidence_from_same_day_market_metrics(self):
        from app.stock_filter_fundamental_history import build_historical_fundamental_snapshot
        frame = pd.DataFrame([{
            'announce_date': '20250101', '基本每股收益': 1.0, '营业总收入TTM(万元)': 100.0, '总股本': 100.0,
        }], index=['000001'])
        snapshot = build_historical_fundamental_snapshot(
            as_of_date='2025-04-18', period_frames={'2024A': frame}, raw_close_by_symbol={'000001': 10.0},
            market_by_symbol={'000001': 'sz'}, industry_by_key={},
            market_metrics_by_key={'sz:000001': {'blowup_break_volume_price_ok': True, 'trend_daily': 'bullish', 'short_trend': 'recovering'}},
        )

        row = snapshot['stocks']['sz:000001']
        self.assertTrue(row['blowup_break_volume_price_ok'])
        self.assertEqual('bullish', row['trend_daily'])
        self.assertEqual('recovering', row['short_trend'])


if __name__ == "__main__":
    unittest.main()
