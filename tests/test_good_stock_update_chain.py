import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app.pipeline import commands, runner
from app.pipeline.state import DATA_UPDATE_JOB_STATE
from app import handler

FIN = 'build_good_stock_financial_snapshot'
DIAG = 'build_good_stock_undervaluation_current'

class GoodStockUpdateChainTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(DATA_UPDATE_JOB_STATE)
        DATA_UPDATE_JOB_STATE.clear()
    def tearDown(self):
        DATA_UPDATE_JOB_STATE.clear(); DATA_UPDATE_JOB_STATE.update(self.old)
    def test_declared_order_retry_and_plan(self):
        declared = commands._data_update_commands(None)
        ids = [x[0] for x in declared]
        self.assertIn(FIN, ids)
        for upstream in ['build_stock_filter_qfq_daily', 'update_financial_ts', 'build_industry_relative_valuation_snapshot', FIN]:
            self.assertLess(ids.index(upstream), ids.index(DIAG))
        self.assertLess(ids.index('update_financial_ts'), ids.index(FIN))
        for task in [FIN, DIAG]:
            self.assertEqual(dict(declared)[task][1], str(commands.PROJECT_ROOT / f'scripts/{task}.py'))
            self.assertIn(task, dict(commands._data_update_commands(None, retry_failed=True)))
        request = Mock()
        with patch.object(handler, '_latest_trading_day_for_refresh', return_value=None), patch.object(handler, 'load_data_update_status', return_value={}):
            handler.StockDashboardHandler.handle_data_update_plan(request)
        tasks = request.respond_json.call_args.args[1]['tasks']
        self.assertTrue({FIN, DIAG}.issubset({x['id'] for x in tasks}))
    def test_retry_failed_good_stock_only_does_not_rebuild_unrelated_industry(self):
        DATA_UPDATE_JOB_STATE['task_states'] = {FIN: {'status': 'done'}, DIAG: {'status': 'failed'}}
        with patch.object(runner, '_latest_trading_day_for_refresh', return_value=None), patch.object(runner, '_run_data_update_command', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as run, patch.object(runner, 'clear_runtime_data_caches'):
            runner.run_full_data_update(retry_failed=True)
        self.assertEqual([x.args[0] for x in run.call_args_list], [DIAG])
    def test_timeout_of_good_stock_is_failed_and_does_not_block_technical(self):
        import subprocess
        with patch.object(runner, '_latest_trading_day_for_refresh', return_value=None), patch.object(runner, '_data_update_commands', return_value=[(DIAG,[DIAG]), ('refresh_rps_daily',['rps'])]), patch.object(runner, '_run_data_update_command', side_effect=[subprocess.TimeoutExpired('builder', 1800),SimpleNamespace(returncode=0, stdout='', stderr='')]), patch.object(runner, 'clear_runtime_data_caches'):
            result = runner.run_full_data_update()
        self.assertFalse(result['ok'])
        self.assertFalse(result['steps'][0]['ok'])
        self.assertTrue(result['steps'][1]['ok'])
    def test_full_rerun_replaces_old_done_with_running_before_command(self):
        DATA_UPDATE_JOB_STATE['task_states'] = {DIAG: {'status': 'done'}}
        observed=[]
        def execute(*args, **kw):
            observed.append(DATA_UPDATE_JOB_STATE['task_states'][DIAG]['status'])
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(runner, '_latest_trading_day_for_refresh', return_value=None), patch.object(runner, '_data_update_commands', return_value=[(DIAG,[DIAG])]), patch.object(runner, '_run_data_update_command', side_effect=execute), patch.object(runner, 'clear_runtime_data_caches'):
            runner.run_full_data_update()
        self.assertEqual(observed,['running'])
    def test_cache_clears_undervaluation_service(self):
        module = SimpleNamespace(loader=Mock(cache_clear=Mock()))
        with patch.object(commands.importlib, 'import_module', return_value=module) as load:
            commands.clear_runtime_data_caches()
        self.assertIn('app.undervaluation.service', [x.args[0] for x in load.call_args_list])
    def test_single_task_never_runs_upstream_and_failure_is_explicit(self):
        with patch.object(runner, '_latest_trading_day_for_refresh', return_value=None), patch.object(runner, '_run_data_update_command', return_value=SimpleNamespace(returncode=1, stdout='', stderr='bad source')) as run:
            for task in [FIN, DIAG]:
                with self.assertRaises(runner.DataUpdateStepError):
                    runner.run_data_update_task(task)
                self.assertEqual(run.call_args.args[0], task)
            self.assertEqual(run.call_count, 2)
    def test_failed_financial_skips_diagnosis_but_runs_technical(self):
        calls = []
        def execute(task, *args, **kw):
            calls.append(task)
            return SimpleNamespace(returncode=1 if task == FIN else 0, stdout='', stderr='bad source')
        with patch.object(runner, '_latest_trading_day_for_refresh', return_value=None), patch.object(runner, '_data_update_commands', return_value=[(x,[x]) for x in [FIN, DIAG, 'refresh_rps_daily']]), patch.object(runner, '_run_data_update_command', side_effect=execute), patch.object(runner, 'clear_runtime_data_caches'):
            result = runner.run_full_data_update()
        self.assertEqual(calls, [FIN, 'refresh_rps_daily'])
        self.assertFalse(result['steps'][1]['ok'])
        self.assertEqual(DATA_UPDATE_JOB_STATE['task_states'][DIAG]['status'], 'failed')
    def test_diagnosis_failure_does_not_block_technical_or_report_success(self):
        with patch.object(runner, '_latest_trading_day_for_refresh', return_value=None), patch.object(runner, '_data_update_commands', return_value=[(DIAG,[DIAG]), ('refresh_rps_daily',['rps'])]), patch.object(runner, '_run_data_update_command', side_effect=[SimpleNamespace(returncode=2, stdout='', stderr='bad snapshot'),SimpleNamespace(returncode=0, stdout='', stderr='')]), patch.object(runner, 'clear_runtime_data_caches'):
            runner._run_data_update_worker()
        self.assertEqual(DATA_UPDATE_JOB_STATE['task_states'][DIAG]['status'], 'failed')
        self.assertEqual(DATA_UPDATE_JOB_STATE['task_states']['refresh_rps_daily']['status'], 'done')
        self.assertTrue(DATA_UPDATE_JOB_STATE['can_retry_failed'])
        self.assertEqual(DATA_UPDATE_JOB_STATE['status'], 'failed')
