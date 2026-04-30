import json
import unittest
from unittest import mock

from scripts import serve_stock_dashboard as dashboard


class StockScoreAiReportTests(unittest.TestCase):
    def test_build_ai_financial_report_prompt_mentions_required_sections(self) -> None:
        reports = [
            {
                "report_date": "20260331",
                "period": "2026Q1",
                "announce_date": "20260429",
                "metrics": {
                    "revenue": 1200.0,
                    "net_profit": 180.0,
                    "ocf": 210.0,
                    "roe_ex": 12.8,
                    "debt_ratio": 41.2,
                },
            }
        ]

        prompt = dashboard.build_ai_financial_report_prompt(
            stock_name="中国平安",
            market="sh",
            symbol="601318",
            reports=reports,
        )

        self.assertIn("最近3年", prompt)
        self.assertIn("总体评价", prompt)
        self.assertIn("财报亮点", prompt)
        self.assertIn("风险警示", prompt)
        self.assertIn("加分项", prompt)
        self.assertIn("减分项", prompt)
        self.assertIn("最新一期", prompt)
        self.assertIn("同季度", prompt)
        self.assertIn("上年同期", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("中国平安", prompt)

    def test_generate_stock_ai_report_parses_hermes_json_output(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"overall": "稳健", "highlights": ["现金流改善"], "risks": ["保费增速放缓"], "positive_factors": ["盈利修复"], "negative_factors": ["投资波动"]}'
        report_history = {
            "market": "sh",
            "symbol": "601318",
            "stock_name": "中国平安",
            "reports": [{"report_date": "20260331", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(dashboard, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(dashboard.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = dashboard.generate_stock_ai_report("sh", "601318")

        self.assertTrue(result["ok"])
        self.assertEqual("中国平安", result["stock_name"])
        self.assertEqual("稳健", result["analysis"]["overall"])
        self.assertEqual(["现金流改善"], result["analysis"]["highlights"])
        self.assertEqual(["保费增速放缓"], result["analysis"]["risks"])
        self.assertEqual(["盈利修复"], result["analysis"]["positive_factors"])
        self.assertEqual(["投资波动"], result["analysis"]["negative_factors"])
        self.assertEqual(1, result["report_count"])
        command = run_mock.call_args.args[0]
        self.assertIn("hermes", command[0])
        self.assertIn("chat", command)
        self.assertIn("-q", command)

    def test_load_recent_three_year_financial_reports_returns_recent_three_year_quarter_timeline(self) -> None:
        class FakeRow(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeFrame:
            def __init__(self, rows):
                self._rows = rows

            def iterrows(self):
                return iter(self._rows)

        files = [
            ("20260331", "/tmp/20260331.dat"),
            ("20251231", "/tmp/20251231.dat"),
            ("20250930", "/tmp/20250930.dat"),
            ("20250630", "/tmp/20250630.dat"),
            ("20250331", "/tmp/20250331.dat"),
            ("20241231", "/tmp/20241231.dat"),
            ("20240930", "/tmp/20240930.dat"),
            ("20240630", "/tmp/20240630.dat"),
            ("20240331", "/tmp/20240331.dat"),
        ]
        loaded_map = {
            "/tmp/20260331.dat": ("20260331", FakeFrame([("601318", FakeRow({"announce_date": "20260429"}))])),
            "/tmp/20251231.dat": ("20251231", FakeFrame([("601318", FakeRow({"announce_date": "20260320"}))])),
            "/tmp/20250930.dat": ("20250930", FakeFrame([("601318", FakeRow({"announce_date": "20251030"}))])),
            "/tmp/20250630.dat": ("20250630", FakeFrame([("601318", FakeRow({"announce_date": "20250820"}))])),
            "/tmp/20250331.dat": ("20250331", FakeFrame([("601318", FakeRow({"announce_date": "20250430"}))])),
            "/tmp/20241231.dat": ("20241231", FakeFrame([("601318", FakeRow({"announce_date": "20250320"}))])),
            "/tmp/20240930.dat": ("20240930", FakeFrame([("601318", FakeRow({"announce_date": "20241030"}))])),
            "/tmp/20240630.dat": ("20240630", FakeFrame([("601318", FakeRow({"announce_date": "20240820"}))])),
            "/tmp/20240331.dat": ("20240331", FakeFrame([("601318", FakeRow({"announce_date": "20240429"}))])),
        }

        fake_search_index = mock.Mock()
        fake_search_index._stock_name_lookup.return_value = {("sh", "601318"): "中国平安"}
        fake_search_index._all_financial_files.return_value = files
        fake_search_index._load_file.side_effect = lambda fp: loaded_map[fp]
        fake_search_index._derive_sub_fields.side_effect = [
            {"roe_ex": 12.8, "debt_ratio": 41.2, "current_ratio": 1.2, "quick_ratio": 1.1, "profit_growth": 8.0, "revenue_growth": 6.0, "ex_profit_growth": 7.0},
            {"roe_ex": 12.2, "debt_ratio": 41.5, "current_ratio": 1.2, "quick_ratio": 1.1, "profit_growth": 7.0, "revenue_growth": 5.0, "ex_profit_growth": 6.0},
            {"roe_ex": 11.9, "debt_ratio": 41.8, "current_ratio": 1.1, "quick_ratio": 1.0, "profit_growth": 6.5, "revenue_growth": 4.5, "ex_profit_growth": 5.5},
            {"roe_ex": 11.6, "debt_ratio": 42.0, "current_ratio": 1.1, "quick_ratio": 1.0, "profit_growth": 6.0, "revenue_growth": 4.0, "ex_profit_growth": 5.0},
            {"roe_ex": 11.3, "debt_ratio": 43.0, "current_ratio": 1.0, "quick_ratio": 0.9, "profit_growth": 4.0, "revenue_growth": 3.0, "ex_profit_growth": 2.0},
            {"roe_ex": 11.0, "debt_ratio": 43.2, "current_ratio": 1.0, "quick_ratio": 0.9, "profit_growth": 3.5, "revenue_growth": 2.8, "ex_profit_growth": 1.8},
            {"roe_ex": 10.8, "debt_ratio": 43.5, "current_ratio": 0.9, "quick_ratio": 0.8, "profit_growth": 3.0, "revenue_growth": 2.0, "ex_profit_growth": 1.6},
            {"roe_ex": 10.7, "debt_ratio": 43.7, "current_ratio": 0.9, "quick_ratio": 0.8, "profit_growth": 2.5, "revenue_growth": 1.5, "ex_profit_growth": 1.2},
            {"roe_ex": 10.9, "debt_ratio": 44.0, "current_ratio": 0.9, "quick_ratio": 0.8, "profit_growth": 2.0, "revenue_growth": 1.0, "ex_profit_growth": 1.5},
        ]
        fake_search_index._pick.side_effect = lambda value: value

        with mock.patch.dict("sys.modules", {"app.search.index": fake_search_index}):
            result = dashboard.load_recent_three_year_financial_reports("sh", "601318")

        self.assertEqual("2026Q1", result["latest_period_label"])
        self.assertEqual("20260331", result["latest_report"]["report_date"])
        self.assertEqual(
            ["2024Q1", "2024Q2", "2024Q3", "2024A", "2025Q1", "2025Q2", "2025Q3", "2025A", "2026Q1"],
            [row["period"] for row in result["reports"]],
        )
        self.assertEqual([1.0, 1.5, 2.0], [row["metrics"]["revenue_growth"] for row in result["reports"][:3]])
        self.assertEqual(6.0, result["reports"][-1]["metrics"]["revenue_growth"])


if __name__ == "__main__":
    unittest.main()
