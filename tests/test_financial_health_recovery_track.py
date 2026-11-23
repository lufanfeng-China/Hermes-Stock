import unittest

from app.financial.health import build_financial_health


def annual(year, *, revenue, ex_net_profit, ocf=12, free_cf=6):
    return {
        "year": str(year),
        "period": f"{year}A",
        "report_date": f"{year}1231",
        "metrics": {
            "revenue": revenue,
            "ex_net_profit": ex_net_profit,
            "ocf": ocf,
            "free_cf": free_cf,
            "gross_margin": 30,
            "net_margin": 10,
            "roe_ex": 10,
            "debt_ratio": 40,
            "accounts_receivable": 10,
            "inventory": 10,
            "capex": 3,
            "goodwill": 1,
            "equity": 60,
            "total_assets": 100,
        },
    }


class FinancialHealthRecoveryTrackTests(unittest.TestCase):
    def test_profit_path_table_is_auditable_for_recovery_and_deterioration_cases(self):
        cases = [
            ([-10, -5, 2, 4, 6], "turnaround", 13, "recovery_track"),
            ([-10, -8, -6, -4, -2], "loss_narrowing", 5, "recovery_track"),
            ([-1, -2, -3, -4, -5], "loss_widening", 0, "deteriorating_track"),
            ([-5, -5, -5, -5, -5], "loss_flat", 1, "deteriorating_track"),
        ]
        for profits, expected_path, expected_score, expected_track in cases:
            with self.subTest(path=expected_path):
                reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=value) for i, value in enumerate(profits)]
                health = build_financial_health(reports, industry_level_1="医药医疗")
                evidence = next(item for item in health["score_breakdown"] if item["code"] == "growth_quality")["evidence"]
                self.assertEqual(health["derived"]["ex_net_profit_path"], expected_path)
                self.assertEqual(evidence["subscores"]["profit_path"], expected_score)
                self.assertEqual(health["score_basis_track"], expected_track)

    def test_positive_but_declining_profit_keeps_standard_cagr_basis_with_low_points(self):
        profits = [10, 9, 8, 7, 6]
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=value) for i, value in enumerate(profits)]

        health = build_financial_health(reports, industry_level_1="医药医疗")
        growth = next(item for item in health["dimensions"] if item["code"] == "growth_quality")

        self.assertEqual(health["growth_quality_basis"], "cagr")
        self.assertEqual(health["score_basis_track"], "five_year_standard")
        self.assertTrue(growth["available"])

    def test_profit_to_loss_is_zero_profit_path_score_but_available_growth_dimension(self):
        profits = [10, 8, 5, 1, -2]
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=value) for i, value in enumerate(profits)]

        health = build_financial_health(reports, industry_level_1="医药医疗")
        growth = next(item for item in health["dimensions"] if item["code"] == "growth_quality")
        evidence = next(item for item in health["score_breakdown"] if item["code"] == "growth_quality")["evidence"]

        self.assertEqual(health["derived"]["ex_net_profit_path"], "profit_to_loss")
        self.assertEqual(health["growth_quality_basis"], "profit_path")
        self.assertEqual(health["score_basis_track"], "deteriorating_track")
        self.assertEqual(health["score_version"], "financial-health-v3-recovery")
        self.assertFalse(health["score_comparable"])
        self.assertTrue(growth["available"])
        self.assertEqual(evidence["subscores"]["profit_path"], 0)
        self.assertIsInstance(health["score"], float)
        self.assertIn("ex_net_profit_profit_to_loss", [item["code"] for item in health["investigation_items"]])

    def test_non_positive_cumulative_profit_uses_absolute_cash_creation_score(self):
        profits = [-10, -8, -6, -4, -2]
        reports = [
            annual(2021 + i, revenue=100 + i * 10, ex_net_profit=profit, ocf=5 + i, free_cf=1 + i)
            for i, profit in enumerate(profits)
        ]

        health = build_financial_health(reports, industry_level_1="医药医疗")
        cash = next(item for item in health["dimensions"] if item["code"] == "cash_quality")
        evidence = next(item for item in health["score_breakdown"] if item["code"] == "cash_quality")["evidence"]

        self.assertEqual(health["cash_quality_basis"], "absolute_cash_support")
        self.assertEqual(health["score_basis_track"], "recovery_track")
        self.assertTrue(cash["available"])
        self.assertEqual(evidence["subscores"]["absolute_cash_support"], 9)
        self.assertIsInstance(health["score"], float)

    def test_missing_profit_and_cash_fields_remain_explicitly_unavailable(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=-5, ocf=5, free_cf=2) for i in range(5)]
        reports[2]["metrics"]["ex_net_profit"] = None
        reports[3]["metrics"]["ocf"] = None

        health = build_financial_health(reports, industry_level_1="医药医疗")
        dimensions = {item["code"]: item for item in health["dimensions"]}

        self.assertEqual(health["growth_quality_basis"], "unavailable")
        self.assertEqual(health["cash_quality_basis"], "unavailable")
        self.assertFalse(dimensions["growth_quality"]["available"])
        self.assertFalse(dimensions["cash_quality"]["available"])
        self.assertIsNone(health["score"])

    def test_strict_snapshot_projects_recovery_basis_fields(self):
        from app.stock_filter_snapshot import build_strict_financial_record

        profits = [-10, -8, -6, -4, -2]
        reports = [
            annual(2021 + i, revenue=100 + i * 10, ex_net_profit=profit, ocf=5 + i, free_cf=1 + i)
            for i, profit in enumerate(profits)
        ]

        record = build_strict_financial_record(
            reports, industry_level_1="医药医疗", annual_anchor="2025A", quarterly_anchor="2026Q3"
        )
        annual_record = record["annual"]

        self.assertEqual(annual_record["score_basis_track"], "recovery_track")
        self.assertEqual(annual_record["growth_quality_basis"], "profit_path")
        self.assertEqual(annual_record["cash_quality_basis"], "absolute_cash_support")
        self.assertFalse(annual_record["score_comparable"])
        self.assertEqual(annual_record["score_version"], "financial-health-v3-recovery")

    def test_special_industry_is_explicitly_not_applicable_not_comparable(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10) for i in range(5)]

        health = build_financial_health(reports, industry_level_1="银行")

        self.assertEqual(health["status"], "not_applicable")
        self.assertEqual(health["score_basis_track"], "not_applicable")
        self.assertFalse(health["score_comparable"])
        self.assertEqual(health["growth_quality_basis"], "unavailable")
        self.assertEqual(health["cash_quality_basis"], "unavailable")


if __name__ == "__main__":
    unittest.main()
