import unittest
from unittest import mock


class StockScoreDiagnosticCopyTests(unittest.TestCase):
    def test_financial_industry_diagnostics_use_sector_specific_copy(self) -> None:
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
                        "roe_ex": 2.35,
                        "quick_ratio": None,
                        "current_ratio": None,
                        "roe_pct": 9.2,
                    },
                    "prev_raw_sub_indicators": {
                        "roe_ex": 14.37,
                        "quick_ratio": None,
                        "current_ratio": None,
                        "roe_pct": 15.8,
                    },
                }
            },
        }
        component_context = {
            "current": {
                "ex_net_profit": 3000000000.0,
                "equity": 128000000000.0,
            },
            "previous": {
                "ex_net_profit": 11200000000.0,
                "equity": 78000000000.0,
            },
        }

        with (
            mock.patch.object(idx, "_load_financial_snapshot", return_value=snapshot),
            mock.patch.object(idx, "_stock_name_lookup", return_value={("sh", "601318"): "中国平安"}),
            mock.patch.object(idx, "_load_industry_map", return_value={("sh", "601318"): ("保险", "非银金融")}),
            mock.patch.object(idx, "_load_sub_indicator_component_context", return_value=component_context),
        ):
            result = idx.compute_stock_score("sh", "601318")

        diagnostics = result["sub_indicator_diagnostics"]
        self.assertIn("保险", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("承保", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("投资收益", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("主因", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("次因", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("对冲项", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("扣非利润", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("归母权益", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("回落", diagnostics["roe_ex"]["attribution"]["summary"])
        self.assertIn("保险", diagnostics["quick_ratio"]["attribution"]["summary"])
        self.assertIn("补充观察", diagnostics["quick_ratio"]["attribution"]["summary"])
        self.assertIn("净资产收益率", diagnostics["roe_pct"]["attribution"]["summary"])
        self.assertIn("投资收益", diagnostics["roe_pct"]["attribution"]["summary"])


if __name__ == "__main__":
    unittest.main()
