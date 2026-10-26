"""Regression contract for retiring the two external governance features."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import handler
from app.pipeline import runner

ROOT=Path(__file__).resolve().parents[1]
RETIRED={'update_company_pledge','update_related_transactions'}

class ExternalGovernanceRetirementTests(unittest.TestCase):
    def test_analysis_page_and_report_no_longer_expose_overlay(self):
        for name in ['web/stock-analysis.html','web/stock-analysis.js','app/financial/reports.py']:
            text=(ROOT/name).read_text()
            for token in ['governance-risk','governance_risk','renderGovernanceRisk','治理调整','大股东质押风险','关联销售依赖风险']:
                with self.subTest(file=name,token=token):self.assertNotIn(token,text)

    def test_update_surface_has_no_retired_registry_or_metadata(self):
        for name in ['app/handler.py','app/pipeline/commands.py','app/pipeline/runner.py','web/data-update.html']:
            text=(ROOT/name).read_text()
            for token in ['company_pledge','related_transactions','external_risk','pledge-date','related-date','_manual_data_update_commands']:
                with self.subTest(file=name,token=token):self.assertNotIn(token,text)

    def test_dedicated_implementation_docs_and_old_tests_are_removed(self):
        for name in ['app/financial/governance_risk.py','app/data/external_risk_updates.py','app/data/related_trade_partitions.py','scripts/update_external_risk.py','docs/governance-risk.md','docs/external-risk-updates.md','tests/test_governance_risk.py','tests/test_governance_risk_ui.py','tests/test_governance_parent_acceptance.py','tests/test_governance_report_integration.py','tests/test_governance_decimal_boundaries.py','tests/test_external_risk_updates.py','tests/test_external_risk_cli_output.py','tests/test_external_update_tasks.py','tests/test_related_monthly_updates.py']:
            with self.subTest(file=name):self.assertFalse((ROOT/name).exists())

    def test_plan_only_keeps_surviving_tasks_and_single_task_metadata(self):
        req=Mock()
        with patch.object(handler,'load_data_update_status',return_value={}),patch.object(handler,'_latest_trading_day_for_refresh',return_value=None),patch.object(handler,'_data_update_job_snapshot',return_value={'status':'idle','mode':'single_task','task_name':'refresh_rps_daily','task_states':{}}):
            handler.StockDashboardHandler.handle_data_update_plan(req)
        payload=req.respond_json.call_args.args[1]
        self.assertFalse(RETIRED.intersection(t['id'] for t in payload['tasks']))
        self.assertNotIn('company_pledge',payload['current_status'])
        self.assertNotIn('related_transactions',payload['current_status'])
        self.assertEqual('single_task',payload['job']['mode'])
        self.assertEqual('refresh_rps_daily',payload['job']['task_name'])
        self.assertTrue({'refresh_rps_daily','update_financial_ts','build_financial_snapshot'}.issubset(t['id'] for t in payload['tasks']))

    def test_retired_task_ids_cannot_execute_any_command(self):
        for name in RETIRED:
            with self.subTest(task=name),patch.object(runner,'_latest_trading_day_for_refresh',return_value=None),patch.object(runner,'_update_data_update_job_state'),patch.object(runner,'_run_data_update_command',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as execute:
                with self.assertRaises(ValueError):runner.run_data_update_task(name)
                execute.assert_not_called()

    def test_failed_single_task_retry_targets_only_that_task(self):
        for name in ['refresh_rps_daily','update_financial_ts']:
            with self.subTest(task=name),patch.object(runner,'_data_update_job_snapshot',return_value={'mode':'single_task','status':'failed','task_name':name}),patch.object(runner,'start_data_update_task',return_value={'ok':True}) as start,patch.object(runner,'DATA_UPDATE_LOCK'),patch.object(runner,'_update_data_update_job_state'),patch.object(runner.threading,'Thread') as thread:
                result=runner.start_data_update_job(retry_failed=True)
                self.assertTrue(result['ok']);start.assert_called_once_with(name);thread.assert_not_called()

    def test_unknown_failed_single_task_retry_does_not_start_other_tasks(self):
        with patch.object(runner,'_data_update_job_snapshot',return_value={'mode':'single_task','status':'failed','task_name':'unknown_removed_task'}),patch.object(runner,'_latest_trading_day_for_refresh',return_value=None),patch.object(runner,'DATA_UPDATE_LOCK'),patch.object(runner,'_update_data_update_job_state'),patch.object(runner.threading,'Thread') as thread:
            result=runner.start_data_update_job(retry_failed=True)
        self.assertFalse(result['ok']);self.assertEqual('unsupported_task',result['error']['code']);thread.assert_not_called()

    def test_regular_single_task_execution_remains_supported(self):
        with patch.object(runner,'_latest_trading_day_for_refresh',return_value=None),patch.object(runner,'_update_data_update_job_state'),patch.object(runner,'clear_runtime_data_caches'),patch.object(runner,'_load_rps_history_dataset'),patch.object(runner,'_load_rps_trading_days'),patch.object(runner,'_load_stock_rps_history_dataset'),patch.object(runner,'_run_data_update_command',return_value=SimpleNamespace(returncode=0,stdout='ok',stderr='')) as execute:
            result=runner.run_data_update_task('refresh_rps_daily')
        self.assertTrue(result['ok']);self.assertEqual('refresh_rps_daily',execute.call_args.args[0])

if __name__=='__main__':unittest.main()
