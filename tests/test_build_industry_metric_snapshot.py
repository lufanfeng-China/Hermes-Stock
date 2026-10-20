import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_industry_metric_snapshot as builder
from scripts.build_industry_metric_snapshot import build_snapshot, publish_snapshot


class BuildIndustryMetricSnapshotTests(unittest.TestCase):
    def test_groups_all_secondary_industry_members_and_reports_metric_coverage(self):
        source = {
            "schema_version": "stock-filter-strict-financial-v1",
            "annual_anchor": "2025A",
            "quarterly_anchor": "2026Q2",
            "stocks": {
                "sz:300001": {
                    "peer_metrics": {
                        "revenue": {
                            "annual": {"period": "2025A", "value": 120},
                            "quarter": {"period": "2026Q2", "value": 75},
                            "ttm": {"period": "2026Q2", "value": 135},
                        },
                    },
                },
            },
        }
        industry_rows = [
            {"market": "sz", "symbol": "300001", "industry_level_1_name": "设备", "industry_level_2_name": "光伏设备"},
            {"market": "sz", "symbol": "300002", "industry_level_1_name": "设备", "industry_level_2_name": "光伏设备"},
        ]

        payload = build_snapshot(
            source,
            industry_rows,
            name_lookup={("sz", "300001"): "甲", ("sz", "300002"): "乙"},
            source_path="strict_financial_health_snapshot_2025A__2026Q2.json",
            built_at="2026-10-17T00:00:00Z",
        )

        self.assertEqual(payload["built_at"], "2026-10-17T00:00:00Z")
        self.assertEqual(payload["annual_anchor"], "2025A")
        self.assertEqual(payload["quarter_anchor"], "2026Q2")
        self.assertEqual(
            payload["source_versions"]["strict_financial_health_snapshot"],
            {"path": "strict_financial_health_snapshot_2025A__2026Q2.json", "schema_version": "stock-filter-strict-financial-v1"},
        )
        industry = payload["industries"]["光伏设备"]
        self.assertEqual(industry["coverage"], {
            "members": 2,
            "snapshot_records": 1,
            "metrics": {"revenue": {"annual": 1, "quarter": 1, "ttm": 1}},
        })
        self.assertEqual(
            industry["rows"],
            [
                {
                    "market": "sz", "symbol": "300001", "stock_name": "甲",
                    "peer_metrics": source["stocks"]["sz:300001"]["peer_metrics"], "available": True,
                },
                {
                    "market": "sz", "symbol": "300002", "stock_name": "乙",
                    "peer_metrics": {}, "available": False,
                    "unavailable_reason": "strict_financial_health_snapshot_record_missing",
                },
            ],
        )

    def test_publishes_versioned_snapshot_before_current_snapshot(self):
        payload = {"built_at": "2026-10-17T12:34:56Z", "industries": {"光伏设备": {}}}
        with tempfile.TemporaryDirectory() as directory:
            current_path, versioned_path = publish_snapshot(payload, Path(directory))
            self.assertEqual(versioned_path.name, "dataset_industry_metric_peers_2026-10-17.json")
            self.assertEqual(current_path.name, "dataset_industry_metric_peers_current.json")
            versioned = json.loads(versioned_path.read_text(encoding="utf-8"))
            current = json.loads(current_path.read_text(encoding="utf-8"))
            self.assertEqual(versioned, current)
            self.assertNotIn("industries", current)
            self.assertEqual(current["partitions"], {"光伏设备": "dataset_industry_metric_peers_2026-10-17.partitions/f87d56f3eddc63600314.json"})

    def test_publishes_small_manifest_with_stock_index_and_separate_partitions(self):
        payload = {
            "built_at": "2026-10-17T12:34:56Z",
            "annual_anchor": "2025A",
            "quarter_anchor": "2026Q2",
            "industries": {
                "光伏设备": {"industry_level_1": "设备", "industry_level_2": "光伏设备", "rows": [
                    {"market": "sz", "symbol": "300001", "stock_name": "甲", "peer_metrics": {}},
                ]},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            current_path, versioned_path = publish_snapshot(payload, Path(directory))
            manifest = json.loads(current_path.read_text(encoding="utf-8"))
            partition_path = Path(directory) / manifest["partitions"]["光伏设备"]

            self.assertNotIn("industries", manifest)
            self.assertEqual(manifest["stock_to_industry"], {"sz:300001": "光伏设备"})
            self.assertTrue(partition_path.is_file())
            self.assertEqual(json.loads(partition_path.read_text(encoding="utf-8")), payload["industries"]["光伏设备"])
            self.assertEqual(json.loads(versioned_path.read_text(encoding="utf-8"))["partitions"], manifest["partitions"])

    def test_main_discovers_published_source_outside_requested_output_directory(self):
        source_path = Path("/published/strict.json")
        strict_snapshot = {"stocks": {}}
        payload = {"industries": {}, "annual_anchor": "2025A", "quarter_anchor": "2026Q2"}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(builder, "discover_strict_snapshot", return_value=source_path) as discover, \
             patch.object(builder, "_load_json", return_value=strict_snapshot), \
             patch.object(builder.search_index, "load_industry_rows", return_value=[]), \
             patch.object(builder.search_index, "_stock_name_lookup", return_value={}), \
             patch.object(builder, "build_snapshot", return_value=payload), \
             patch.object(builder, "publish_snapshot", return_value=(Path(directory) / "current.json", Path(directory) / "versioned.json")), \
             patch.object(sys, "argv", ["build_industry_metric_snapshot.py", "--output-dir", directory]):
            builder.main()

        discover.assert_called_once_with(builder.FINAL_DIR)


if __name__ == "__main__":
    unittest.main()
