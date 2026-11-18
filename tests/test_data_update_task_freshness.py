import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import handler
from app.pipeline.task_freshness import task_freshness


class TaskFreshnessTests(unittest.TestCase):
    def test_published_dates_not_build_times_or_upstream_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / 'datasets' / 'final'
            final.mkdir(parents=True)
            cache = root / 'cache'
            cache.mkdir()
            (cache / 'tdx_qfq_export_sync.json').write_text(json.dumps({'latest_trading_day': '2026-10-30', 'synced_at': '2026-11-03T12:00:00'}))
            (final / 'market_relative_strength_current.json').write_text(json.dumps({'as_of_date': '2026-10-28', 'built_at': '2026-11-03'}))
            (final / 'dataset_concept_temperature_current.json').write_text(json.dumps({'as_of_date': '2026-10-29', 'generated_at': '2026-11-03'}))
            (final / 'dataset_macd_signals_current.json').write_text(json.dumps([{'generated_at': '2026-11-03T12:00:00'}]))
            (final / 'financial_snapshot_2026Q3.json').write_text(json.dumps({'report_date': '2026Q3'}))
            (final / 'dataset_stock_industry_current.json').write_text(json.dumps([{'trading_day': '2026-10-30'}]))
            (final / 'dataset_industry_metric_peers_current.json').write_text(json.dumps({'quarter_anchor': '2026Q2', 'built_at': '2026-11-03'}))
            self.assertEqual('2026-10-30', task_freshness('sync_tdx_qfq_exports', root)['data_date'])
            self.assertEqual('2026-10-28', task_freshness('build_market_relative_strength', root)['data_date'])
            self.assertEqual('2026-10-29', task_freshness('build_concept_temperature', root)['data_date'])
            self.assertIsNone(task_freshness('rebuild_macd_signals', root)['data_date'])
            self.assertEqual('2026-09-30', task_freshness('build_financial_snapshot', root)['data_date'])
            self.assertEqual('报告期截至', task_freshness('build_industry_metric_snapshot', root)['label'])
            self.assertEqual('2026-10-30', task_freshness('refresh_industry_membership', root)['data_date'])

    def test_file_content_change_invalidates_even_same_size_fast_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'cache' / 'tdx_qfq_export_sync.json'
            path.parent.mkdir()
            path.write_text('{"latest_trading_day":"2026-10-29"}')
            self.assertEqual('2026-10-29', task_freshness('sync_tdx_qfq_exports', root)['data_date'])
            path.write_text('{"latest_trading_day":"2026-10-30"}')
            self.assertEqual('2026-10-30', task_freshness('sync_tdx_qfq_exports', root)['data_date'])

    def test_unknown_when_missing_invalid_or_unmapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / 'datasets' / 'final'
            final.mkdir(parents=True)
            (final / 'wyckoff_signals_current.json').write_text('{"as_of_date":"garbage"}')
            self.assertIsNone(task_freshness('build_wyckoff_snapshot', root)['data_date'])
            self.assertIsNone(task_freshness('nonexistent', root)['data_date'])
            self.assertIsNone(task_freshness('refresh_rps_daily', root)['data_date'])

    def test_plan_each_task_has_uniform_freshness(self):
        request = Mock()
        with patch.object(handler, '_data_update_job_snapshot', return_value={}):
            handler.StockDashboardHandler.handle_data_update_plan(request)
        _, payload = request.respond_json.call_args.args
        for task in payload['tasks']:
            self.assertIn('data_freshness', task)
            self.assertEqual({'data_date', 'label'}, set(task['data_freshness']))

    def test_page_shows_dates_in_title_row_without_replacing_status(self):
        page = (Path(__file__).resolve().parents[1] / 'web' / 'data-update.html').read_text()
        self.assertIn('class="task-freshness${', page)
        self.assertIn('task-title-line', page)
        self.assertIn('t.data_freshness', page)
        self.assertIn('数据日期未知', page)
        self.assertIn('class="task-time"', page)
        self.assertNotIn('id="rps-date"', page)
        self.assertNotIn('id="freshness-grid"', page)
        self.assertNotIn('renderFreshness(', page)


if __name__ == '__main__':
    unittest.main()
