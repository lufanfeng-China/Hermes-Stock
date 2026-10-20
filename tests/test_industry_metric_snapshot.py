import unittest

from app.financial.industry_metric_snapshot import build_industry_metric_rows, build_metric_cells


class IndustryMetricSnapshotTests(unittest.TestCase):
    def test_revenue_has_annual_quarter_and_ttm_values_with_same_basis_growth(self):
        reports = [
            {"period": "2023A", "metrics": {"revenue": 90}},
            {"period": "2024Q2", "metrics": {"revenue": 50}},
            {"period": "2024A", "metrics": {"revenue": 100}},
            {"period": "2025Q2", "metrics": {"revenue": 60}},
            {"period": "2025A", "metrics": {"revenue": 120}},
            {"period": "2026Q2", "metrics": {"revenue": 75}},
        ]

        cells = build_metric_cells(reports, "revenue")

        self.assertEqual(cells["annual"], {"period": "2025A", "value": 120.0, "yoy_value": 20.0, "basis": "annual"})
        self.assertEqual(cells["quarter"], {"period": "2026Q2", "value": 75.0, "yoy_value": 25.0, "basis": "quarter_cumulative"})
        self.assertEqual(cells["ttm"], {"period": "2026Q2", "value": 135.0, "yoy_value": 22.7273, "basis": "ttm"})

    def test_point_in_time_metric_marks_ttm_not_applicable(self):
        reports = [
            {"period": "2025A", "metrics": {"goodwill": 12}},
            {"period": "2026Q2", "metrics": {"goodwill": 14}},
        ]

        cells = build_metric_cells(reports, "goodwill")

        self.assertEqual(cells["annual"]["value"], 12.0)
        self.assertEqual(cells["quarter"]["value"], 14.0)
        self.assertIsNone(cells["ttm"]["value"])
        self.assertEqual(cells["ttm"]["reason"], "point_in_time_metric")
    def test_cash_profit_ratio_uses_flow_consistent_ttm_formula(self):
        reports = [
            {"period": "2023A", "metrics": {"ocf": 90, "ex_net_profit": 45}},
            {"period": "2024Q2", "metrics": {"ocf": 40, "ex_net_profit": 20}},
            {"period": "2024A", "metrics": {"ocf": 100, "ex_net_profit": 50}},
            {"period": "2025Q2", "metrics": {"ocf": 50, "ex_net_profit": 25}},
            {"period": "2025A", "metrics": {"ocf": 120, "ex_net_profit": 60}},
            {"period": "2026Q2", "metrics": {"ocf": 75, "ex_net_profit": 30}},
        ]
        cells = build_metric_cells(reports, "cash_profit_ratio")
        self.assertEqual(cells["annual"]["value"], 2.0)
        self.assertEqual(cells["quarter"]["value"], 2.5)
        self.assertEqual(cells["ttm"]["value"], 2.2307692308)
        self.assertEqual(cells["ttm"]["yoy_value"], 11.5385)

    def test_derived_growth_and_intensity_metrics_preserve_their_specific_basis_contracts(self):
        reports = [
            {"period": "2024Q2", "metrics": {"revenue": 100, "free_cf": 10, "capex": 8, "accounts_receivable": 20, "inventory": 30}},
            {"period": "2024A", "metrics": {"revenue": 200, "free_cf": 20, "capex": 16, "accounts_receivable": 25, "inventory": 35}},
            {"period": "2025Q2", "metrics": {"revenue": 120, "free_cf": 18, "capex": 12, "accounts_receivable": 28, "inventory": 45}},
            {"period": "2025A", "metrics": {"revenue": 240, "free_cf": 30, "capex": 24, "accounts_receivable": 30, "inventory": 42}},
            {"period": "2026Q2", "metrics": {"revenue": 150, "free_cf": 30, "capex": 21, "accounts_receivable": 40, "inventory": 54}},
        ]

        revenue_growth = build_metric_cells(reports, "revenue_growth")
        fcf_margin = build_metric_cells(reports, "fcf_margin")
        capex_intensity = build_metric_cells(reports, "capex_intensity")
        receivable_gap = build_metric_cells(reports, "accounts_receivable_growth_gap")
        inventory_gap = build_metric_cells(reports, "inventory_growth_gap")

        self.assertEqual(revenue_growth["annual"]["value"], 20.0)
        self.assertEqual(revenue_growth["quarter"]["value"], 25.0)
        self.assertIsNone(revenue_growth["annual"]["yoy_value"])
        self.assertEqual(revenue_growth["ttm"]["basis"], "not_applicable")
        self.assertEqual(fcf_margin["annual"]["yoy_value"], 2.5)
        self.assertEqual(fcf_margin["quarter"]["yoy_value"], 5.0)
        self.assertEqual(capex_intensity["annual"]["yoy_value"], 2.0)
        self.assertEqual(capex_intensity["quarter"]["yoy_value"], 4.0)
        # TTM is recomputed from the flow numerator and revenue denominator:
        # (30 + 30 - 18) / (150 + 240 - 120) and (21 + 24 - 12) / same.
        self.assertEqual(fcf_margin["ttm"]["value"], 15.5555555556)
        self.assertEqual(capex_intensity["ttm"]["value"], 12.2222222222)
        self.assertEqual(receivable_gap["quarter"]["value"], 17.8571)
        self.assertEqual(inventory_gap["quarter"]["value"], -5.0)
        self.assertEqual(receivable_gap["ttm"]["reason"], "derived_change_metric")
        self.assertEqual(inventory_gap["ttm"]["reason"], "derived_change_metric")

    def test_cash_profit_ratio_with_nonpositive_profit_suppresses_yoy_but_keeps_calculable_ratio(self):
        reports = [
            {"period": "2024A", "metrics": {"ocf": 10, "ex_net_profit": -5}},
            {"period": "2025A", "metrics": {"ocf": 20, "ex_net_profit": -10}},
        ]

        cells = build_metric_cells(reports, "cash_profit_ratio")

        self.assertEqual(cells["annual"]["value"], -2.0)
        self.assertIsNone(cells["annual"]["yoy_value"])

    def test_build_industry_metric_rows_preserves_member_identity_and_missing_cells(self):
        reports_by_stock = {
            ("sz", "300001"): {"stock_name": "甲", "industry_level_2": "设备", "reports": [{"period": "2025A", "metrics": {"revenue": 10}}]},
            ("sz", "300002"): {"stock_name": "乙", "industry_level_2": "设备", "reports": []},
        }

        rows = build_industry_metric_rows(reports_by_stock, "revenue", current_stock=("sz", "300001"))

        self.assertEqual(rows[0]["market"], "sz")
        self.assertEqual(rows[0]["symbol"], "300001")
        self.assertEqual(rows[0]["stock_name"], "甲")
        self.assertEqual(rows[0]["industry_level_2"], "设备")
        self.assertTrue(rows[0]["is_current_stock"])
        self.assertEqual(rows[0]["metrics"]["annual"]["value"], 10.0)
        self.assertFalse(rows[1]["is_current_stock"])
        self.assertIsNone(rows[1]["metrics"]["annual"]["value"])


if __name__ == "__main__":
    unittest.main()
