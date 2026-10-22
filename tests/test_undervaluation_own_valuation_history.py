import unittest

import pandas as pd


class OwnValuationHistoryTests(unittest.TestCase):
    def test_uses_only_disclosures_already_announced_on_each_raw_price_day(self):
        from app.undervaluation.own_valuation_history import build_own_valuation_history

        result = build_own_valuation_history(
            bars=[
                {"trading_day": "2024-01-02", "close": 10.0},
                {"trading_day": "2024-01-03", "close": 12.0},
                {"trading_day": "2024-04-02", "close": 14.0},
                {"trading_day": "2024-04-03", "close": 16.0},
            ],
            disclosures=[
                {"announce_date": "2024-01-03", "ttm_eps": 2.0, "ttm_revenue": 100.0, "total_shares": 100.0, "period": "2023Q3"},
                {"announce_date": "2024-04-03", "ttm_eps": 4.0, "ttm_revenue": 200.0, "total_shares": 100.0, "period": "2023A"},
            ],
            as_of_date="2024-04-03",
        )

        self.assertEqual(3, result["pe_valid_trading_days"])
        self.assertEqual(3, result["ps_valid_trading_days"])
        self.assertEqual("2023A", result["latest_disclosed_period"])
        self.assertEqual(4.0, result["latest_pe_ttm"])
        self.assertEqual(8.0, result["latest_ps_ttm"])
        self.assertEqual("2024-01-03", result["series"][0]["announce_date"])
        self.assertEqual("2024-04-03", result["series"][-1]["announce_date"])

    def test_builds_disclosures_from_warehouse_rows_without_future_report(self):
        from app.undervaluation.own_valuation_history import build_pit_disclosures_from_period_frames

        frames = {
            "2023A": pd.DataFrame([{
                "announce_date": 20240403, "基本每股收益": 2.0,
                "营业总收入TTM(万元)": 100.0, "总股本": 100.0,
            }], index=["000001"]),
            "2024A": pd.DataFrame([{
                "announce_date": 20250403, "基本每股收益": 3.0,
                "营业总收入TTM(万元)": 150.0, "总股本": 100.0,
            }], index=["000001"]),
        }

        disclosures = build_pit_disclosures_from_period_frames(
            period_frames=frames, symbol="000001", as_of_date="2024-12-31",
        )

        self.assertEqual(1, len(disclosures))
        self.assertEqual("2023A", disclosures[0]["period"])
        self.assertEqual("2024-04-03", disclosures[0]["announce_date"])
        self.assertEqual(2.0, disclosures[0]["ttm_eps"])
        self.assertEqual(1_000_000.0, disclosures[0]["ttm_revenue"])

    def test_summarizes_three_year_500_day_own_history_with_empirical_percentiles(self):
        from app.undervaluation.own_valuation_history import summarize_own_valuation_history

        history = {
            "as_of_date": "2024-10-19",
            "series": [
                {"trading_day": "2021-10-19", "pe_ttm": 20.0, "ps_ttm": 4.0},
                *[{"trading_day": "2023-01-01", "pe_ttm": 20.0, "ps_ttm": 4.0} for _ in range(498)],
                {"trading_day": "2024-10-19", "pe_ttm": 10.0, "ps_ttm": 2.0},
            ],
        }

        result = summarize_own_valuation_history(history)

        self.assertTrue(result["coverage_sufficient"])
        self.assertEqual(500, result["pe_valid_trading_days"])
        self.assertEqual(500, result["ps_valid_trading_days"])
        self.assertLessEqual(result["pe_percentile"], 30.0)
        self.assertLessEqual(result["ps_percentile"], 30.0)


if __name__ == "__main__":
    unittest.main()
