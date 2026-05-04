import unittest
from unittest import mock


class RelativeValuationServiceTests(unittest.TestCase):
    def test_build_relative_valuation_result_uses_pe_percentile_for_a_class(self) -> None:
        from app.relative_valuation import service

        stock_inputs = {
            "market": "sz",
            "symbol": "000333",
            "stock_name": "美的集团",
            "industry_level_1_name": "家电",
            "industry_level_2_name": "白色家电",
            "listed_days": 1500,
            "current_price": 81.1,
            "free_float_market_cap": 5560.0,
            "ttm_net_profit": 380.0,
            "ttm_revenue": 4100.0,
            "revenue_yoy": 0.09,
            "gross_margin": 0.25,
            "book_value_per_share": 21.5,
            "pe_ttm": 24.0,
            "ps_ttm": 1.35,
        }
        industry_snapshot = {
            "industry_level_1_name": "家电",
            "industry_level_2_name": "白色家电",
            "valid_member_count": 18,
            "sample_status": "ok",
            "weighted_pe_ttm": 18.5,
            "weighted_ps_ttm": 1.92,
            "pe_invalid_threshold": 92.5,
            "temperature_percentile_since_2022": 72.0,
            "temperature_label": "行业偏热",
        }

        with (
            mock.patch.object(service, "load_stock_relative_valuation_inputs", return_value=stock_inputs),
            mock.patch.object(service, "load_industry_valuation_snapshot", return_value=industry_snapshot),
            mock.patch.object(service, "load_industry_percentile_sample", return_value=[12.0, 18.0, 24.0, 36.0]),
            mock.patch.object(service, "load_industry_temperature_history", return_value=[
                {"trading_day": "2022-03-31", "weighted_pe_ttm": 12.0},
                {"trading_day": "2022-12-31", "weighted_pe_ttm": 18.0},
            ]),
        ):
            result = service.build_relative_valuation_result("sz", "000333")

        self.assertTrue(result["ok"])
        self.assertEqual("A_NORMAL_EARNING", result["classification"])
        self.assertEqual("pe_ttm", result["primary_percentile_metric"])
        self.assertAlmostEqual(75.0, result["primary_percentile"], places=6)
        self.assertEqual("合理偏高", result["valuation_band_label"])
        self.assertEqual("行业偏热", result["industry_temperature_label"])
        self.assertEqual(18, result["industry_valid_member_count"])
        self.assertEqual(
            [
                {"trading_day": "2022-03-31", "weighted_pe_ttm": 12.0},
                {"trading_day": "2022-12-31", "weighted_pe_ttm": 18.0},
            ],
            result["industry_temperature_history"],
        )

    def test_build_relative_valuation_result_falls_back_to_ps_percentile_for_b_class(self) -> None:
        from app.relative_valuation import service

        stock_inputs = {
            "market": "sh",
            "symbol": "688111",
            "stock_name": "金山办公",
            "industry_level_1_name": "计算机",
            "industry_level_2_name": "软件服务",
            "listed_days": 900,
            "current_price": 210.0,
            "free_float_market_cap": 900.0,
            "ttm_net_profit": 3.0,
            "ttm_revenue": 50.0,
            "revenue_yoy": 0.15,
            "gross_margin": 0.82,
            "book_value_per_share": 9.5,
            "pe_ttm": 260.0,
            "ps_ttm": 18.0,
        }
        industry_snapshot = {
            "industry_level_1_name": "计算机",
            "industry_level_2_name": "软件服务",
            "valid_member_count": 24,
            "sample_status": "ok",
            "weighted_pe_ttm": 30.0,
            "weighted_ps_ttm": 5.0,
            "pe_invalid_threshold": 150.0,
            "temperature_percentile_since_2022": 81.0,
            "temperature_label": "行业过热",
        }

        with (
            mock.patch.object(service, "load_stock_relative_valuation_inputs", return_value=stock_inputs),
            mock.patch.object(service, "load_industry_valuation_snapshot", return_value=industry_snapshot),
            mock.patch.object(service, "load_industry_percentile_sample", return_value=[6.0, 10.0, 18.0, 24.0]),
        ):
            result = service.build_relative_valuation_result("sh", "688111")

        self.assertEqual("B_THIN_PROFIT_DISTORTED", result["classification"])
        self.assertEqual("ps_ttm", result["primary_percentile_metric"])
        self.assertAlmostEqual(75.0, result["primary_percentile"], places=6)
        self.assertIn("PE invalid, fallback to PS percentile", result["notes"])
        self.assertIn("行业环境偏热/过热", result["risk_flags"])

    def test_build_relative_valuation_result_degrades_when_industry_sample_is_insufficient(self) -> None:
        from app.relative_valuation import service

        stock_inputs = {
            "market": "sz",
            "symbol": "301234",
            "stock_name": "测试样本",
            "industry_level_1_name": "电子",
            "industry_level_2_name": "光学光电",
            "listed_days": 500,
            "current_price": 22.0,
            "free_float_market_cap": 120.0,
            "ttm_net_profit": 8.0,
            "ttm_revenue": 60.0,
            "revenue_yoy": 0.12,
            "gross_margin": 0.22,
            "book_value_per_share": 3.2,
            "pe_ttm": 28.0,
            "ps_ttm": 2.4,
        }
        industry_snapshot = {
            "industry_level_1_name": "电子",
            "industry_level_2_name": "光学光电",
            "valid_member_count": 8,
            "sample_status": "insufficient",
            "weighted_pe_ttm": 16.0,
            "weighted_ps_ttm": 2.0,
            "pe_invalid_threshold": 80.0,
            "temperature_percentile_since_2022": None,
            "temperature_label": None,
        }

        with (
            mock.patch.object(service, "load_stock_relative_valuation_inputs", return_value=stock_inputs),
            mock.patch.object(service, "load_industry_valuation_snapshot", return_value=industry_snapshot),
            mock.patch.object(service, "load_industry_percentile_sample", return_value=[12.0, 18.0, 24.0]),
        ):
            result = service.build_relative_valuation_result("sz", "301234")

        self.assertEqual("insufficient", result["sample_status"])
        self.assertIsNone(result["primary_percentile"])
        self.assertEqual("样本不足", result["valuation_band_label"])

    def test_build_relative_valuation_result_returns_error_for_unknown_symbol(self) -> None:
        from app.relative_valuation import service

        with mock.patch.object(service, "load_stock_relative_valuation_inputs", return_value=None):
            result = service.build_relative_valuation_result("sz", "000000")

        self.assertFalse(result["ok"])
        self.assertEqual("stock_not_found", result["error"])

    def test_build_relative_valuation_result_uses_embedded_snapshot_history_without_recompute(self) -> None:
        from app.relative_valuation import service

        stock_inputs = {
            "market": "sh",
            "symbol": "601600",
            "stock_name": "中国铝业",
            "industry_level_1_name": "有色金属",
            "industry_level_2_name": "工业金属",
            "listed_days": 2000,
            "current_price": 7.2,
            "free_float_market_cap": 980.0,
            "ttm_net_profit": 88.0,
            "ttm_revenue": 2200.0,
            "revenue_yoy": 0.05,
            "gross_margin": 0.11,
            "book_value_per_share": 5.2,
            "pe_ttm": 13.6,
            "ps_ttm": 0.45,
        }
        industry_snapshot = {
            "industry_level_1_name": "有色金属",
            "industry_level_2_name": "工业金属",
            "valid_member_count": 30,
            "sample_status": "ok",
            "weighted_pe_ttm": 8.3,
            "weighted_ps_ttm": 1.1,
            "pe_invalid_threshold": 50.0,
            "temperature_percentile_since_2022": 70.0,
            "temperature_label": "行业偏热",
            "temperature_history_since_2022": [
                {"trading_day": "2025-12-31", "weighted_pe_ttm": 7.8},
                {"trading_day": "2026-04-30", "weighted_pe_ttm": 8.3},
            ],
        }

        with (
            mock.patch.object(service, "load_stock_relative_valuation_inputs", return_value=stock_inputs),
            mock.patch.object(service, "load_industry_valuation_snapshot", return_value=industry_snapshot),
            mock.patch.object(service, "load_industry_percentile_sample", return_value=[8.0, 10.0, 13.6, 20.0]),
            mock.patch.object(service, "load_industry_temperature_history", side_effect=AssertionError("should not recompute history")),
        ):
            result = service.build_relative_valuation_result("sh", "601600")

        self.assertEqual(industry_snapshot["temperature_history_since_2022"], result["industry_temperature_history"])


class RelativeValuationApiContractTests(unittest.TestCase):
    def test_dashboard_script_registers_relative_valuation_route_and_handler(self) -> None:
        from pathlib import Path

        script = (Path(__file__).resolve().parents[1] / "scripts" / "serve_stock_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('if parsed.path == "/api/relative-valuation":', script)
        self.assertIn('self.handle_relative_valuation(parsed.query)', script)
        self.assertIn('def handle_relative_valuation(self, query: str) -> None:', script)
