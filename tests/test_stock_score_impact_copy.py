import unittest
from unittest import mock


class StockScoreImpactCopyTests(unittest.TestCase):
    def test_insurance_and_formula_metrics_return_triplet_impact_copy(self) -> None:
        from app.search import index as idx

        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:601318": {
                    "report_date": "20260331",
                    "announce_date": "20260429",
                    "latest_period": "2026Q1",
                    "sub_indicators": {sub_key: 50.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_sub_indicators": {sub_key: 45.0 for sub_key, *_ in idx._SUB_DEFS},
                    "ind_dim_scores": {},
                    "ind_total_score": 0.0,
                    "raw_sub_indicators": {
                        "free_cf": 1200000000.0,
                        "goodwill_ratio": 0.27,
                    },
                    "prev_raw_sub_indicators": {
                        "free_cf": 2400000000.0,
                        "goodwill_ratio": 0.32,
                    },
                }
            },
        }
        component_context = {
            "current": {
                "op_cf": 5400000000.0,
                "capex": 4200000000.0,
                "goodwill": 56800000000.0,
                "total_assets": 1580000000000.0,
            },
            "previous": {
                "op_cf": 7600000000.0,
                "capex": 5200000000.0,
                "goodwill": 68500000000.0,
                "total_assets": 1630000000000.0,
            },
        }

        with (
            mock.patch.object(idx, "_load_financial_snapshot", return_value=snapshot),
            mock.patch.object(idx, "_stock_name_lookup", return_value={("sh", "601318"): "中国平安"}),
            mock.patch.object(idx, "_load_industry_map", return_value={("sh", "601318"): ("保险", "非银金融")}),
            mock.patch.object(idx, "_load_sub_indicator_component_context", return_value=component_context),
        ):
            result = idx.compute_stock_score("sh", "601318")

        free_cf_risks = result["sub_indicator_diagnostics"]["free_cf"]["impact"]["impact_risks"]
        goodwill_risks = result["sub_indicator_diagnostics"]["goodwill_ratio"]["impact"]["impact_risks"]
        self.assertIn("主影响", free_cf_risks[0])
        self.assertTrue(any("次影响" in item for item in free_cf_risks))
        self.assertTrue(any("缓冲项" in item for item in free_cf_risks))
        self.assertIn("可支配现金", " ".join(free_cf_risks))
        self.assertIn("主影响", goodwill_risks[0])
        self.assertTrue(any("减值" in item for item in goodwill_risks))


if __name__ == "__main__":
    unittest.main()
