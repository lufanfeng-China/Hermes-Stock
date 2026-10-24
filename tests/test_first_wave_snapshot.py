import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class FirstWaveSnapshotTest(unittest.TestCase):
    def test_failed_history_builder_clears_lock_and_publishes_failure(self):
        from scripts import build_first_wave_snapshot as builder
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory)
            lock = history / '2026-10-18.building'
            lock.touch()
            with patch.object(builder, 'HISTORY', history), patch.object(builder, 'ASSET', history / 'missing.parquet'), patch('sys.argv', ['build', '--trading-day', '2026-10-18']):
                with self.assertRaises((SystemExit, FileNotFoundError)):
                    builder.main()
            self.assertFalse(lock.exists())
            failure = json.loads((history / '2026-10-18.error.json').read_text())
            self.assertEqual(builder.SCHEMA_VERSION, failure['schema_version'])
            self.assertIn('missing', failure['message'])

    def test_response_reports_failed_history_and_allows_next_query_to_retry(self):
        from app import first_wave_snapshot as snapshots
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory)
            failure = history / '2026-10-18.error.json'
            failure.write_text(json.dumps({'schema_version': snapshots.SCHEMA_VERSION, 'message': 'not an available QFQ trading day'}))
            with patch.object(snapshots, 'HISTORY', history), patch.object(snapshots.subprocess, 'Popen') as launch:
                result = snapshots.response('2026-10-18')
                self.assertEqual('historical_snapshot_failed', result['error']['code'])
                launch.assert_not_called()
                self.assertFalse(failure.exists())
                retry = snapshots.response('2026-10-18')
                self.assertEqual('historical_snapshot_building', retry['error']['code'])
                launch.assert_called_once()

    def test_response_only_shows_new_eligible_group_without_old_score_ranking(self):
        from app.first_wave_snapshot import response_from_rows
        rows = [
            {"classification": "FIRST_WAVE_ELIGIBLE", "market": "sz", "symbol": "000002"},
            {"classification": "FIRST_WAVE_ELIGIBLE", "market": "sz", "symbol": "000001"},
            {"classification": "FIRST_WAVE_WATCH", "market": "sh", "symbol": "600001"},
            {"classification": "REBASE_REVIEW", "market": "sh", "symbol": "600002"},
        ]
        result = response_from_rows(rows, as_of_date="2026-10-16", data_date="2026-10-16", historical=False)
        self.assertEqual(["000001", "000002"], [x["symbol"] for x in result["groups"]["main"]])
        self.assertEqual({"main": 2}, result["counts"])
        self.assertEqual({"main"}, set(result["groups"]))
        self.assertEqual("first-wave-start-v5-20d-4x", result["schema_version"])

    def test_old_historical_snapshot_is_rebuilt_instead_of_serving_legacy_rules(self):
        from app import first_wave_snapshot as snapshots
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory)
            (history / "2026-10-16.json").write_text(json.dumps({"schema_version": "first-wave-start-v4-20d-no-ma", "as_of_date": "2026-10-16", "rows": []}))
            with patch.object(snapshots, 'HISTORY', history), patch.object(snapshots.subprocess, 'Popen') as launch:
                result = snapshots.response('2026-10-16')
            self.assertFalse(result['ok'])
            self.assertEqual('historical_snapshot_building', result['error']['code'])
            launch.assert_called_once()
            self.assertTrue((history / '2026-10-16.building').exists())


if __name__ == '__main__':
    unittest.main()
