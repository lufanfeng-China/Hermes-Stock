import unittest
from unittest import mock


class StockScoreAdjustmentTests(unittest.TestCase):
    def test_blend_market_scores_with_industry_prioritizes_cross_industry_dimensions(self) -> None:
        from app.search import index as idx

        market_scores = {sub_key: 10.0 for sub_key, *_ in idx._SUB_DEFS}
        industry_scores = {sub_key: 90.0 for sub_key, *_ in idx._SUB_DEFS}

        adjusted = idx.blend_market_scores_with_industry(market_scores, industry_scores)

        self.assertAlmostEqual(66.0, adjusted["ar_days"])
        self.assertAlmostEqual(66.0, adjusted["current_ratio"])
        self.assertAlmostEqual(66.0, adjusted["goodwill_ratio"])
        self.assertEqual(10.0, adjusted["roe_ex"])
        self.assertEqual(10.0, adjusted["revenue_growth"])
        self.assertEqual(10.0, adjusted["ocf_to_profit"])

    def test_compute_stock_score_uses_adjusted_market_scores_from_snapshot(self) -> None:
        from app.search import index as idx

        market_scores = {sub_key: 20.0 for sub_key, *_ in idx._SUB_DEFS}
        industry_scores = {sub_key: 80.0 for sub_key, *_ in idx._SUB_DEFS}
        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:601600": {
                    "report_date": "20260331",
                    "announce_date": "20260424",
                    "latest_period": "2026Q1",
                    "sub_indicators": market_scores,
                    "ind_sub_indicators": industry_scores,
                    "ind_dim_scores": {"profitability": 20.0},
                    "ind_total_score": 61.0,
                    "raw_sub_indicators": {},
                    "prev_raw_sub_indicators": {},
                },
                "sh:601168": {
                    "report_date": "20260331",
                    "announce_date": "20260424",
                    "latest_period": "2026Q1",
                    "sub_indicators": {sub_key: 10.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_sub_indicators": {sub_key: 30.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_dim_scores": {"profitability": 10.0},
                    "ind_total_score": 58.0,
                    "raw_sub_indicators": {},
                    "prev_raw_sub_indicators": {},
                },
                "sh:600111": {
                    "report_date": "20260331",
                    "announce_date": "20260424",
                    "latest_period": "2026Q1",
                    "sub_indicators": {sub_key: 5.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_sub_indicators": {sub_key: 15.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_dim_scores": {"profitability": 5.0},
                    "ind_total_score": 40.0,
                    "raw_sub_indicators": {},
                    "prev_raw_sub_indicators": {},
                },
            },
        }

        industry_map = {
            ("sh", "601600"): ("工业金属", "有色"),
            ("sh", "601168"): ("工业金属", "有色"),
            ("sh", "600111"): ("稀土", "有色"),
        }

        with (
            mock.patch.object(idx, "_load_financial_snapshot", return_value=snapshot),
            mock.patch.object(idx, "_stock_name_lookup", return_value={("sh", "601600"): "中国铝业"}),
            mock.patch.object(idx, "_load_industry_map", return_value=industry_map),
        ):
            result = idx.compute_stock_score("sh", "601600")

        self.assertEqual("industry_adjusted_market_view", result["score_methodology"]["market_score_mode"])
        self.assertAlmostEqual(62.0, result["score_data"]["current_ratio"])
        self.assertAlmostEqual(62.0, result["score_data"]["ar_days"])
        self.assertAlmostEqual(20.0, result["score_data"]["roe_ex"])
        self.assertEqual(1, result["market_total_rank"])
        self.assertEqual(3, result["market_total_universe_size"])
        self.assertEqual(1, result["industry_total_rank"])
        self.assertEqual(2, result["industry_total_universe_size"])

    def test_compute_stock_score_returns_latest_report_analysis_strengths_and_risks(self) -> None:
        from app.search import index as idx

        market_scores = {sub_key: 50.0 for sub_key, *_ in idx._SUB_DEFS}
        industry_scores = {sub_key: 50.0 for sub_key, *_ in idx._SUB_DEFS}
        market_scores.update({
            "roe_ex": 88.0,
            "profit_growth": 83.0,
            "ocf_to_profit": 78.0,
            "debt_ratio": 22.0,
            "goodwill_ratio": 24.0,
        })
        raw_sub = {
            "roe_ex": 12.3,
            "profit_growth": 40.0,
            "ocf_to_profit": 1.8,
            "debt_ratio": 72.0,
            "goodwill_ratio": 18.0,
        }
        prev_raw_sub = {
            "roe_ex": 9.8,
            "profit_growth": 8.0,
            "ocf_to_profit": 1.2,
            "debt_ratio": 68.0,
            "goodwill_ratio": 15.0,
        }
        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:601600": {
                    "report_date": "20260331",
                    "announce_date": "20260424",
                    "latest_period": "2026Q1",
                    "sub_indicators": market_scores,
                    "ind_sub_indicators": industry_scores,
                    "ind_dim_scores": {},
                    "ind_total_score": 0.0,
                    "raw_sub_indicators": raw_sub,
                    "prev_raw_sub_indicators": prev_raw_sub,
                }
            },
        }

        with (
            mock.patch.object(idx, "_load_financial_snapshot", return_value=snapshot),
            mock.patch.object(idx, "_stock_name_lookup", return_value={("sh", "601600"): "中国铝业"}),
        ):
            result = idx.compute_stock_score("sh", "601600")

        analysis = result["latest_report_analysis"]
        self.assertIn("strengths", analysis)
        self.assertIn("risks", analysis)
        self.assertTrue(analysis["strengths"])
        self.assertTrue(analysis["risks"])


if __name__ == "__main__":
    unittest.main()
