import unittest
from unittest import mock


class IndustryHealthPeersTests(unittest.TestCase):
    def test_returns_all_secondary_industry_members_with_separate_annual_and_quarterly_scores(self):
        from app.financial import reports

        def payload(market, symbol, years=6):
            return {
                "stock_name": {"000001": "甲公司", "000002": "乙公司"}[symbol],
                "health": {
                    "score": 76 if symbol == "000001" else None,
                    "periods": ["2021A", "2022A", "2023A", "2024A", "2025A"],
                    "assessment_track": "five_year",
                    "sample_years": 5,
                    "coverage_weight": 100,
                    "status": "available",
                    "dimensions": [
                        {"code": "growth_quality", "score": 15}, {"code": "profitability", "score": 16},
                        {"code": "cash_quality", "score": 14}, {"code": "working_capital", "score": 12},
                        {"code": "reinvestment", "score": 8}, {"code": "financial_risk", "score": 11},
                    ],
                },
                "quarterly_monitor": {
                    "latest_period": "2026Q2", "status": "available",
                    "realtime_score": {"score": 69 if symbol == "000001" else None, "coverage_weight": 100,
                                       "status": "complete", "breakdown": [
                                           {"code": "growth", "points": 12}, {"code": "profitability", "points": 12},
                                           {"code": "cash", "points": 12}, {"code": "working_capital", "points": 9},
                                           {"code": "reinvestment", "points": 6}, {"code": "financial_risk", "points": 9},
                                       ]},
                },
            }

        with (
            mock.patch("app.search.index._load_industry_map", return_value={
                ("sz", "000001"): ("测试二级", "测试一级"),
                ("sz", "000002"): ("测试二级", "测试一级"),
                ("sh", "600000"): ("其他二级", "测试一级"),
            }),
            mock.patch.object(reports, "load_recent_three_year_financial_reports", side_effect=payload),
        ):
            result = reports.build_industry_financial_health_peers("sz", "000001")

        self.assertTrue(result["ok"])
        self.assertEqual("测试二级", result["industry_level_2"])
        self.assertEqual(2, len(result["rows"]))
        current = next(row for row in result["rows"] if row["is_current_stock"])
        self.assertEqual("甲公司", current["stock_name"])
        self.assertEqual(76, current["annual"]["score"])
        self.assertEqual(15, current["annual"]["dimensions"]["growth_quality"])
        self.assertEqual("2026Q2", current["quarterly"]["period"])
        self.assertEqual(69, current["quarterly"]["score"])
        self.assertEqual(12, current["quarterly"]["dimensions"]["growth_quality"])
        other = next(row for row in result["rows"] if row["symbol"] == "000002")
        self.assertIsNone(other["annual"]["score"])
        self.assertIsNone(other["quarterly"]["score"])


if __name__ == "__main__":
    unittest.main()
