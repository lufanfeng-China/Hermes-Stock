"""Data-update ETA uses measured successful durations, never fixed guesses."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from app.pipeline.task_eta import load_duration_history, record_success_duration, task_estimates

TZ = timezone(timedelta(hours=8))


class TaskEtaTests(unittest.TestCase):
    def test_idle_and_first_run_have_no_fabricated_clock_time(self):
        ids = ['a', 'b']
        result = task_estimates(ids, {'running': False, 'task_states': {}}, {'a': [540, 660]},
                                now=datetime(2026, 10, 30, 9, 0, tzinfo=TZ))
        self.assertIsNone(result['a']['finish_at'])
        self.assertEqual('not_started', result['a']['state'])
        self.assertEqual(600, result['a']['duration_seconds'])
        self.assertIsNone(result['b']['finish_at'])
        self.assertEqual(0, result['b']['samples'])

    def test_running_and_full_queue_use_median_and_current_step(self):
        result = task_estimates(['a', 'b', 'c'], {
            'running': True, 'mode': 'full', 'current_step': 'a',
            'task_states': {'a': {'status': 'running', 'started_at': '2026-10-30T10:00:00+08:00'}},
        }, {'a': [540, 660], 'b': [300], 'c': []},
            now=datetime(2026, 10, 30, 10, 2, tzinfo=TZ))
        self.assertEqual('2026-10-30T10:10:00+08:00', result['a']['finish_at'])
        self.assertEqual('2026-10-30T10:15:00+08:00', result['b']['finish_at'])
        self.assertIsNone(result['c']['finish_at'])
        self.assertEqual('no_history', result['c']['state'])

    def test_finished_current_step_must_not_keep_running_forecast(self):
        result = task_estimates(['a', 'b'], {
            'running': True, 'mode': 'full', 'current_step': 'a',
            'task_states': {'a': {'status': 'done', 'started_at': '2026-10-30T10:00:00+08:00',
                                  'finished_at': '2026-10-30T10:04:00+08:00'}},
        }, {'a': [600], 'b': [300]}, now=datetime(2026, 10, 30, 10, 4, tzinfo=TZ))
        self.assertEqual('done', result['a']['state'])
        self.assertIsNone(result['a']['finish_at'])
        self.assertIsNone(result['b']['finish_at'])

    def test_overdue_or_missing_predecessor_blocks_queue_forecast(self):
        job = {'running': True, 'mode': 'full', 'current_step': 'a',
               'task_states': {'a': {'status': 'running', 'started_at': '2026-10-30T10:00:00+08:00'}}}
        overdue = task_estimates(['a', 'b'], job, {'a': [600], 'b': [300]},
                                 now=datetime(2026, 10, 30, 10, 11, tzinfo=TZ))
        self.assertEqual('overdue', overdue['a']['state'])
        self.assertIsNone(overdue['b']['finish_at'])
        missing = task_estimates(['a', 'b'], job, {'b': [300]},
                                 now=datetime(2026, 10, 30, 10, 2, tzinfo=TZ))
        self.assertIsNone(missing['a']['finish_at'])
        self.assertIsNone(missing['b']['finish_at'])

    def test_successful_durations_persist_and_failures_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            self.assertFalse(record_success_duration('x', '2026-10-30 10:00:00',
                                                     '2026-10-30 09:59:59', path=path))
            self.assertTrue(record_success_duration('x', '2026-10-30 10:00:00',
                                                    '2026-10-30 10:04:00', path=path))
            self.assertEqual({'x': [240]}, load_duration_history(path))
            self.assertEqual([240], json.loads(path.read_text())['x'])

    def test_completed_step_records_duration_before_running_state_is_replaced(self):
        from app.pipeline import runner
        state = {'task_states': {'x': {'status': 'running', 'started_at': '2026-10-30 10:00:00'}}}
        with patch.object(runner, 'DATA_UPDATE_JOB_STATE', state), \
             patch.object(runner, 'record_success_duration') as record, \
             patch.object(runner, '_format_timestamp', return_value='2026-10-30 10:04:00'), \
             patch.object(runner, '_update_data_update_job_state'):
            runner._record_step_result({'name': 'x', 'ok': True})
        record.assert_called_once_with('x', '2026-10-30 10:00:00', '2026-10-30 10:04:00')

    def test_failed_step_does_not_enter_duration_history(self):
        from app.pipeline import runner
        state = {'task_states': {'x': {'status': 'running', 'started_at': '2026-10-30 10:00:00'}}}
        with patch.object(runner, 'DATA_UPDATE_JOB_STATE', state), \
             patch.object(runner, 'record_success_duration') as record, \
             patch.object(runner, '_update_data_update_job_state'):
            runner._record_step_result({'name': 'x', 'ok': False, 'stderr_tail': 'failed'})
        record.assert_not_called()

    def test_page_and_plan_share_estimate_contract(self):
        from app import handler
        request = Mock()
        with patch.object(handler, '_data_update_job_snapshot', return_value={}), \
             patch.object(handler, 'load_duration_history', return_value={}):
            handler.StockDashboardHandler.handle_data_update_plan(request)
        _, payload = request.respond_json.call_args.args
        self.assertTrue(all('estimated_completion' in task for task in payload['tasks']))
        page = (Path(__file__).resolve().parents[1] / 'web' / 'data-update.html').read_text()
        self.assertIn('t.estimated_completion', page)
        self.assertIn('预计完成', page)


if __name__ == '__main__':
    unittest.main()
