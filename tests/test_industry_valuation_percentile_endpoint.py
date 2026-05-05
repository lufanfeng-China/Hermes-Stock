import unittest
from unittest import mock


class IndustryValuationPercentilePayloadTests(unittest.TestCase):
    def test_payload_uses_selected_stock_primary_metric_and_marks_invalid_values_not_comparable(self) -> None:
        from scripts import serve_stock_dashboard as server

        snapshot = {
            "scores": {
                "sh:600519": {
                    "industry_sw_level_1": "食品饮料",
                    "industry_sw_level_2": "酿酒",
                }
            }
        }
        industry_snapshot = {
            "sample_status": "ok",
            "pe_invalid_threshold": 60,
            "member_valuation_rows": [
                {"market": "sh", "symbol": "600519", "stock_name": "贵州茅台", "current_price": 1384.79, "pe_ttm": 20, "ps_ttm": 17},
                {"market": "sz", "symbol": "000858", "stock_name": "五粮液", "current_price": 97.08, "pe_ttm": 10, "ps_ttm": -40},
                {"market": "sh", "symbol": "600199", "stock_name": "金种子酒", "current_price": 7.94, "pe_ttm": -3, "ps_ttm": -324},
                {"market": "sz", "symbol": "002304", "stock_name": "洋河股份", "current_price": 49.23, "pe_ttm": None, "ps_ttm": 5},
            ],
        }

        with mock.patch("app.search.index._load_financial_snapshot", return_value=snapshot), \
            mock.patch("app.search.index._stock_name_lookup", return_value={("sh", "600519"): "贵州茅台"}), \
            mock.patch("app.relative_valuation.data_loader.load_industry_valuation_snapshot", return_value=industry_snapshot), \
            mock.patch("app.relative_valuation.data_loader.load_industry_percentile_sample", return_value=[10, 20, 30]), \
            mock.patch.object(server, "build_relative_valuation_result", return_value={
                "ok": True,
                "stock_name": "贵州茅台",
                "classification": "A_NORMAL_EARNING",
                "sub_classification": None,
                "primary_percentile_metric": "pe_ttm",
                "primary_percentile_value": 20,
                "primary_percentile": 66.6666666667,
                "valuation_band_label": "合理",
            }):
            payload = server._build_industry_valuation_percentile_payload("sh", "600519")

        self.assertTrue(payload["ok"])
        self.assertEqual("pe_ttm", payload["primary_metric"])
        self.assertAlmostEqual(66.6666667, payload["primary_percentile"], places=4)
        self.assertEqual("贵州茅台", payload["stock_name"])

        rows = payload["rows"]
        self.assertEqual(["五粮液", "贵州茅台", "金种子酒", "洋河股份"], [row["stock_name"] for row in rows])
        self.assertEqual("pe_ttm", rows[0]["valuation_metric"])
        self.assertAlmostEqual(33.3333333, rows[0]["valuation_percentile"], places=4)
        self.assertEqual("估值不可比", rows[-1]["valuation_band"])
        self.assertIsNone(rows[-1]["valuation_percentile"])
        self.assertIsNone(rows[2]["pe_ttm"])
        self.assertIsNone(rows[2]["ps_ttm"])
        self.assertIsNone(rows[3]["pe_ttm"])
        self.assertEqual(5, rows[3]["ps_ttm"])

    def test_payload_uses_relative_valuation_primary_metric_when_summary_falls_back_to_ps(self) -> None:
        from scripts import serve_stock_dashboard as server

        snapshot = {
            "scores": {
                "sh:600001": {
                    "industry_sw_level_1": "测试行业",
                    "industry_sw_level_2": "测试二级",
                }
            }
        }
        industry_snapshot = {
            "sample_status": "ok",
            "pe_invalid_threshold": 150,
            "member_valuation_rows": [
                {"market": "sh", "symbol": "600001", "stock_name": "高PE样本", "current_price": 10, "pe_ttm": 260, "ps_ttm": 18},
                {"market": "sh", "symbol": "600002", "stock_name": "低PS样本", "current_price": 8, "pe_ttm": 20, "ps_ttm": 2},
            ],
        }

        with mock.patch("app.search.index._load_financial_snapshot", return_value=snapshot), \
            mock.patch("app.search.index._stock_name_lookup", return_value={("sh", "600001"): "高PE样本"}), \
            mock.patch("app.relative_valuation.data_loader.load_industry_valuation_snapshot", return_value=industry_snapshot), \
            mock.patch("app.relative_valuation.data_loader.load_industry_percentile_sample", return_value=[2, 6, 18]), \
            mock.patch.object(server, "build_relative_valuation_result", return_value={
                "ok": True,
                "stock_name": "高PE样本",
                "classification": "B_THIN_PROFIT_DISTORTED",
                "sub_classification": None,
                "primary_percentile_metric": "ps_ttm",
                "primary_percentile_value": 18,
                "primary_percentile": 100.0,
                "valuation_band_label": "高估区间",
            }):
            payload = server._build_industry_valuation_percentile_payload("sh", "600001")

        self.assertEqual("ps_ttm", payload["primary_metric"])
        self.assertEqual(18, payload["primary_percentile_value"])
        self.assertEqual(100.0, payload["primary_percentile"])
        rows = payload["rows"]
        self.assertEqual("低PS样本", rows[0]["stock_name"])
        self.assertEqual("ps_ttm", rows[0]["valuation_metric"])
        self.assertAlmostEqual(33.3333333, rows[0]["valuation_percentile"], places=4)

    def test_payload_builds_peer_rows_from_live_members_when_snapshot_has_no_member_rows(self) -> None:
        from scripts import serve_stock_dashboard as server

        snapshot = {
            "scores": {
                "sz:002230": {
                    "industry_sw_level_1": "计算机",
                    "industry_sw_level_2": "软件服务",
                }
            }
        }
        industry_snapshot = {
            "sample_status": "ok",
            "pe_invalid_threshold": 80,
            "percentile_samples": {"pe_ttm|A_NORMAL_EARNING": [10, 20, 30]},
        }
        member_inputs = {
            ("sz", "002230"): {"market": "sz", "symbol": "002230", "stock_name": "当前股", "current_price": 11, "pe_ttm": 20, "ps_ttm": 2.0},
            ("sz", "000001"): {"market": "sz", "symbol": "000001", "stock_name": "同业A", "current_price": 8, "pe_ttm": 10, "ps_ttm": 1.0},
            ("sz", "000002"): {"market": "sz", "symbol": "000002", "stock_name": "同业B", "current_price": 9, "pe_ttm": 30, "ps_ttm": 3.0},
        }

        with mock.patch("app.search.index._load_financial_snapshot", return_value=snapshot), \
            mock.patch("app.search.index._stock_name_lookup", return_value={("sz", "002230"): "当前股"}), \
            mock.patch("app.relative_valuation.data_loader.load_industry_valuation_snapshot", return_value=industry_snapshot), \
            mock.patch("app.relative_valuation.data_loader._industry_members", return_value=[
                {"market": "sz", "symbol": "002230"},
                {"market": "sz", "symbol": "000001"},
                {"market": "sz", "symbol": "000002"},
            ]), \
            mock.patch("app.relative_valuation.data_loader.load_stock_relative_valuation_inputs", side_effect=lambda m, s: member_inputs[(m, s)]), \
            mock.patch.object(server, "build_relative_valuation_result", return_value={
                "ok": True,
                "stock_name": "当前股",
                "classification": "A_NORMAL_EARNING",
                "sub_classification": None,
                "primary_percentile_metric": "pe_ttm",
                "primary_percentile_value": 20,
                "primary_percentile": 66.6666666667,
                "valuation_band_label": "合理",
            }):
            payload = server._build_industry_valuation_percentile_payload("sz", "002230")

        self.assertTrue(payload["ok"])
        self.assertEqual(3, len(payload["rows"]))
        self.assertEqual(["同业A", "当前股", "同业B"], [row["stock_name"] for row in payload["rows"]])
        self.assertTrue(any(row["is_current_stock"] for row in payload["rows"]))


if __name__ == "__main__":
    unittest.main()
