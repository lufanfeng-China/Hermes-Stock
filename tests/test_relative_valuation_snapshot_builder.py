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

    def test_build_current_industry_snapshots_reports_progress_and_continues_failed_industries(self) -> None:
        from app.relative_valuation import snapshot_builder

        industry_rows = [
            {"industry_level_2_name": "白色家电"},
            {"industry_level_2_name": "消费电子"},
            {"industry_level_2_name": "工业金属"},
        ]
        events: list[dict[str, object]] = []

        def fake_build(name: str):
            if name == "消费电子":
                raise RuntimeError("mock valuation input failed")
            return {
                "industry_level_2_name": name,
                "trading_day": "2026-04-30",
                "member_valuation_rows": [
                    {"market": "sz", "symbol": "000001", "pe_ttm": 8.0, "ps_ttm": 1.2},
                    {"market": "sz", "symbol": "000002", "pe_ttm": 9.0, "ps_ttm": 1.3},
                ],
                "percentile_samples": {"pe_ttm|A_NORMAL_EARNING": [8.0, 9.0]},
            }

        with (
            mock.patch.object(snapshot_builder, "load_industry_rows", return_value=industry_rows),
            mock.patch.object(snapshot_builder, "build_industry_snapshot_for_industry", side_effect=fake_build),
        ):
            rows = snapshot_builder.build_current_industry_snapshots(progress_callback=events.append)

        self.assertEqual(["工业金属", "白色家电"], [row["industry_level_2_name"] for row in rows])
        self.assertEqual("start", events[0]["event"])
        self.assertEqual(3, events[0]["total_industries"])
        failed_events = [event for event in events if event.get("event") == "industry_failed"]
        self.assertEqual(1, len(failed_events))
        self.assertEqual("消费电子", failed_events[0]["industry_level_2_name"])
        self.assertIn("mock valuation input failed", str(failed_events[0]["error"]))
        done_events = [event for event in events if event.get("event") == "industry_done"]
        self.assertEqual([2, 2], [event.get("member_valuation_row_count") for event in done_events])
        complete_event = events[-1]
        self.assertEqual("complete", complete_event["event"])
        self.assertEqual(2, complete_event["success_count"])
        self.assertEqual(1, complete_event["failure_count"])
        self.assertEqual(4, complete_event["total_member_valuation_rows"])

    def test_build_current_industry_snapshots_can_reuse_complete_existing_snapshots(self) -> None:
        from app.relative_valuation import snapshot_builder

        industry_rows = [
            {"industry_level_2_name": "白色家电"},
            {"industry_level_2_name": "工业金属"},
        ]
        existing_rows = [
            {
                "industry_level_2_name": "白色家电",
                "trading_day": "2026-04-30",
                "temperature_history_since_2022": [{"trading_day": "2026-03-31", "weighted_pe_ttm": 12.0}],
                "percentile_samples": {"pe_ttm|A_NORMAL_EARNING": [10.0]},
                "member_valuation_rows": [{"market": "sz", "symbol": "000001", "pe_ttm": 8.0, "ps_ttm": 1.2}],
            }
        ]
        events: list[dict[str, object]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            existing_path = snapshot_builder.Path(tmpdir) / "current.json"
            existing_path.write_text(json.dumps(existing_rows, ensure_ascii=False), encoding="utf-8")
            with (
                mock.patch.object(snapshot_builder, "load_industry_rows", return_value=industry_rows),
                mock.patch.object(snapshot_builder, "build_industry_snapshot_for_industry", return_value={
                    "industry_level_2_name": "工业金属",
                    "trading_day": "2026-04-30",
                    "temperature_history_since_2022": [],
                    "percentile_samples": {"pe_ttm|A_NORMAL_EARNING": [9.0]},
                    "member_valuation_rows": [{"market": "sz", "symbol": "002160", "pe_ttm": 34.7, "ps_ttm": 0.6}],
                }) as build_mock,
            ):
                rows = snapshot_builder.build_current_industry_snapshots(
                    progress_callback=events.append,
                    reuse_existing_complete=True,
                    existing_path=existing_path,
                )

        self.assertEqual(["工业金属", "白色家电"], [row["industry_level_2_name"] for row in rows])
        build_mock.assert_called_once_with("工业金属")
        skipped_events = [event for event in events if event.get("event") == "industry_skipped"]
        self.assertEqual(1, len(skipped_events))
        self.assertEqual("白色家电", skipped_events[0]["industry_level_2_name"])
        self.assertEqual(1, skipped_events[0]["member_valuation_row_count"])

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
