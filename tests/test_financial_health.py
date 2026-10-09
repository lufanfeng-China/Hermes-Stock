import unittest

from app.financial.health import build_financial_health


def annual(year, **metrics):
    return {
        "year": str(year),
        "period": f"{year}A",
        "report_date": f"{year}1231",
        "metrics": metrics,
    }


class FinancialHealthTests(unittest.TestCase):
    def test_uses_five_complete_annual_reports_and_ignores_current_interim_report(self):
        reports = [
            annual(2021, revenue=100, ex_net_profit=10, ocf=12, free_cf=8, gross_margin=30, net_margin=10, roe_ex=12, debt_ratio=40, accounts_receivable=10, inventory=15, capex=4, goodwill=0, equity=60, total_assets=100),
            annual(2022, revenue=120, ex_net_profit=13, ocf=15, free_cf=10, gross_margin=31, net_margin=11, roe_ex=13, debt_ratio=39, accounts_receivable=11, inventory=16, capex=5, goodwill=0, equity=65, total_assets=110),
            annual(2023, revenue=140, ex_net_profit=16, ocf=18, free_cf=12, gross_margin=32, net_margin=12, roe_ex=14, debt_ratio=38, accounts_receivable=12, inventory=17, capex=6, goodwill=0, equity=70, total_assets=120),
            annual(2024, revenue=170, ex_net_profit=21, ocf=25, free_cf=17, gross_margin=34, net_margin=14, roe_ex=16, debt_ratio=37, accounts_receivable=14, inventory=18, capex=8, goodwill=0, equity=76, total_assets=130),
            annual(2025, revenue=200, ex_net_profit=27, ocf=33, free_cf=23, gross_margin=36, net_margin=16, roe_ex=18, debt_ratio=36, accounts_receivable=15, inventory=19, capex=10, goodwill=0, equity=84, total_assets=145),
            {"year": "2026", "period": "2026Q2", "report_date": "20260630", "metrics": {"revenue": 90}},
        ]

        health = build_financial_health(reports)

        self.assertEqual(health["periods"], ["2021A", "2022A", "2023A", "2024A", "2025A"])
        self.assertAlmostEqual(health["derived"]["revenue_cagr"], 18.9207, places=3)
        self.assertAlmostEqual(health["derived"]["ex_net_profit_cagr"], 28.186, places=3)
        self.assertAlmostEqual(health["derived"]["profit_growth_premium"], 9.265, places=3)
        self.assertAlmostEqual(health["derived"]["five_year_cash_profit_ratio"], 1.1839, places=3)
        self.assertEqual(len(health["dimensions"]), 6)
        self.assertLessEqual(health["score"], 100)
        self.assertGreaterEqual(health["score"], 0)
        self.assertEqual(health["red_flags"], [])

    def test_risk_trend_marks_deleveraging_as_improvement(self):
        reports = [annual(2021 + index, revenue=100 + index * 10, ex_net_profit=10 + index, ocf=12 + index, free_cf=5 + index, gross_margin=30, net_margin=10, roe_ex=12, debt_ratio=60 - index * 5, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=50, total_assets=100) for index in range(5)]
        health = build_financial_health(reports)
        risk = next(item for item in health["dimensions"] if item["code"] == "financial_risk")
        self.assertEqual(risk["trend"], "up")

    def test_flags_capex_increase_with_revenue_growth_deceleration(self):
        reports = [
            annual(2021, revenue=100, ex_net_profit=20, ocf=20, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=1, goodwill=0, equity=60, total_assets=100),
            annual(2022, revenue=130, ex_net_profit=21, ocf=21, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=2, goodwill=0, equity=60, total_assets=100),
            annual(2023, revenue=150, ex_net_profit=22, ocf=22, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100),
            annual(2024, revenue=165, ex_net_profit=23, ocf=23, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=4, goodwill=0, equity=60, total_assets=100),
            annual(2025, revenue=170, ex_net_profit=24, ocf=24, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=60, total_assets=100),
        ]
        health = build_financial_health(reports)
        self.assertIn("capex_up_revenue_growth_down", {flag["code"] for flag in health["red_flags"]})

    def test_rejects_non_contiguous_annual_periods(self):
        reports = [annual(year, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=60, total_assets=100) for year in (2018, 2019, 2021, 2023, 2025)]
        health = build_financial_health(reports)
        self.assertEqual(health["status"], "insufficient_data")
        self.assertEqual(health["reason"], "annual_reports_not_contiguous")

    def test_marks_special_industry_as_not_applicable(self):
        reports = [annual(2021 + index, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=60, total_assets=100) for index in range(5)]
        health = build_financial_health(reports, industry_level_1="银行", industry_level_2="全国性银行")
        self.assertEqual(health["status"], "not_applicable")
        self.assertIsNone(health["score"])
        self.assertIn("银行", health["reason"])

    def test_reports_red_flags_without_allowing_score_to_hide_them(self):
        reports = [
            annual(2021, revenue=100, ex_net_profit=20, ocf=25, free_cf=5, gross_margin=40, net_margin=20, roe_ex=20, debt_ratio=30, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=70, total_assets=100),
            annual(2022, revenue=110, ex_net_profit=19, ocf=20, free_cf=-1, gross_margin=39, net_margin=18, roe_ex=18, debt_ratio=35, accounts_receivable=14, inventory=14, capex=6, goodwill=1, equity=72, total_assets=110),
            annual(2023, revenue=120, ex_net_profit=18, ocf=15, free_cf=-2, gross_margin=38, net_margin=16, roe_ex=16, debt_ratio=41, accounts_receivable=20, inventory=20, capex=8, goodwill=3, equity=74, total_assets=125),
            annual(2024, revenue=130, ex_net_profit=17, ocf=12, free_cf=-3, gross_margin=37, net_margin=14, roe_ex=14, debt_ratio=48, accounts_receivable=28, inventory=29, capex=11, goodwill=6, equity=76, total_assets=145),
            annual(2025, revenue=140, ex_net_profit=16, ocf=10, free_cf=-4, gross_margin=36, net_margin=12, roe_ex=12, debt_ratio=56, accounts_receivable=39, inventory=42, capex=15, goodwill=10, equity=78, total_assets=175),
        ]

        health = build_financial_health(reports)

        codes = {flag["code"] for flag in health["red_flags"]}
        self.assertTrue({"revenue_up_ex_profit_down", "receivables_growth_gap", "inventory_growth_gap", "gross_margin_two_year_decline", "roe_ex_decline", "debt_ratio_rising", "fcf_two_year_negative", "goodwill_up_profit_not"}.issubset(codes))
        self.assertGreaterEqual(health["red_flag_count"], 8)
        self.assertIn("status", health)


if __name__ == "__main__":
    unittest.main()
