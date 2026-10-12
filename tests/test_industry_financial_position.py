import unittest

from app.financial.industry_position import build_industry_financial_position


class IndustryFinancialPositionTests(unittest.TestCase):
    def test_returns_aligned_peer_median_percentile_sample_and_coverage(self):
        snapshot = {
            "report_date": "20260630",
            "scores": {
                "sh:600001": {"industry_sw_level_2": "酿酒", "latest_period": "2026Q2", "report_date": "20260630", "raw_sub_indicators": {"net_margin": 30, "ocf_to_profit": 0.8, "debt_ratio": 20, "ar_days": 15, "inv_days": 30}},
                "sh:600002": {"industry_sw_level_2": "酿酒", "latest_period": "2026Q2", "report_date": "20260630", "raw_sub_indicators": {"net_margin": 20, "ocf_to_profit": 0.6, "debt_ratio": 30, "ar_days": 10, "inv_days": 40}},
                "sz:000003": {"industry_sw_level_2": "酿酒", "latest_period": "2026Q2", "report_date": "20260630", "raw_sub_indicators": {"net_margin": 10, "ocf_to_profit": 0.4, "debt_ratio": 40, "ar_days": 20, "inv_days": 20}},
                "sh:600004": {"industry_sw_level_2": "酿酒", "latest_period": "2025A", "report_date": "20251231", "raw_sub_indicators": {"net_margin": 99}},
            },
        }
        result = build_industry_financial_position("sh", "600001", snapshot)
        self.assertEqual("酿酒", result["industry_level_2"])
        self.assertEqual("2026Q2", result["report_period"])
        self.assertEqual(4, result["industry_member_count"])
        self.assertEqual(3, result["aligned_sample_count"])
        self.assertEqual(75.0, result["period_alignment_coverage"])
        self.assertEqual(20.0, result["metrics"]["net_margin"]["industry_median"])
        self.assertEqual(100.0, result["metrics"]["net_margin"]["percentile"])
        self.assertEqual(3, result["metrics"]["net_margin"]["sample_count"])
        self.assertEqual(20.0, result["metrics"]["debt_ratio"]["company_value"])


if __name__ == "__main__":
    unittest.main()
