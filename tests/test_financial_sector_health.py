import importlib
import importlib.util
import unittest


class FinancialSectorHealthScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = importlib.util.find_spec("app.financial.sector_health")
        self.assertIsNotNone(spec, "银行/证券专用评分模块尚未实现")
        self.module = importlib.import_module("app.financial.sector_health")

    def test_bank_full_evidence_can_score_100_and_is_bank_only_comparable(self) -> None:
        result = self.module.score_bank_health({
            "npl_ratio": 0.8,
            "provision_coverage_ratio": 320.0,
            "npl_yoy_change_pp": -0.1,
            "provision_yoy_change_pp": 5.0,
            "cet1_ratio": 12.5,
            "tier1_ratio": 13.5,
            "capital_adequacy_ratio": 15.5,
            "roe": 13.0,
            "roa": 1.1,
            "net_interest_margin": 2.3,
            "cost_income_ratio": 27.0,
            "liquidity_coverage_ratio": 155.0,
            "net_stable_funding_ratio": 125.0,
            "revenue_path": "continuous_growth",
            "profit_path": "profitable_growth",
            "credit_impairment_revenue_pct": 8.0,
            "risk_reserve_status": "high_stable",
        })
        self.assertEqual(100.0, result["score"])
        self.assertEqual(100.0, result["coverage_weight"])
        self.assertEqual("bank", result["model_type"])
        self.assertEqual("bank-health-v1", result["score_version"])
        self.assertEqual("within_bank_only", result["score_comparability"])
        self.assertEqual([], result["red_flags"])

    def test_bank_missing_asset_quality_core_withholds_composite(self) -> None:
        result = self.module.score_bank_health({
            "provision_coverage_ratio": 250.0,
            "cet1_ratio": 11.0,
            "tier1_ratio": 12.0,
            "capital_adequacy_ratio": 14.0,
            "roe": 10.0,
            "roa": 0.8,
            "net_interest_margin": 1.8,
            "cost_income_ratio": 33.0,
            "liquidity_coverage_ratio": 130.0,
            "net_stable_funding_ratio": 115.0,
            "revenue_path": "overall_growth",
            "profit_path": "profitable_volatile",
            "credit_impairment_revenue_pct": 15.0,
            "risk_reserve_status": "stable",
        })
        self.assertIsNone(result["score"])
        self.assertEqual("insufficient_evidence", result["status"])
        self.assertIn("asset_quality", result["unavailable_core_families"])

    def test_securities_full_evidence_scores_and_is_securities_only_comparable(self) -> None:
        result = self.module.score_securities_health({
            "risk_coverage_ratio": 210.0,
            "capital_leverage_ratio": 16.0,
            "net_capital_to_net_assets_pct": 72.0,
            "business_line_coverage": "complete",
            "largest_business_share_pct": 45.0,
            "fee_income_trend": "growth",
            "proprietary_income_revenue_pct": 18.0,
            "trading_assets_to_equity_pct": 90.0,
            "proprietary_volatility": "low",
            "roe": 13.0,
            "profit_path": "profitable_growth",
            "liquidity_coverage_ratio": 155.0,
            "net_stable_funding_ratio": 125.0,
            "credit_impairment_revenue_pct": 4.0,
            "margin_financing_risk": "stable",
        })
        self.assertEqual(100.0, result["score"])
        self.assertEqual("securities", result["model_type"])
        self.assertEqual("securities-health-v1", result["score_version"])
        self.assertEqual("within_securities_only", result["score_comparability"])

    def test_securities_missing_regulatory_capital_withholds_composite(self) -> None:
        result = self.module.score_securities_health({
            "roe": 12.0,
            "profit_path": "profitable_growth",
            "liquidity_coverage_ratio": 150.0,
            "net_stable_funding_ratio": 120.0,
        })
        self.assertIsNone(result["score"])
        self.assertEqual("insufficient_evidence", result["status"])
        self.assertIn("capital_and_risk_coverage", result["unavailable_core_families"])
    def test_bank_quarterly_monitor_uses_latest_period_and_withholds_on_missing_core(self) -> None:
        ready = self.module.score_bank_quarterly_monitor({
            "npl_ratio": 0.8, "provision_coverage_ratio": 320.0,
            "cet1_ratio": 12.5, "tier1_ratio": 13.5, "capital_adequacy_ratio": 15.5,
            "net_interest_margin": 2.3, "cost_income_ratio": 27.0,
            "liquidity_coverage_ratio": 155.0, "net_stable_funding_ratio": 125.0,
            "credit_impairment_revenue_pct": 5.0,
        }, report_period="2026Q3", previous_score=92.0)
        self.assertEqual(100.0, ready["score"])
        self.assertEqual("improving", ready["status"])
        self.assertEqual("2026Q3", ready["report_period"])
        self.assertEqual("bank-quarterly-v1", ready["score_version"])

        missing = self.module.score_bank_quarterly_monitor({
            "cet1_ratio": 12.0, "capital_adequacy_ratio": 15.0,
        }, report_period="2026Q3")
        self.assertIsNone(missing["score"])
        self.assertEqual("insufficient_evidence", missing["status"])

    def test_bank_quarterly_monitor_exposes_yoy_and_year_start_comparisons(self) -> None:
        current = {
            "npl_ratio": 1.0, "provision_coverage_ratio": 250.0,
            "cet1_ratio": 11.0, "tier1_ratio": 12.0, "capital_adequacy_ratio": 14.0,
            "net_interest_margin": 1.8, "cost_income_ratio": 32.0,
            "liquidity_coverage_ratio": 130.0, "net_stable_funding_ratio": 115.0,
            "credit_impairment_revenue_pct": 5.0,
        }
        previous = {"npl_ratio": 1.2, "net_interest_margin": 2.0, "cost_income_ratio": 31.0,
                    "credit_impairment_revenue_pct": 8.0}
        year_start = {"npl_ratio": 1.1, "net_interest_margin": 9.9}
        result = self.module.score_bank_quarterly_monitor(
            current, report_period="2026Q3", previous_metrics=previous, year_start_metrics=year_start,
        )
        self.assertEqual("year_start_and_yoy", result["comparisons"]["npl_ratio"]["basis"])
        self.assertEqual("improving", result["comparisons"]["npl_ratio"]["status"])
        self.assertEqual("yoy_same_period", result["comparisons"]["net_interest_margin"]["basis"])
        self.assertIsNone(result["comparisons"]["net_interest_margin"]["year_start"])
        self.assertEqual("stale_reference", result["comparisons"]["liquidity_coverage_ratio"]["reference_status"])
        self.assertEqual("yoy_same_period", result["comparisons"]["credit_impairment_revenue_pct"]["basis"])
        self.assertEqual("improving", result["comparisons"]["credit_impairment_revenue_pct"]["status"])

    def test_securities_quarterly_monitor_scores_regulatory_buffer(self) -> None:
        ready = self.module.score_securities_quarterly_monitor({
            "risk_coverage_ratio": 210.0, "capital_leverage_ratio": 16.0,
            "net_capital_to_net_assets_pct": 72.0,
            "liquidity_coverage_ratio": 155.0, "net_stable_funding_ratio": 125.0,
            "margin_financing_risk": "stable",
            "proprietary_income_revenue_pct": 10.0,
            "margin_financing_balance": 100.0,
            "credit_impairment_revenue_pct": 2.0,
        }, report_period="2026Q3", previous_score=100.0)
        self.assertEqual(100.0, ready["score"])
        self.assertEqual("stable", ready["status"])
        self.assertEqual("securities-quarterly-v1", ready["score_version"])

    def test_securities_quarterly_monitor_compares_flow_and_period_end_metrics(self) -> None:
        current = {
            "risk_coverage_ratio": 210.0, "capital_leverage_ratio": 16.0,
            "net_capital_to_net_assets_pct": 72.0,
            "liquidity_coverage_ratio": 155.0, "net_stable_funding_ratio": 125.0,
            "proprietary_income_revenue_pct": 10.0, "margin_financing_balance": 100.0,
            "credit_impairment_revenue_pct": 2.0, "margin_financing_risk": "stable",
        }
        previous = {
            "proprietary_income_revenue_pct": 20.0, "margin_financing_balance": 120.0,
            "credit_impairment_revenue_pct": 4.0,
        }
        year_start = {"margin_financing_balance": 110.0}
        result = self.module.score_securities_quarterly_monitor(
            current, report_period="2026Q3", previous_metrics=previous,
            year_start_metrics=year_start,
        )
        self.assertEqual("yoy_same_period", result["comparisons"]["proprietary_income_revenue_pct"]["basis"])
        self.assertEqual("year_start_and_yoy", result["comparisons"]["margin_financing_balance"]["basis"])
        self.assertEqual("yoy_same_period", result["comparisons"]["credit_impairment_revenue_pct"]["basis"])
        self.assertEqual("stale_reference", result["comparisons"]["risk_coverage_ratio"]["status"])

    def test_snapshot_builder_wires_quarterly_financial_statement_inputs(self) -> None:
        builder = importlib.import_module("scripts.build_financial_sector_health_snapshot")
        evidence = {"metrics": {
            "margin_financing_balance": {"value": 100.0, "quality": 100},
        }}
        row = {
            "其中：营业收入": 1000.0,
            "信用减值损失(万元)": 0.001,
            "投资收益": 80.0,
            "加：公允价值变动净收益": 20.0,
        }
        bank = builder._quarterly_bank_metrics(evidence, row)
        securities = builder._quarterly_securities_metrics(evidence, row, None, None)
        self.assertEqual(1.0, bank["credit_impairment_revenue_pct"])
        self.assertEqual(10.0, securities["proprietary_income_revenue_pct"])
        self.assertEqual(100.0, securities["margin_financing_balance"])
        self.assertEqual(1.0, securities["credit_impairment_revenue_pct"])


if __name__ == "__main__":
    unittest.main()
