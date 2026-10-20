import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import handler as app_handler
from app.financial import industry_metric_peers


class IndustryMetricPeersTests(unittest.TestCase):
    def _snapshot_file(self, directory: str) -> Path:
        path = Path(directory) / "snapshot.json"
        path.write_text(json.dumps({
            "schema_version": "industry-peer-v1",
            "snapshot_as_of": "2026-10-16T08:30:00+08:00",
            "stocks": {
                "sz:300001": {"peer_metrics": {"cash_profit_ratio": {
                    "annual": {"period": "2025A", "value": 1.2, "yoy_value": 3.1, "basis": "annual"},
                    "quarter": {"period": "2026Q2", "value": 1.1, "yoy_value": 2.0, "basis": "quarter_cumulative"},
                    "ttm": {"period": "2026Q2", "value": 1.3, "yoy_value": 4.0, "basis": "ttm"},
                }}},
                "sz:300002": {"peer_metrics": {"cash_profit_ratio": {
                    "annual": {"period": "2025A", "value": 0.8, "yoy_value": None, "basis": "annual"},
                    "quarter": {"period": "2026Q2", "value": None, "yoy_value": None, "basis": "quarter_cumulative"},
                    "ttm": {"period": "2026Q2", "value": None, "yoy_value": None, "basis": "ttm"},
                }}},
            },
        }), encoding="utf-8")
        return path

    def _industry_patches(self):
        industry_map = {
            ("sz", "300001"): ("设备", "制造"),
            ("sz", "300002"): ("设备", "制造"),
        }
        return (
            patch("app.search.index._load_industry_map", return_value=industry_map),
            patch("app.search.index._stock_name_lookup", return_value={("sz", "300001"): "甲", ("sz", "300002"): "乙"}),
        )

    def test_api_returns_audited_snapshot_contract_for_valid_request(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = self._snapshot_file(directory)
            load_industries, load_names = self._industry_patches()
            with patch.object(industry_metric_peers, "SNAPSHOT", snapshot_path), \
                 patch.object(industry_metric_peers, "CURRENT_SNAPSHOT", Path(directory) / "missing-current.json"), \
                 load_industries, load_names, \
                 patch("app.financial.reports.load_recent_three_year_financial_reports") as raw_loader:
                industry_metric_peers._load_snapshot.cache_clear()
                payload = industry_metric_peers.build_industry_metric_peers("sz", "300001", "cash_profit_ratio")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["metric"], {
            "code": "cash_profit_ratio", "label": "现金利润比", "unit": "倍",
            "formula": "经营现金流 ÷ 扣非归母净利润", "growth_unit": "%", "ttm_supported": True,
        })
        self.assertEqual(payload["industry_level_2"], "设备")
        self.assertEqual(payload["snapshot_as_of"], "2026-10-16T08:30:00+08:00")
        self.assertEqual(payload["coverage"], {"members": 2, "annual": 2, "quarter": 1, "ttm": 1})
        self.assertEqual(len(payload["rows"]), 2)
        self.assertTrue(payload["rows"][0]["is_current_stock"])
        self.assertEqual(payload["rows"][1]["metrics"]["quarter"]["value"], None)
        raw_loader.assert_not_called()

    def test_all_planned_derived_metric_contracts_are_exposed(self):
        expected = {
            "revenue_growth": ("营收增长率", "%", "百分点", False),
            "fcf_margin": ("FCF Margin", "%", "百分点", True),
            "capex_intensity": ("CapEx 强度", "%", "百分点", True),
            "accounts_receivable_growth_gap": ("应收增速差", "百分点", "百分点", False),
            "inventory_growth_gap": ("存货增速差", "百分点", "百分点", False),
        }
        for code, (label, unit, growth_unit, ttm_supported) in expected.items():
            metadata = industry_metric_peers._metric_metadata(code)
            self.assertEqual((metadata["label"], metadata["unit"], metadata["growth_unit"], metadata["ttm_supported"]), (label, unit, growth_unit, ttm_supported))

    def test_api_reads_independent_industry_partition_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "dataset_industry_metric_peers_current.json"
            snapshot_path.write_text(json.dumps({
                "built_at": "2026-10-17T04:47:19Z",
                "industries": {"设备": {"industry_level_1": "制造", "industry_level_2": "设备", "coverage": {"members": 2, "metrics": {"revenue": {"annual": 1, "quarter": 1, "ttm": 1}}}, "rows": [
                    {"market": "sz", "symbol": "300001", "stock_name": "甲", "available": True, "peer_metrics": {"revenue": {"annual": {"value": 1}, "quarter": {"value": 2}, "ttm": {"value": 3}}}},
                    {"market": "sz", "symbol": "300002", "stock_name": "乙", "available": False, "peer_metrics": {}},
                ]}},
            }), encoding="utf-8")
            load_industries, load_names = self._industry_patches()
            with patch.object(industry_metric_peers, "CURRENT_SNAPSHOT", snapshot_path), load_industries, load_names:
                industry_metric_peers._load_snapshot.cache_clear()
                payload = industry_metric_peers.build_industry_metric_peers("sz", "300001", "revenue")

        self.assertEqual(payload["coverage"], {"members": 2, "annual": 1, "quarter": 1, "ttm": 1})
        self.assertEqual(payload["rows"][0]["metrics"]["ttm"]["value"], 3)
        self.assertFalse(payload["rows"][1]["available"])

    def test_partitioned_manifest_reads_only_requested_partition_without_industry_map(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            manifest_path = directory_path / "dataset_industry_metric_peers_current.json"
            partitions_path = directory_path / "dataset_industry_metric_peers_current.partitions"
            partitions_path.mkdir()
            manifest_path.write_text(json.dumps({
                "schema_version": "industry-metric-peers-v2",
                "built_at": "2026-10-17T04:47:19Z",
                "stock_to_industry": {"sz:300001": "设备"},
                "partitions": {"设备": "dataset_industry_metric_peers_current.partitions/equipment.json"},
            }), encoding="utf-8")
            (partitions_path / "equipment.json").write_text(json.dumps({
                "industry_level_1": "制造", "industry_level_2": "设备", "rows": [
                    {"market": "sz", "symbol": "300001", "stock_name": "甲", "peer_metrics": {"revenue": {
                        "annual": {"value": 1}, "quarter": {"value": 2}, "ttm": {"value": 3},
                    }}},
                ],
            }), encoding="utf-8")
            original_load = industry_metric_peers._load_snapshot
            original_load.cache_clear()
            loaded_paths = []

            def recording_load(path_text, mtime_ns):
                loaded_paths.append(Path(path_text))
                return original_load(path_text, mtime_ns)

            with patch.object(industry_metric_peers, "CURRENT_SNAPSHOT", manifest_path), \
                 patch.object(industry_metric_peers, "SNAPSHOT", directory_path / "missing.json"), \
                 patch.object(industry_metric_peers, "_load_snapshot", side_effect=recording_load), \
                 patch("app.search.index._load_industry_map", side_effect=AssertionError("hot path used industry map")), \
                 patch("app.search.index._stock_name_lookup", side_effect=AssertionError("hot path used name lookup")):
                industry_metric_peers._load_snapshot.cache_clear()
                payload = industry_metric_peers.build_industry_metric_peers("sz", "300001", "revenue")

        self.assertEqual(loaded_paths, [manifest_path, partitions_path / "equipment.json"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["industry_level_2"], "设备")
        self.assertEqual(payload["coverage"], {"members": 1, "annual": 1, "quarter": 1, "ttm": 1})
        self.assertEqual(payload["rows"][0]["stock_name"], "甲")

    def test_handler_returns_structured_errors_for_unknown_metric_no_industry_and_no_snapshot(self):
        handler = Mock()
        app_handler.StockDashboardHandler.handle_industry_metric_peers(
            handler, "market=sz&symbol=300001&metric=not-a-metric",
        )
        status, payload = handler.respond_json.call_args.args
        self.assertEqual(status, app_handler.HTTPStatus.BAD_REQUEST)
        self.assertEqual(payload["error"]["code"], "unknown_metric")

        handler.reset_mock()
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = self._snapshot_file(directory)
            with patch.object(industry_metric_peers, "SNAPSHOT", snapshot_path), \
                 patch.object(industry_metric_peers, "CURRENT_SNAPSHOT", Path(directory) / "missing-current.json"), \
                 patch("app.search.index._load_industry_map", return_value={}):
                industry_metric_peers._load_snapshot.cache_clear()
                app_handler.StockDashboardHandler.handle_industry_metric_peers(
                    handler, "market=sz&symbol=300001&metric=revenue",
                )
        status, payload = handler.respond_json.call_args.args
        self.assertEqual(status, app_handler.HTTPStatus.NOT_FOUND)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "industry_classification_unavailable")

        handler.reset_mock()
        missing = Path(tempfile.gettempdir()) / "missing-industry-peer-snapshot.json"
        with patch.object(industry_metric_peers, "SNAPSHOT", missing), \
             patch.object(industry_metric_peers, "CURRENT_SNAPSHOT", missing, create=True):
            industry_metric_peers._load_snapshot.cache_clear()
            app_handler.StockDashboardHandler.handle_industry_metric_peers(
                handler, "market=sz&symbol=300001&metric=revenue",
            )
        status, payload = handler.respond_json.call_args.args
        self.assertEqual(status, app_handler.HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertEqual(payload["error"]["code"], "snapshot_unavailable")


if __name__ == "__main__":
    unittest.main()
