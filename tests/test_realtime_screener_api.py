import unittest
from pathlib import Path
from unittest import mock


class RealtimeScreenerApiTests(unittest.TestCase):
    def test_realtime_screener_response_returns_tail_session_defaults(self) -> None:
        from app.search import index

        payload = index.realtime_screener_response(
            {
                "scenario": "tail_session",
                "refresh_seconds": "30",
                "gain_min_pct": "3",
                "gain_max_pct": "5",
                "limit_up_lookback_days": "20",
                "min_volume_ratio": "1.4",
                "max_market_cap_yi": "200",
                "turnover_min_pct": "5",
                "turnover_max_pct": "10",
                "intraday_above_vwap": "true",
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual("tail_session", payload["scenario"])
        self.assertEqual("尾盘选股", payload["scenario_label"])
        self.assertEqual(30, payload["refresh_seconds"])
        self.assertEqual(3.0, payload["conditions"]["gain_min_pct"])
        self.assertEqual(5.0, payload["conditions"]["gain_max_pct"])
        self.assertEqual(20, payload["conditions"]["limit_up_lookback_days"])
        self.assertEqual(1.4, payload["conditions"]["min_volume_ratio"])
        self.assertEqual(200.0, payload["conditions"]["max_market_cap_yi"])
        self.assertEqual(5.0, payload["conditions"]["turnover_min_pct"])
        self.assertEqual(10.0, payload["conditions"]["turnover_max_pct"])
        self.assertTrue(payload["conditions"]["intraday_above_vwap"])
        self.assertEqual(80.0, payload["conditions"]["intraday_above_vwap_min_ratio_pct"])
        self.assertEqual(0.3, payload["conditions"]["intraday_vwap_max_breach_pct"])
        self.assertTrue(payload["conditions"]["current_above_open"])
        self.assertTrue(payload["condition_enabled"]["gain_pct"])
        self.assertTrue(payload["condition_enabled"]["limit_up_lookback_days"])
        self.assertTrue(payload["condition_enabled"]["min_volume_ratio"])
        self.assertTrue(payload["condition_enabled"]["max_market_cap_yi"])
        self.assertTrue(payload["condition_enabled"]["turnover_pct"])
        self.assertTrue(payload["condition_enabled"]["intraday_above_vwap"])
        self.assertTrue(payload["condition_enabled"]["current_above_open"])
        self.assertIn("rows", payload)
        self.assertEqual([], payload["rows"])
        self.assertIn("实时行情", payload["data_note"])

    def test_realtime_screener_response_filters_live_tail_session_quotes(self) -> None:
        from app.search import index

        quotes = [
            {
                "market": "sh",
                "symbol": "600001",
                "price": 10.4,
                "open": 10.1,
                "last_close": 10.0,
                "low": 10.3,
                "volume": 200000,
                "amount": 206000000.0,
                "volume_ratio": 1.8,
                "intraday_points": [
                    {"price": 10.06, "volume": 1000, "amount": 1008000.0},
                    {"price": 10.09, "volume": 1000, "amount": 1009000.0},
                    {"price": 10.20, "volume": 1000, "amount": 1020000.0},
                    {"price": 10.32, "volume": 1000, "amount": 1032000.0},
                    {"price": 10.40, "volume": 1000, "amount": 1040000.0},
                ],
            },
            {
                "market": "sz",
                "symbol": "000001",
                "price": 10.1,
                "open": 10.2,
                "last_close": 10.0,
                "low": 9.8,
                "volume": 100000,
                "amount": 99000000.0,
                "volume_ratio": 1.1,
                "intraday_points": [
                    {"price": 9.70, "volume": 1000, "amount": 1000000.0},
                    {"price": 9.80, "volume": 1000, "amount": 1000000.0},
                    {"price": 9.90, "volume": 1000, "amount": 1000000.0},
                ],
            },
        ]
        securities = [
            {"market": "sh", "symbol": "600001", "stock_name": "实时命中"},
            {"market": "sz", "symbol": "000001", "stock_name": "实时未命中"},
        ]
        valuation_rows = [
            {
                "member_valuation_rows": [
                    {
                        "market": "sh",
                        "symbol": "600001",
                        "total_market_cap": 120.0,
                        "free_float_market_cap": 40.0,
                    },
                    {
                        "market": "sz",
                        "symbol": "000001",
                        "total_market_cap": 300.0,
                        "free_float_market_cap": 100.0,
                    },
                ]
            }
        ]

        with mock.patch.object(index, "load_realtime_quote_rows", return_value=quotes), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_industry_valuation_rows", return_value=valuation_rows), \
             mock.patch.object(index, "_has_recent_limit_up", side_effect=lambda market, symbol, days: symbol == "600001"):
            payload = index.realtime_screener_response(
                {
                    "scenario": "tail_session",
                    "monitor": "true",
                    "gain_min_pct": "3",
                    "gain_max_pct": "5",
                    "limit_up_lookback_days": "20",
                    "min_volume_ratio": "1.4",
                    "max_market_cap_yi": "200",
                    "turnover_min_pct": "5",
                    "turnover_max_pct": "10",
                    "intraday_above_vwap": "true",
                    "intraday_above_vwap_min_ratio_pct": "80",
                    "intraday_vwap_max_breach_pct": "0.3",
                    "current_above_open": "true",
                }
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(1, len(payload["rows"]))
        row = payload["rows"][0]
        self.assertEqual("600001", row["symbol"])
        self.assertEqual("实时命中", row["stock_name"])
        self.assertEqual(4.0, row["gain_pct"])
        self.assertEqual(1.8, row["volume_ratio"])
        self.assertEqual(120.0, row["market_cap_yi"])
        self.assertTrue(5.0 <= row["turnover_pct"] <= 10.0)
        self.assertIn("全天在均价线上方", row["matched_conditions"])

    def test_realtime_screener_rows_include_industry_score_rank_and_info(self) -> None:
        from app.search import index

        quotes = [{
            "market": "sh",
            "symbol": "600001",
            "price": 10.4,
            "open": 10.1,
            "last_close": 10.0,
            "low": 10.3,
            "volume": 200000,
            "amount": 206000000.0,
            "volume_ratio": 1.8,
            "intraday_points": [
                {"price": 10.06, "volume": 1000, "amount": 1008000.0},
                {"price": 10.09, "volume": 1000, "amount": 1009000.0},
                {"price": 10.20, "volume": 1000, "amount": 1020000.0},
                {"price": 10.32, "volume": 1000, "amount": 1032000.0},
                {"price": 10.40, "volume": 1000, "amount": 1040000.0},
            ],
        }]
        securities = [{"market": "sh", "symbol": "600001", "stock_name": "行业清单命中"}]
        industry_rows = [{
            "market": "sh",
            "symbol": "600001",
            "industry_level_1_name": "电子",
            "industry_level_2_name": "半导体",
        }]
        valuation_rows = [{"member_valuation_rows": [{"market": "sh", "symbol": "600001", "total_market_cap": 120.0, "free_float_market_cap": 40.0}]}]
        snapshot = {"scores": {
            "sh:600001": {"industry_sw_level_1": "电子", "industry_sw_level_2": "半导体", "ind_total_score": 88.0},
            "sh:600099": {"industry_sw_level_1": "电子", "industry_sw_level_2": "半导体", "ind_total_score": 90.0},
            "sz:000888": {"industry_sw_level_1": "电子", "industry_sw_level_2": "半导体", "ind_total_score": 70.0},
        }}

        with mock.patch.object(index, "load_realtime_quote_rows", return_value=quotes), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_industry_rows", return_value=industry_rows), \
             mock.patch.object(index, "load_industry_valuation_rows", return_value=valuation_rows), \
             mock.patch.object(index, "_load_financial_snapshot", return_value=snapshot), \
             mock.patch.object(index, "_has_recent_limit_up", return_value=True):
            payload = index.realtime_screener_response(
                {
                    "scenario": "tail_session",
                    "monitor": "true",
                    "gain_min_pct": "3",
                    "gain_max_pct": "5",
                    "limit_up_lookback_days": "20",
                    "min_volume_ratio": "1.4",
                    "max_market_cap_yi": "200",
                    "turnover_min_pct": "5",
                    "turnover_max_pct": "10",
                    "intraday_above_vwap": "true",
                    "current_above_open": "true",
                }
            )

        row = payload["rows"][0]
        self.assertEqual("电子", row["industry_level_1"])
        self.assertEqual("半导体", row["industry_level_2"])
        self.assertEqual(88.0, row["industry_total_score"])
        self.assertEqual(2, row["industry_total_rank"])
        self.assertEqual(3, row["industry_total_universe_size"])

    def test_realtime_screener_disabled_condition_does_not_filter_quotes(self) -> None:
        from app.search import index

        quotes = [
            {
                "market": "sh",
                "symbol": "600001",
                "price": 10.4,
                "open": 10.1,
                "last_close": 10.0,
                "low": 10.3,
                "volume": 200000,
                "amount": 206000000.0,
                "volume_ratio": 1.1,
            }
        ]
        securities = [{"market": "sh", "symbol": "600001", "stock_name": "关闭量比后命中"}]
        valuation_rows = [{"member_valuation_rows": [{"market": "sh", "symbol": "600001", "total_market_cap": 120.0, "free_float_market_cap": 40.0}]}]

        with mock.patch.object(index, "load_realtime_quote_rows", return_value=quotes), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_industry_valuation_rows", return_value=valuation_rows), \
             mock.patch.object(index, "_has_recent_limit_up", return_value=True):
            payload = index.realtime_screener_response(
                {
                    "scenario": "tail_session",
                    "monitor": "true",
                    "gain_min_pct": "3",
                    "gain_max_pct": "5",
                    "limit_up_lookback_days": "20",
                    "min_volume_ratio": "1.4",
                    "enable_min_volume_ratio": "false",
                    "max_market_cap_yi": "200",
                    "turnover_min_pct": "5",
                    "turnover_max_pct": "10",
                    "intraday_above_vwap": "true",
                }
            )

        self.assertFalse(payload["condition_enabled"]["min_volume_ratio"])
        self.assertEqual(1, len(payload["rows"]))
        self.assertEqual("600001", payload["rows"][0]["symbol"])

    def test_realtime_screener_intraday_vwap_allows_short_shallow_breach_and_requires_current_above_open(self) -> None:
        from app.search import index

        base_quote = {
            "market": "sh",
            "symbol": "600001",
            "price": 10.4,
            "open": 10.1,
            "last_close": 10.0,
            "low": 10.0,
            "volume": 200000,
            "amount": 202000000.0,
            "volume_ratio": 1.8,
        }
        quotes = [
            {
                **base_quote,
                "symbol": "600001",
                "intraday_points": [
                    {"price": 10.06, "volume": 1000, "amount": 1008000.0},
                    {"price": 10.09, "volume": 1000, "amount": 1009000.0},
                    {"price": 10.20, "volume": 1000, "amount": 1020000.0},
                    {"price": 10.32, "volume": 1000, "amount": 1032000.0},
                    {"price": 10.40, "volume": 1000, "amount": 1040000.0},
                ],
            },
            {
                **base_quote,
                "symbol": "600002",
                "price": 10.05,
                "open": 10.1,
                "intraday_points": [
                    {"price": 10.20, "volume": 1000, "amount": 1020000.0},
                    {"price": 10.24, "volume": 1000, "amount": 1024000.0},
                    {"price": 10.30, "volume": 1000, "amount": 1030000.0},
                    {"price": 10.40, "volume": 1000, "amount": 1040000.0},
                ],
            },
            {
                **base_quote,
                "symbol": "600003",
                "intraday_points": [
                    {"price": 9.95, "volume": 1000, "amount": 1008000.0},
                    {"price": 10.09, "volume": 1000, "amount": 1009000.0},
                    {"price": 10.20, "volume": 1000, "amount": 1020000.0},
                    {"price": 10.32, "volume": 1000, "amount": 1032000.0},
                    {"price": 10.40, "volume": 1000, "amount": 1040000.0},
                ],
            },
        ]
        securities = [
            {"market": "sh", "symbol": "600001", "stock_name": "浅跌可容忍"},
            {"market": "sh", "symbol": "600002", "stock_name": "低于开盘"},
            {"market": "sh", "symbol": "600003", "stock_name": "跌破过深"},
        ]
        valuation_rows = [{"member_valuation_rows": [
            {"market": "sh", "symbol": "600001", "total_market_cap": 120.0, "free_float_market_cap": 40.0},
            {"market": "sh", "symbol": "600002", "total_market_cap": 120.0, "free_float_market_cap": 40.0},
            {"market": "sh", "symbol": "600003", "total_market_cap": 120.0, "free_float_market_cap": 40.0},
        ]}]

        with mock.patch.object(index, "load_realtime_quote_rows", return_value=quotes), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_industry_valuation_rows", return_value=valuation_rows), \
             mock.patch.object(index, "_has_recent_limit_up", return_value=True):
            payload = index.realtime_screener_response(
                {
                    "scenario": "tail_session",
                    "monitor": "true",
                    "gain_min_pct": "0",
                    "gain_max_pct": "10",
                    "limit_up_lookback_days": "20",
                    "min_volume_ratio": "1.4",
                    "max_market_cap_yi": "200",
                    "turnover_min_pct": "5",
                    "turnover_max_pct": "10",
                    "intraday_above_vwap": "true",
                    "intraday_above_vwap_min_ratio_pct": "80",
                    "intraday_vwap_max_breach_pct": "0.3",
                    "current_above_open": "true",
                }
            )

        self.assertEqual(["600001"], [row["symbol"] for row in payload["rows"]])
        self.assertIn("大部分时间在均价线上方", payload["rows"][0]["matched_conditions"])
        self.assertIn("当前价高于开盘价", payload["rows"][0]["matched_conditions"])

    def test_realtime_screener_loads_intraday_points_when_quote_snapshot_has_no_points(self) -> None:
        from app.search import index

        quotes = [{
            "market": "sh",
            "symbol": "600004",
            "price": 10.4,
            "open": 10.1,
            "last_close": 10.0,
            "low": 9.9,
            "volume": 200000,
            "amount": 206000000.0,
            "volume_ratio": 1.8,
        }]
        securities = [{"market": "sh", "symbol": "600004", "stock_name": "实时分时命中"}]
        valuation_rows = [{"member_valuation_rows": [{"market": "sh", "symbol": "600004", "total_market_cap": 120.0, "free_float_market_cap": 40.0}]}]
        intraday_points = [
            {"price": 10.06, "volume": 1000},
            {"price": 10.09, "volume": 1000},
            {"price": 10.20, "volume": 1000},
            {"price": 10.32, "volume": 1000},
            {"price": 10.40, "volume": 1000},
        ]

        with mock.patch.object(index, "load_realtime_quote_rows", return_value=quotes), \
             mock.patch.object(index, "load_security_rows", return_value=securities), \
             mock.patch.object(index, "load_industry_valuation_rows", return_value=valuation_rows), \
             mock.patch.object(index, "_has_recent_limit_up", return_value=True), \
             mock.patch.object(index, "load_realtime_intraday_points", return_value=intraday_points) as intraday_loader:
            payload = index.realtime_screener_response(
                {
                    "scenario": "tail_session",
                    "monitor": "true",
                    "gain_min_pct": "0",
                    "gain_max_pct": "10",
                    "limit_up_lookback_days": "20",
                    "min_volume_ratio": "1.4",
                    "max_market_cap_yi": "200",
                    "turnover_min_pct": "5",
                    "turnover_max_pct": "10",
                    "intraday_above_vwap": "true",
                    "intraday_above_vwap_min_ratio_pct": "80",
                    "intraday_vwap_max_breach_pct": "0.3",
                    "current_above_open": "true",
                }
            )

        intraday_loader.assert_called_once_with("sh", "600004")
        self.assertEqual(["600004"], [row["symbol"] for row in payload["rows"]])

    def test_dashboard_registers_realtime_screener_api_route(self) -> None:
        content = Path("scripts/serve_stock_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('/api/realtime-screener', content)
        self.assertIn('handle_realtime_screener', content)
        self.assertIn('realtime_screener_response', content)


if __name__ == "__main__":
    unittest.main()
