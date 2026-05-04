import json
import tempfile
import unittest
from unittest import mock


class RelativeValuationSnapshotBuilderTests(unittest.TestCase):
    def test_build_current_industry_snapshots_deduplicates_industries_and_skips_empty_rows(self) -> None:
        from app.relative_valuation import snapshot_builder

        industry_rows = [
            {"industry_level_2_name": "白色家电"},
            {"industry_level_2_name": "白色家电"},
            {"industry_level_2_name": "工业金属"},
            {"industry_level_2_name": ""},
        ]

        def fake_build(name: str):
            if name == "白色家电":
                return {"industry_level_2_name": name, "weighted_pe_ttm": 12.3}
            if name == "工业金属":
                return {"industry_level_2_name": name, "weighted_pe_ttm": 20.6}
            return None

        with (
            mock.patch.object(snapshot_builder, "load_industry_rows", return_value=industry_rows),
            mock.patch.object(snapshot_builder, "build_industry_snapshot_for_industry", side_effect=fake_build),
        ):
            rows = snapshot_builder.build_current_industry_snapshots()

        self.assertEqual(["工业金属", "白色家电"], [row["industry_level_2_name"] for row in rows])
        self.assertEqual(2, len(rows))

    def test_write_current_industry_snapshots_also_writes_archive_snapshot_for_trading_day(self) -> None:
        from app.relative_valuation import snapshot_builder

        rows = [
            {
                "trading_day": "2026-04-30",
                "industry_level_2_name": "白色家电",
                "weighted_pe_ttm": 16.8,
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = snapshot_builder.Path(tmpdir) / "dataset_industry_valuation_current.json"
            archive_root = snapshot_builder.Path(tmpdir) / "archive"
            with mock.patch.object(snapshot_builder, "build_current_industry_snapshots", return_value=rows):
                written_path = snapshot_builder.write_current_industry_snapshots(path=current_path, archive_root=archive_root)

            archive_path = archive_root / "trading_day=2026-04-30" / "snapshots" / "snapshot_industry_relative_valuation_current.json"
            self.assertEqual(current_path, written_path)
            self.assertTrue(archive_path.exists())
            self.assertEqual(rows, json.loads(archive_path.read_text(encoding="utf-8")))
