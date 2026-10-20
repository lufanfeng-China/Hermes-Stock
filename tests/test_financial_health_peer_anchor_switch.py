import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_financial_health_peer_snapshot as builder


class FinancialHealthPeerAnchorSwitchTests(unittest.TestCase):
    def test_publish_writes_versioned_snapshot_then_atomic_current_pointer(self):
        payload = {
            "annual_anchor": "2025A",
            "quarterly_anchor": "2026Q3",
            "periods_loaded": ["2021A", "2022A", "2023A", "2024A", "2025A", "2025Q3", "2026Q3"],
            "stocks": {"sh:600001": {}},
        }
        with tempfile.TemporaryDirectory() as directory:
            current, versioned = builder.publish_snapshot(payload, Path(directory))

            self.assertEqual("financial_health_peer_snapshot_current.json", current.name)
            self.assertEqual("financial_health_peer_snapshot_2025A__2026Q3.json", versioned.name)
            self.assertEqual(payload, json.loads(versioned.read_text(encoding="utf-8")))
            self.assertEqual(payload, json.loads(current.read_text(encoding="utf-8")))

    def test_incremental_refresh_rebuilds_all_market_when_quarter_anchor_changed(self):
        existing = {"annual_anchor": "2025A", "quarterly_anchor": "2026Q2", "stocks": {"sh:600001": {}}}
        selection = {"annual_anchor": "2025A", "quarterly_anchor": "2026Q3", "periods": ["2021A", "2022A", "2023A", "2024A", "2025A", "2025Q3", "2026Q3"]}
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "financial_health_peer_snapshot_current.json"
            current.write_text(json.dumps(existing), encoding="utf-8")
            rebuilt = {**existing, **selection, "stocks": {"sh:600001": {"quarterly": {"period": "2026Q3"}}, "sz:000001": {}}}
            with patch.object(builder, "select_warehouse_periods", return_value=selection), \
                 patch.object(builder, "build_full_snapshot", return_value=rebuilt) as full_build, \
                 patch.object(builder, "publish_snapshot") as publish:
                result = builder.refresh_snapshot(current, ["600001"], warehouse_dir=Path(directory) / "warehouse")

        self.assertEqual("full_rebuild", result["mode"])
        full_build.assert_called_once_with(selection, warehouse_dir=Path(directory) / "warehouse")
        publish.assert_called_once_with(rebuilt, current.parent)

    def test_incremental_refresh_updates_only_changed_symbols_when_anchors_match(self):
        selection = {"annual_anchor": "2025A", "quarterly_anchor": "2026Q3", "periods": ["2021A", "2022A", "2023A", "2024A", "2025A", "2025Q3", "2026Q3"]}
        existing = {"annual_anchor": selection["annual_anchor"], "quarterly_anchor": selection["quarterly_anchor"], "periods_loaded": selection["periods"], "stocks": {"sh:600001": {"old": 1}, "sz:000001": {"old": 2}}}
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "financial_health_peer_snapshot_current.json"
            current.write_text(json.dumps(existing), encoding="utf-8")
            with patch.object(builder, "select_warehouse_periods", return_value=selection), \
                 patch.object(builder, "refresh_symbol_records", return_value={"sh:600001": {"new": 1}}) as refresh, \
                 patch.object(builder, "publish_snapshot") as publish:
                result = builder.refresh_snapshot(current, ["600001"], warehouse_dir=Path(directory) / "warehouse")

        self.assertEqual("incremental", result["mode"])
        refresh.assert_called_once_with(["600001"], selection, warehouse_dir=Path(directory) / "warehouse")
        payload = publish.call_args.args[0]
        self.assertEqual({"new": 1}, payload["stocks"]["sh:600001"])
        self.assertEqual({"old": 2}, payload["stocks"]["sz:000001"])

    def test_full_snapshot_keeps_unavailable_members_instead_of_falling_back_to_an_old_anchor(self):
        import pandas as pd

        selection = {"annual_anchor": "2025A", "quarterly_anchor": "2026Q3", "periods": ["2021A", "2025A", "2025Q3", "2026Q3"]}
        frames = {
            "2021A": pd.DataFrame({"value": [1, 2]}, index=["600001", "600002"]),
            "2025A": pd.DataFrame({"value": [1, 2]}, index=["600001", "600002"]),
            "2025Q3": pd.DataFrame({"value": [1, 2]}, index=["600001", "600002"]),
            "2026Q3": pd.DataFrame({"value": [1]}, index=["600001"]),
        }
        with patch.object(builder, "_industry_map", return_value={("sh", "600001"): ("二级", "一级")}), \
             patch.object(builder, "build_strict_financial_record", return_value={"annual": {"score": 1}, "quarterly": {"period": "2026Q3"}}):
            records = builder._records_from_frames(frames, selection)

        self.assertIn("sh:600002", records)
        self.assertIsNone(records["sh:600002"]["quarterly"]["period"])
        self.assertEqual("2026Q3", records["sh:600002"]["quarterly"]["anchor_period"])

    def test_peer_loader_reads_current_snapshot_not_a_hard_coded_quarter(self):
        from app.financial import health_peer_snapshot

        self.assertEqual(
            "financial_health_peer_snapshot_current.json",
            health_peer_snapshot.CURRENT_SNAPSHOT.name,
        )


if __name__ == "__main__":
    unittest.main()
