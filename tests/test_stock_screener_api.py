import unittest
from unittest import mock


class StockScreenerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.search import index

        for loader_name in (
            "load_industry_valuation_rows",
            "load_stock_screener_strategy_rows",
            "load_rps_rows",
            "load_security_rows",
            "load_industry_rows",
        ):
            loader = getattr(index, loader_name, None)
            if hasattr(loader, "cache_clear"):
                loader.cache_clear()

    def test_build_stock_screener_response_filters_scores_valuation_rps_and_paginates(self) -> None:
        from app.search import index

        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:600001": {
                    "industry_sw_level_1": "电子",
                    "industry_sw_level_2": "半导体",
                    "total_score": 88.2,
                    "ind_total_score": 91.1,
                    "market_total_rank": 12,
                    "market_total_universe_size": 5000,
                    "industry_total_rank": 2,
                    "industry_total_universe_size": 120,
                    "dim_scores": {"profitability": 23.0, "growth": 17.0},
                    "ind_dim_scores": {"profitability": 24.0, "growth": 18.0},
                    "sub_indicators": {"roe_ex": 86.0, "profit_growth": 77.0},
                    "ind_sub_indicators": {"roe_ex": 92.0},
                },
                "sz:000001": {
                    "industry_sw_level_1": "银行",
                    "industry_sw_level_2": "全国性银行",
                    "total_score": 64.0,
                    "ind_total_score": 52.0,
                    "market_total_rank": 2400,
                    "market_total_universe_size": 5000,
                    "industry_total_rank": 11,
                    "industry_total_universe_size": 20,
                    "dim_scores": {"profitability": 20.0, "growth": 10.0},
                    "ind_dim_scores": {"profitability": 21.0, "growth": 11.0},
                    "sub_indicators": {"roe_ex": 70.0, "profit_growth": 53.0},
                    "ind_sub_indicators": {"roe_ex": 86.0},
                },
            },
        }
        securities = [
            {"market": "sh", "symbol": "600001", "stock_name": "测试半导体"},
            {"market": "sz", "symbol": "000001", "stock_name": "平安银行"},
        ]
        rps_rows = [
            {"market": "sh", "symbol": "600001", "rps_20": 92.0, "rps_50": 88.0, "rps_120": 81.0, "rps_250": 76.0},
            {"market": "sz", "symbol": "000001", "rps_20": 60.0, "rps_50": 58.0, "rps_120": 55.0, "rps_250": 50.0},
        ]
        valuation_rows = [
            {
                "industry_level_2_name": "半导体",
                "industry_temperature_percentile_since_2022": 72.5,
                "industry_temperature_label": "行业偏热",
                "member_valuation_rows": [
                    {
                        "market": "sh",
                        "symbol": "600001",
                        "current_price": 42.1,
                        "classification": "A_NORMAL_EARNING",
                        "valuation_band_label": "合理偏低",
                        "primary_percentile": 35.0,
                    }
                ],
            },
            {
                "industry_level_2_name": "全国性银行",
                "industry_temperature_percentile_since_2022": 20.0,
                "industry_temperature_label": "行业偏冷",
                "member_valuation_rows": [
                    {
                        "market": "sz",
                        "symbol": "000001",
                        "current_price": 11.5,
                        "classification": "A_NORMAL_EARNING",
                        "valuation_band_label": "合理",
                        "primary_percentile": 48.0,
                    }
                ],
            },
        ]

        with mock.patch.object(index, "_load_financial_snapshot", return_value=snapshot), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_rps_rows", return_value=rps_rows), \
             mock.patch.object(index, "load_industry_rows", return_value=[]), \
             mock.patch.object(index, "_load_json_rows", return_value=valuation_rows):
            payload = index.build_stock_screener_response(
                {
                    "min_total_score": "80",
                    "industry_level_1": "电子",
                    "industry_temperature_label": "行业偏热",
                    "classification": "A_NORMAL_EARNING",
                    "valuation_band": "合理偏低",
                    "min_primary_percentile": "20",
                    "max_primary_percentile": "50",
                    "min_dim_profitability": "20",
                    "min_sub_roe_ex": "80",
                    "min_rps_20": "90",
                    "page": "1",
                    "page_size": "50",
                }
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(1, payload["total"])
        self.assertEqual(1, payload["page"])
        self.assertEqual(50, payload["page_size"])
        self.assertEqual("600001", payload["rows"][0]["symbol"])
        self.assertEqual("测试半导体", payload["rows"][0]["stock_name"])
        self.assertEqual(42.1, payload["rows"][0]["current_price"])
        self.assertEqual("正常盈利", payload["rows"][0]["classification_label"])
        self.assertEqual("合理偏低", payload["rows"][0]["valuation_band_label"])
        self.assertEqual("半导体", payload["rows"][0]["industry_level_2"])

    def test_build_stock_screener_response_filters_multiple_industry_temperature_labels(self) -> None:
        from app.search import index

        snapshot = {
            "scores": {
                "sh:600001": {"total_score": 88.0, "ind_total_score": 80.0, "dim_scores": {"operating": 1.0}, "sub_indicators": {}},
                "sh:600002": {"total_score": 82.0, "ind_total_score": 78.0, "dim_scores": {"operating": 99.0}, "sub_indicators": {}},
                "sz:000001": {"total_score": 70.0, "ind_total_score": 60.0, "dim_scores": {"operating": 99.0}, "sub_indicators": {}},
            }
        }
        securities = [
            {"market": "sh", "symbol": "600001", "stock_name": "偏热股票"},
            {"market": "sh", "symbol": "600002", "stock_name": "温和股票"},
            {"market": "sz", "symbol": "000001", "stock_name": "偏冷股票"},
        ]
        valuation_rows = [
            {"industry_level_2_name": "半导体", "temperature_label": "行业偏热", "member_valuation_rows": [{"market": "sh", "symbol": "600001"}]},
            {"industry_level_2_name": "软件服务", "temperature_label": "行业温和", "member_valuation_rows": [{"market": "sh", "symbol": "600002"}]},
            {"industry_level_2_name": "银行", "temperature_label": "行业偏冷", "member_valuation_rows": [{"market": "sz", "symbol": "000001"}]},
        ]

        with mock.patch.object(index, "_load_financial_snapshot", return_value=snapshot), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_rps_rows", return_value=[]), \
             mock.patch.object(index, "load_industry_rows", return_value=[]), \
             mock.patch.object(index, "_load_json_rows", return_value=valuation_rows):
            payload = index.build_stock_screener_response({
                "industry_temperature_label": "行业偏热,行业偏冷",
                "min_dim_operating": "90",
                "page": "1",
                "page_size": "50",
            })

        self.assertEqual(2, payload["total"])
        self.assertEqual(["600001", "000001"], [row["symbol"] for row in payload["rows"]])

    def test_build_stock_screener_response_computes_missing_score_ranks_and_carries_valuation_fields(self) -> None:
        from app.search import index

        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:600001": {
                    "industry_sw_level_1": "电子",
                    "industry_sw_level_2": "半导体",
                    "total_score": 88.2,
                    "ind_total_score": 91.1,
                    "dim_scores": {},
                    "ind_dim_scores": {},
                    "sub_indicators": {},
                    "ind_sub_indicators": {},
                },
                "sh:600002": {
                    "industry_sw_level_1": "电子",
                    "industry_sw_level_2": "半导体",
                    "total_score": 80.0,
                    "ind_total_score": 92.0,
                    "dim_scores": {},
                    "ind_dim_scores": {},
                    "sub_indicators": {},
                    "ind_sub_indicators": {},
                },
                "sz:000001": {
                    "industry_sw_level_1": "银行",
                    "industry_sw_level_2": "全国性银行",
                    "total_score": 70.0,
                    "ind_total_score": 68.0,
                    "dim_scores": {},
                    "ind_dim_scores": {},
                    "sub_indicators": {},
                    "ind_sub_indicators": {},
                },
            },
        }
        securities = [
            {"market": "sh", "symbol": "600001", "stock_name": "测试半导体A"},
            {"market": "sh", "symbol": "600002", "stock_name": "测试半导体B"},
            {"market": "sz", "symbol": "000001", "stock_name": "平安银行"},
        ]
        valuation_rows = [
            {
                "industry_level_1_name": "电子",
                "industry_level_2_name": "半导体",
                "temperature_percentile_since_2022": 72.5,
                "temperature_label": "行业偏热",
                "member_valuation_rows": [
                    {
                        "market": "sh",
                        "symbol": "600001",
                        "current_price": 42.1,
                        "pe_ttm": 18.6,
                        "ps_ttm": 3.2,
                        "total_market_cap": 420.5,
                        "free_float_market_cap": 210.25,
                        "classification": "A_NORMAL_EARNING",
                        "sub_classification": None,
                        "primary_metric": "pe_ttm",
                        "primary_percentile": 35.0,
                        "valuation_band_label": "合理偏低",
                    },
                    {
                        "market": "sh",
                        "symbol": "600002",
                        "current_price": 30.0,
                        "pe_ttm": 25.0,
                        "ps_ttm": 4.5,
                        "total_market_cap": 300.0,
                        "free_float_market_cap": 160.0,
                        "classification": "A_NORMAL_EARNING",
                        "primary_metric": "pe_ttm",
                        "primary_percentile": 65.0,
                        "valuation_band_label": "合理偏高",
                    },
                ],
            },
            {
                "industry_level_1_name": "银行",
                "industry_level_2_name": "全国性银行",
                "temperature_percentile_since_2022": 20.0,
                "temperature_label": "行业偏冷",
                "member_valuation_rows": [
                    {"market": "sz", "symbol": "000001", "current_price": 11.5, "classification": "A_NORMAL_EARNING"}
                ],
            },
        ]

        with mock.patch.object(index, "_load_financial_snapshot", return_value=snapshot), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_rps_rows", return_value=[]), \
             mock.patch.object(index, "load_industry_rows", return_value=[]), \
             mock.patch.object(index, "_load_json_rows", return_value=valuation_rows):
            payload = index.build_stock_screener_response({"page": "1", "page_size": "50"})

        first = payload["rows"][0]
        self.assertEqual("600001", first["symbol"])
        self.assertEqual(1, first["market_total_rank"])
        self.assertEqual(3, first["market_total_universe_size"])
        self.assertEqual(2, first["industry_total_rank"])
        self.assertEqual(2, first["industry_total_universe_size"])
        self.assertEqual(18.6, first["pe_ttm"])
        self.assertEqual(3.2, first["ps_ttm"])
        self.assertEqual(420.5, first["total_market_cap"])
        self.assertEqual(210.25, first["free_float_market_cap"])
        self.assertEqual("pe_ttm", first["primary_metric"])
        self.assertEqual(35.0, first["primary_percentile"])
        self.assertEqual("行业偏热", first["industry_temperature_label"])
        self.assertEqual(72.5, first["industry_temperature_percentile_since_2022"])

    def test_stock_screener_strategy_filters_by_named_signal_rows(self) -> None:
        from app.search import index

        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:600001": {"total_score": 80.0, "ind_total_score": 80.0, "dim_scores": {}, "sub_indicators": {}},
                "sz:000001": {"total_score": 90.0, "ind_total_score": 90.0, "dim_scores": {}, "sub_indicators": {}},
            },
        }
        securities = [
            {"market": "sh", "symbol": "600001", "stock_name": "策略命中"},
            {"market": "sz", "symbol": "000001", "stock_name": "策略未命中"},
        ]
        strategy_rows = [
            {
                "market": "sh",
                "symbol": "600001",
                "strategy": "rps_standard_launch",
                "strategy_label": "RPS标准启动",
                "passed": True,
            },
            {
                "market": "sz",
                "symbol": "000001",
                "strategy": "rps_standard_launch",
                "strategy_label": "RPS标准启动",
                "passed": False,
            },
        ]

        with mock.patch.object(index, "_load_financial_snapshot", return_value=snapshot), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_rps_rows", return_value=[]), \
             mock.patch.object(index, "load_industry_rows", return_value=[]), \
             mock.patch.object(index, "_load_json_rows", return_value=[]), \
             mock.patch.object(index, "load_stock_screener_strategy_rows", return_value=strategy_rows):
            payload = index.build_stock_screener_response({"strategy": "rps_standard_launch", "page": "1", "page_size": "50"})

        self.assertTrue(payload["ok"])
        self.assertEqual("rps_standard_launch", payload["active_strategy"])
        self.assertEqual(1, payload["total"])
        self.assertEqual("600001", payload["rows"][0]["symbol"])
        self.assertEqual("RPS标准", payload["rows"][0]["strategy_label"])

    def test_rps_standard_launch_formula_matches_tdx_rules(self) -> None:
        from app.search import index

        bars = []
        for i in range(130):
            close = 80 + i * 0.18
            bars.append({"close": close, "high": close * 1.01, "volume": 1000})
        bars[-10]["high"] = 200.0
        bars[-1]["volume"] = 2000
        latest_rps = {"rps_20": 93.0, "rps_50": 89.0, "rps_120": 86.0, "rps_250": 81.0}
        ref3_rps = {"rps_20": 90.0, "rps_50": 88.0, "rps_120": 85.0, "rps_250": 80.0}
        ref5_rps = {"rps_20": 89.0, "rps_50": 87.0, "rps_120": 84.0, "rps_250": 79.0}

        signal = index.evaluate_rps_standard_launch_signal(latest_rps, ref3_rps, ref5_rps, bars)

        self.assertTrue(signal["passed"])
        self.assertTrue(signal["conditions"]["rps_base"])
        self.assertTrue(signal["conditions"]["rps_turning_point"])
        self.assertTrue(signal["conditions"]["volume_start"])
        self.assertNotIn("not_overheated", signal["conditions"])
        self.assertNotIn("near_breakout_zone", signal["conditions"])

    def test_rps_attack_formula_matches_tdx_rules(self) -> None:
        from app.search import index

        bars = []
        for i in range(130):
            close = 80 + i * 0.18
            bars.append({"close": close, "high": close * 1.01, "volume": 1000})
        bars[-10]["high"] = 200.0
        bars[-1]["volume"] = 2000
        latest_rps = {"rps_20": 89.0, "rps_50": 83.0, "rps_120": 81.0, "rps_250": 76.0}
        ref1_rps = {"rps_20": 88.5, "rps_50": 82.8}
        ref2_rps = {"rps_20": 87.5, "rps_50": 82.6}
        ref3_rps = {"rps_20": 87.0, "rps_50": 82.5}

        signal = index.evaluate_rps_attack_signal(latest_rps, ref1_rps, ref2_rps, ref3_rps, bars)

        self.assertTrue(signal["passed"])
        self.assertTrue(signal["conditions"]["rps_base"])
        self.assertTrue(signal["conditions"]["rps_acceleration"])
        self.assertTrue(signal["conditions"]["volume_mild_expand"])
        self.assertNotIn("setup_position", signal["conditions"])

    def test_stock_screener_strategy_filters_rps_pullback_rows(self) -> None:
        from app.search import index

        snapshot = {
            "report_date": "2026Q1",
            "scores": {
                "sh:600001": {"total_score": 80.0, "ind_total_score": 82.0, "dim_scores": {}, "sub_indicators": {}},
                "sz:000001": {"total_score": 90.0, "ind_total_score": 91.0, "dim_scores": {}, "sub_indicators": {}},
            },
        }
        securities = [
            {"market": "sh", "symbol": "600001", "stock_name": "回踩命中"},
            {"market": "sz", "symbol": "000001", "stock_name": "回踩未命中"},
        ]
        rps_rows = [
            {"market": "sh", "symbol": "600001", "rps_20": 96.0, "rps_50": 91.0, "rps_120": 87.0, "rps_250": 82.0},
            {"market": "sz", "symbol": "000001", "rps_20": 90.0, "rps_50": 88.0, "rps_120": 84.0, "rps_250": 79.0},
        ]
        strategy_rows = [
            {"market": "sh", "symbol": "600001", "strategy": "rps_pullback", "strategy_label": "RPS回踩", "passed": True},
            {"market": "sz", "symbol": "000001", "strategy": "rps_pullback", "strategy_label": "RPS回踩", "passed": False},
        ]

        with mock.patch.object(index, "_load_financial_snapshot", return_value=snapshot), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_rps_rows", return_value=rps_rows), \
             mock.patch.object(index, "load_industry_rows", return_value=[]), \
             mock.patch.object(index, "_load_json_rows", return_value=[]), \
             mock.patch.object(index, "load_stock_screener_strategy_rows", return_value=strategy_rows):
            payload = index.build_stock_screener_response({"strategy": "rps_pullback", "page": "1", "page_size": "50"})

        self.assertTrue(payload["ok"])
        self.assertEqual("rps_pullback", payload["active_strategy"])
        self.assertEqual(1, payload["total"])
        row = payload["rows"][0]
        self.assertEqual("600001", row["symbol"])
        self.assertEqual("RPS回踩", row["strategy_label"])
        self.assertEqual(96.0, row["rps_20"])
        self.assertEqual(91.0, row["rps_50"])
        self.assertEqual(87.0, row["rps_120"])
        self.assertEqual(82.0, row["rps_250"])

    def test_rps_pullback_formula_matches_tdx_rules(self) -> None:
        from app.search import index

        bars = []
        for i in range(260):
            close = 50 + i * 0.2
            high = close * 1.005
            low = close * 0.995
            open_price = close * 0.998
            volume = 1000.0
            bars.append({"open": open_price, "high": high, "low": low, "close": close, "volume": volume})
        bars[-5]["low"] = 99.0
        bars[-4]["low"] = 99.2
        bars[-3]["low"] = 99.4
        bars[-2]["low"] = 99.6
        bars[-2]["high"] = 102.0
        bars[-1]["open"] = 101.0
        bars[-1]["close"] = 102.5
        bars[-1]["high"] = 103.0
        bars[-1]["low"] = 100.0
        bars[-1]["volume"] = 1500.0
        latest_rps = {"rps_20": 96.0, "rps_50": 91.0, "rps_120": 87.0, "rps_250": 82.0}
        ref3_rps = {"rps_20": 94.0}
        ref5_rps = {"rps_50": 89.0}

        signal = index.evaluate_rps_pullback_signal(latest_rps, ref3_rps, ref5_rps, bars)

        self.assertTrue(signal["passed"])
        self.assertEqual(
            {
                "rps_base",
                "rps_structure",
                "rps_turning_point",
                "trend_quality",
                "midterm_up",
                "pullback_touched",
                "trend_intact",
                "renewed_strength",
                "volume_confirmed",
                "bullish_candle",
                "not_overheated",
            },
            set(signal["conditions"].keys()),
        )
        self.assertTrue(all(signal["conditions"].values()))

    def test_rps_pullback_formula_fails_without_enough_bars_and_refs(self) -> None:
        from app.search import index

        bars = [{"open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 1000.0} for _ in range(120)]

        signal = index.evaluate_rps_pullback_signal(
            {"rps_20": 96.0, "rps_50": 91.0, "rps_120": 87.0, "rps_250": 82.0},
            {"rps_20": 94.0},
            {"rps_50": 89.0},
            bars,
        )

        self.assertFalse(signal["passed"])
        self.assertFalse(signal["conditions"]["trend_quality"])
        self.assertFalse(signal["conditions"]["midterm_up"])

    def test_dashboard_registers_stock_screener_route(self) -> None:
        from pathlib import Path

        content = Path("scripts/serve_stock_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('/api/stock-screener', content)
        self.assertIn('handle_stock_screener', content)
        self.assertIn('ensure_stock_screener_strategy_dataset', content)
        self.assertIn('build_stock_screener_strategies.py', content)

    def test_stock_screener_strategy_builder_script_uses_formula_helper(self) -> None:
        from pathlib import Path

        content = Path("scripts/build_stock_screener_strategies.py").read_text(encoding="utf-8")
        self.assertIn('dataset_stock_screener_strategies_current.json', content)
        self.assertIn('evaluate_rps_standard_launch_signal', content)
        self.assertIn('evaluate_rps_attack_signal', content)
        self.assertIn('evaluate_rps_pullback_signal', content)
        self.assertIn('rps_standard_launch', content)
        self.assertIn('rps_attack', content)
        self.assertIn('rps_pullback', content)
        self.assertIn('merge_strategy_rows_for_output', content)
        self.assertIn('RPS标准', content)
        self.assertNotIn('RPS标准启动', content)
        self.assertIn('RPS进攻', content)
        self.assertIn('RPS回踩', content)


if __name__ == "__main__":
    unittest.main()
