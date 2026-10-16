import unittest


class StrictFinancialSnapshotContractTest(unittest.TestCase):
    def test_strict_record_keeps_annual_and_quarterly_health_separate(self):
        from app.stock_filter_snapshot import build_strict_financial_record

        # Complete annuals plus a common Q2 TTM basis. Values are deliberately
        # homogeneous; this test asserts contract separation, not score level.
        reports = []
        for year in range(2021, 2026):
            reports.append({"period": f"{year}A", "report_date": f"{year}1231", "metrics": {
                "revenue": 100.0 + (year - 2021) * 15, "ex_net_profit": 10.0 + (year - 2021),
                "gross_margin": 30.0, "net_margin": 10.0, "roe_ex": 12.0,
                "ocf": 14.0, "free_cf": 8.0, "capex": 6.0, "debt_ratio": 45.0,
                "accounts_receivable": 20.0, "inventory": 10.0, "goodwill": 2.0,
                "equity": 80.0, "total_assets": 150.0,
            }})
        reports.extend([
            {"period": "2025Q2", "report_date": "20250630", "metrics": {"revenue": 55.0, "ex_net_profit": 6.0, "gross_margin": 30.0, "net_margin": 10.0, "ocf": 7.0, "capex": 3.0, "debt_ratio": 45.0, "accounts_receivable": 12.0, "inventory": 6.0, "goodwill": 2.0, "equity": 80.0, "total_assets": 150.0}},
            {"period": "2026Q2", "report_date": "20260630", "metrics": {"revenue": 65.0, "ex_net_profit": 7.0, "gross_margin": 31.0, "net_margin": 11.0, "ocf": 8.0, "capex": 3.0, "debt_ratio": 44.0, "accounts_receivable": 13.0, "inventory": 6.0, "goodwill": 2.0, "equity": 85.0, "total_assets": 155.0}},
        ])
        record = build_strict_financial_record(reports, industry_level_1="电子", annual_anchor="2025A", quarterly_anchor="2026Q2")
        self.assertEqual(record["annual"]["periods"], ["2021A", "2022A", "2023A", "2024A", "2025A"])
        self.assertEqual(record["annual"]["assessment_track"], "five_year")
        self.assertIn("growth_quality", record["annual"]["dimensions"])
        self.assertIn("revenue_cagr", record["annual"]["derived"])
        self.assertEqual(record["quarterly"]["anchor_period"], "2026Q2")
        self.assertIn("growth", record["quarterly"]["dimensions"])
        self.assertNotEqual(set(record["annual"]["dimensions"]), set(record["quarterly"]["dimensions"]))
        quality = record["quarterly"]["quality"]
        self.assertGreater(quality["revenue_yoy"], 0)
        self.assertGreater(quality["ex_net_profit_yoy"], 0)
        self.assertGreaterEqual(quality["ttm_fcf_margin"], 0)
        self.assertEqual(quality["profitability_status"], "stable")
        self.assertFalse(quality["has_high_or_critical_alert"])
        self.assertEqual(record["quarterly"]["triggered_red_flag_count"], 0)
        self.assertEqual(record["composite"]["mode"], "blended")
        self.assertIsNotNone(record["composite"]["score"])


if __name__ == "__main__":
    unittest.main()
