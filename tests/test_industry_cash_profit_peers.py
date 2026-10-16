import unittest

from app.financial.reports import build_cash_profit_peer_values


class IndustryCashProfitPeerValuesTests(unittest.TestCase):
    def test_reports_return_annual_quarter_and_ttm_values_with_same_period_growth(self):
        reports = [
            {"period": "2024A", "metrics": {"ocf": 120.0, "ex_net_profit": 100.0}},
            {"period": "2025Q2", "metrics": {"ocf": 70.0, "ex_net_profit": 50.0}},
            {"period": "2025A", "metrics": {"ocf": 180.0, "ex_net_profit": 150.0}},
            {"period": "2026Q2", "metrics": {"ocf": 132.0, "ex_net_profit": 88.0}},
        ]

        result = build_cash_profit_peer_values(reports)

        self.assertEqual(result["annual"]["period"], "2025A")
        self.assertAlmostEqual(result["annual"]["value"], 1.2)
        self.assertAlmostEqual(result["annual"]["yoy_pct"], 0.0)
        self.assertEqual(result["quarter"]["period"], "2026Q2")
        self.assertAlmostEqual(result["quarter"]["value"], 1.5)
        self.assertAlmostEqual(result["quarter"]["yoy_pct"], (1.5 / 1.4 - 1) * 100)
        self.assertEqual(result["ttm"]["period"], "2026Q2")
        self.assertAlmostEqual(result["ttm"]["value"], 242 / 188)
        self.assertIsNone(result["ttm"]["yoy_pct"])  # 2024Q2 is absent, so matching TTM growth is unavailable.

    def test_missing_or_zero_profit_is_unavailable_not_zero(self):
        result = build_cash_profit_peer_values([
            {"period": "2025A", "metrics": {"ocf": 10.0, "ex_net_profit": 0.0}},
            {"period": "2026Q2", "metrics": {"ocf": 10.0, "ex_net_profit": None}},
        ])

        self.assertIsNone(result["annual"]["value"])
        self.assertIsNone(result["quarter"]["value"])
        self.assertIsNone(result["ttm"]["value"])


if __name__ == "__main__":
    unittest.main()
