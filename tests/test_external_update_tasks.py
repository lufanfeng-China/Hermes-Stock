import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.pipeline import commands, runner
from app import handler

IDS = {'update_company_pledge', 'update_related_transactions'}

class ExternalTaskTests(unittest.TestCase):
    def test_manual_catalog_is_separate_from_default_and_retry(self):
        manual = dict(commands._manual_data_update_commands())
        self.assertEqual(IDS, set(manual))
        for key, kind in [('update_company_pledge', 'company_pledge'), ('update_related_transactions', 'related_transactions')]:
            self.assertIn('scripts/update_external_risk.py', manual[key][1])
            self.assertEqual(['--dataset', kind], manual[key][2:])
        self.assertFalse(IDS & set(dict(commands._data_update_commands(None))))
        self.assertFalse(IDS & set(dict(commands._data_update_commands(None, retry_failed=True))))

    def test_single_manual_task_does_not_require_tdx_or_clear_technical_caches(self):
        with patch.object(runner, '_run_data_update_command', return_value=SimpleNamespace(returncode=0, stdout='done', stderr='')) as execute, patch.object(runner, '_latest_trading_day_for_refresh') as day, patch.object(runner, 'clear_runtime_data_caches') as clear:
            result = runner.run_data_update_task('update_company_pledge')
        self.assertTrue(result['ok'])
        self.assertEqual('update_company_pledge', execute.call_args.args[0])
        day.assert_not_called()
        clear.assert_not_called()

    def test_retry_after_failed_manual_task_retries_that_task_not_daily_pipeline(self):
        with patch.object(runner, '_data_update_job_snapshot', return_value={'mode':'single_task','status':'failed','task_name':'update_related_transactions'}), patch.object(runner, 'start_data_update_task', return_value={'ok':True}) as start:
            self.assertTrue(runner.start_data_update_job(retry_failed=True)['ok'])
        start.assert_called_once_with('update_related_transactions')

    def test_plan_exposes_manual_tasks_and_durable_metadata(self):
        statuses = {'company_pledge': {'available':True,'row_count':4220,'data_date':'2026-10-23','latest_date_rows':2218,'older_date_rows':2002}, 'related_transactions': {'available':True,'row_count':85705,'company_count':3999,'data_date':'2026-10-24'}}
        request=Mock()
        fake=SimpleNamespace(load_external_risk_status=lambda:statuses)
        with patch.dict(sys.modules, {'app.data.external_risk_updates':fake}), patch.object(handler,'_latest_trading_day_for_refresh',return_value=None), patch.object(handler,'_data_update_job_snapshot',return_value={'status':'succeeded','mode':'single_task','task_name':'update_company_pledge'}):
            handler.StockDashboardHandler.handle_data_update_plan(request)
        _, payload=request.respond_json.call_args.args
        tasks={t['id']:t for t in payload['tasks']}
        self.assertTrue(all(tasks[k]['manual_only'] for k in IDS))
        self.assertIn('公司整体',tasks['update_company_pledge']['name'])
        self.assertEqual(statuses['company_pledge'],payload['current_status']['company_pledge'])
        self.assertEqual(statuses['related_transactions'],payload['current_status']['related_transactions'])
        self.assertEqual('single_task',payload['job']['mode'])
        self.assertEqual('update_company_pledge',payload['job']['task_name'])

    def test_durable_manual_failure_is_retryable_after_server_restart(self):
        request=Mock()
        fake=SimpleNamespace(load_external_risk_status=lambda:{'company_pledge':{'available':True,'error':'source timeout; old snapshot retained'}})
        with patch.dict(sys.modules, {'app.data.external_risk_updates':fake}), patch.object(handler,'_latest_trading_day_for_refresh',return_value=None), patch.object(handler,'_data_update_job_snapshot',return_value={'status':'idle','task_states':{}}):
            handler.StockDashboardHandler.handle_data_update_plan(request)
        payload=request.respond_json.call_args.args[1]
        self.assertEqual('failed',payload['job']['task_states']['update_company_pledge']['status'])
        self.assertFalse(payload['job']['can_retry_failed'])

    def test_page_has_freshness_cards_and_independent_execution_labels(self):
        page=(Path(__file__).parents[1]/'web/data-update.html').read_text()
        for value in ['id="pledge-date"','id="related-date"','status.company_pledge','status.related_transactions','不定期更新','manual_only',"job.mode !== 'single_task'"]:
            self.assertIn(value,page)

if __name__=='__main__':unittest.main()
