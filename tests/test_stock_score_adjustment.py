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

    def test_compute_stock_score_returns_structured_sub_indicator_diagnostics_for_mvp_metrics(self) -> None:
        from app.search import index as idx

        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:601600": {
                    "report_date": "20260331",
                    "announce_date": "20260424",
                    "latest_period": "2026Q1",
                    "sub_indicators": {sub_key: 50.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_sub_indicators": {sub_key: 40.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_dim_scores": {},
                    "ind_total_score": 0.0,
                    "raw_sub_indicators": {
                        "free_cf": 1200000000.0,
                        "ocf_to_profit": 1.4,
                        "ocf_to_rev": 0.18,
                        "net_margin": 14.3,
                        "ar_days": 32.0,
                        "inv_days": 48.0,
                        "asset_turn": 0.72,
                        "current_ratio": 1.32,
                        "quick_ratio": 0.94,
                        "ar_to_asset": 11.2,
                        "inv_to_asset": 9.5,
                        "goodwill_ratio": 3.6,
                        "impair_to_rev": 0.8,
                        "debt_ratio": 62.0,
                        "revenue_growth": -6.2,
                        "ex_profit_growth": -21.0,
                    },
                    "prev_raw_sub_indicators": {
                        "free_cf": 2400000000.0,
                        "ocf_to_profit": 1.8,
                        "ocf_to_rev": 0.24,
                        "net_margin": 13.1,
                        "ar_days": 28.0,
                        "inv_days": 41.0,
                        "asset_turn": 0.78,
                        "current_ratio": 1.48,
                        "quick_ratio": 1.05,
                        "ar_to_asset": 10.4,
                        "inv_to_asset": 8.1,
                        "goodwill_ratio": 4.2,
                        "impair_to_rev": 1.1,
                        "debt_ratio": 58.0,
                        "revenue_growth": 2.1,
                        "ex_profit_growth": 22.4,
                    },
                }
            },
        }
        component_context = {
            "current": {
                "revenue": 26500000000.0,
                "ex_net_profit": 3200000000.0,
                "op_cf": 5400000000.0,
                "net_profit": 3800000000.0,
                "capex": 4200000000.0,
                "total_debt": 980000000000.0,
                "total_assets": 1580000000000.0,
                "current_assets": 426000000000.0,
                "current_liabilities": 323000000000.0,
                "operating_cost": 19800000000.0,
                "ar": 177000000000.0,
                "inventory": 150000000000.0,
                "goodwill": 56800000000.0,
                "impair_loss": 212000000.0,
            },
            "previous": {
                "revenue": 28200000000.0,
                "ex_net_profit": 4100000000.0,
                "op_cf": 7600000000.0,
                "net_profit": 4200000000.0,
                "capex": 5200000000.0,
                "total_debt": 950000000000.0,
                "total_assets": 1630000000000.0,
                "current_assets": 455000000000.0,
                "current_liabilities": 307000000000.0,
                "operating_cost": 18400000000.0,
                "ar": 169000000000.0,
                "inventory": 132000000000.0,
                "goodwill": 68500000000.0,
                "impair_loss": 310000000.0,
            },
        }

        with (
            mock.patch.object(idx, "_load_financial_snapshot", return_value=snapshot),
            mock.patch.object(idx, "_stock_name_lookup", return_value={("sh", "601600"): "中国铝业"}),
            mock.patch.object(idx, "_load_industry_map", return_value={("sh", "601600"): ("工业金属", "有色")}),
            mock.patch.object(idx, "_load_sub_indicator_component_context", return_value=component_context),
        ):
            result = idx.compute_stock_score("sh", "601600")

        diagnostics = result["sub_indicator_diagnostics"]
        self.assertEqual(set(idx._SUB_KEYS), set(diagnostics.keys()))
        self.assertTrue(all(item.get("indicator_name") for item in diagnostics.values()))
        self.assertEqual("自由现金流", diagnostics["free_cf"]["indicator_name"])
        self.assertEqual("净资产收益率", diagnostics["roe_pct"]["indicator_name"])
        self.assertEqual("营收增速", diagnostics["revenue_growth"]["indicator_name"])
        self.assertEqual("formula_decomposition", diagnostics["free_cf"]["attribution"]["template_type"])
        self.assertEqual("high", diagnostics["free_cf"]["attribution"]["evidence_strength"])
        self.assertFalse(diagnostics["free_cf"]["attribution"]["needs_text_validation"])
        self.assertIn("无需额外文本验证", diagnostics["free_cf"]["attribution"]["validation_sources"])
        self.assertIn("全行业", diagnostics["free_cf"]["attribution"]["industry_scope"])
        self.assertIn("主因", diagnostics["free_cf"]["attribution"]["summary"])
        self.assertIn("次因", diagnostics["free_cf"]["attribution"]["summary"])
        self.assertIn("对冲项", diagnostics["free_cf"]["attribution"]["summary"])
        self.assertIn("经营现金流", diagnostics["free_cf"]["attribution"]["summary"])
        self.assertIn("回落", diagnostics["free_cf"]["attribution"]["summary"])
        self.assertIn("资本开支", diagnostics["free_cf"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["roe_ex"]["attribution"]["template_type"])
        self.assertIn("盈利端", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["net_margin"]["attribution"]["template_type"])
        self.assertIn("每单位营收", diagnostics["net_margin"]["attribution"]["summary"])
        self.assertIn("主因", diagnostics["net_margin"]["attribution"]["summary"])
        self.assertIn("净利润", diagnostics["net_margin"]["attribution"]["summary"])
        self.assertIn("对冲项", diagnostics["net_margin"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["ocf_to_profit"]["attribution"]["template_type"])
        self.assertIn("净利润", diagnostics["ocf_to_profit"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["ocf_to_rev"]["attribution"]["template_type"])
        self.assertIn("主因", diagnostics["ocf_to_rev"]["attribution"]["summary"])
        self.assertIn("经营现金流", diagnostics["ocf_to_rev"]["attribution"]["summary"])
        self.assertIn("营收", diagnostics["ocf_to_rev"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["ar_to_asset"]["attribution"]["template_type"])
        self.assertIn("主因", diagnostics["ar_to_asset"]["attribution"]["summary"])
        self.assertIn("应收账款", diagnostics["ar_to_asset"]["attribution"]["summary"])
        self.assertIn("总资产", diagnostics["ar_to_asset"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["inv_to_asset"]["attribution"]["template_type"])
        self.assertIn("工业金属", diagnostics["inv_to_asset"]["attribution"]["summary"])
        self.assertIn("主因", diagnostics["inv_to_asset"]["attribution"]["summary"])
        self.assertIn("存货", diagnostics["inv_to_asset"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["goodwill_ratio"]["attribution"]["template_type"])
        self.assertIn("主因", diagnostics["goodwill_ratio"]["attribution"]["summary"])
        self.assertIn("商誉", diagnostics["goodwill_ratio"]["attribution"]["summary"])
        self.assertEqual("formula_decomposition", diagnostics["impair_to_rev"]["attribution"]["template_type"])
        self.assertIn("主因", diagnostics["impair_to_rev"]["attribution"]["summary"])
        self.assertIn("减值", diagnostics["impair_to_rev"]["attribution"]["summary"])
        self.assertEqual("efficiency_misalignment", diagnostics["debt_ratio"]["attribution"]["template_type"])
        self.assertTrue(diagnostics["debt_ratio"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["debt_ratio"]["impact"]["impact_risks"][0])
        self.assertEqual("efficiency_misalignment", diagnostics["ar_days"]["attribution"]["template_type"])
        self.assertIn("回款节奏", diagnostics["ar_days"]["attribution"]["summary"])
        self.assertTrue(diagnostics["ar_days"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["ar_days"]["impact"]["impact_risks"][0])
        self.assertEqual("efficiency_misalignment", diagnostics["inv_days"]["attribution"]["template_type"])
        self.assertIn("产销节奏", diagnostics["inv_days"]["attribution"]["summary"])
        self.assertTrue(diagnostics["inv_days"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["inv_days"]["impact"]["impact_risks"][0])
        self.assertEqual("efficiency_misalignment", diagnostics["asset_turn"]["attribution"]["template_type"])
        self.assertTrue(diagnostics["asset_turn"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["asset_turn"]["impact"]["impact_risks"][0])
        self.assertEqual("efficiency_misalignment", diagnostics["current_ratio"]["attribution"]["template_type"])
        self.assertTrue(diagnostics["current_ratio"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["current_ratio"]["impact"]["impact_risks"][0])
        self.assertEqual("efficiency_misalignment", diagnostics["quick_ratio"]["attribution"]["template_type"])
        self.assertTrue(diagnostics["quick_ratio"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["quick_ratio"]["impact"]["impact_risks"][0])
        self.assertEqual("period_compare", diagnostics["revenue_growth"]["attribution"]["template_type"])
        self.assertEqual("medium", diagnostics["revenue_growth"]["attribution"]["evidence_strength"])
        self.assertTrue(diagnostics["revenue_growth"]["attribution"]["needs_text_validation"])
        self.assertIn("公告正文", diagnostics["revenue_growth"]["attribution"]["validation_sources"])
        self.assertIn("工业金属", diagnostics["inv_to_asset"]["attribution"]["industry_scope"])
        self.assertIn("收入动能", diagnostics["revenue_growth"]["attribution"]["summary"])
        self.assertEqual("period_compare", diagnostics["profit_growth"]["attribution"]["template_type"])
        self.assertIn("利润释放", diagnostics["profit_growth"]["attribution"]["summary"])
        self.assertEqual("period_compare", diagnostics["ex_profit_growth"]["attribution"]["template_type"])
        self.assertIn("核心经营", diagnostics["ex_profit_growth"]["attribution"]["summary"])
        self.assertEqual("direct_field_signal", diagnostics["roe_pct"]["attribution"]["template_type"])
        self.assertTrue(diagnostics["free_cf"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["free_cf"]["impact"]["impact_risks"][0])
        self.assertTrue(any("次影响" in item for item in diagnostics["free_cf"]["impact"]["impact_risks"]))
        self.assertTrue(any("缓冲项" in item for item in diagnostics["free_cf"]["impact"]["impact_risks"]))
        self.assertTrue(diagnostics["revenue_growth"]["impact"]["impact_risks"])
        self.assertTrue(diagnostics["net_margin"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["net_margin"]["impact"]["impact_risks"][0])
        self.assertTrue(diagnostics["ocf_to_rev"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["ocf_to_rev"]["impact"]["impact_risks"][0])
        self.assertTrue(diagnostics["ar_to_asset"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["ar_to_asset"]["impact"]["impact_risks"][0])
        self.assertTrue(diagnostics["inv_to_asset"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["inv_to_asset"]["impact"]["impact_risks"][0])
        self.assertTrue(diagnostics["goodwill_ratio"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["goodwill_ratio"]["impact"]["impact_risks"][0])
        self.assertTrue(diagnostics["impair_to_rev"]["impact"]["impact_risks"])
        self.assertIn("主影响", diagnostics["impair_to_rev"]["impact"]["impact_risks"][0])
        self.assertEqual("idle", diagnostics["free_cf"]["explanation"]["status"])
        self.assertEqual("idle", diagnostics["roe_pct"]["explanation"]["status"])


if __name__ == "__main__":
    unittest.main()
