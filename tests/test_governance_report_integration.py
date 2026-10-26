import unittest
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
from app.financial import reports

class GovernanceReportIntegrationTests(unittest.TestCase):
    def test_old_annual_governance_evidence_is_not_latest_and_input_is_unchanged(self):
        import copy
        raw={'related_sales':{'ratio':{'period_end':'2024-12-31','complete':True}}}
        before=copy.deepcopy(raw)
        adjusted=reports._align_governance_annual_period(raw,[{'period':'2025A'},{'period':'2026Q2'}])
        self.assertTrue(adjusted['related_sales']['ratio']['stale'])
        self.assertEqual(raw,before)
        latest={'related_sales':{'ratio':{'period_end':'2025-12-31','complete':True}}}
        self.assertEqual(reports._align_governance_annual_period(latest,[{'period':'2025A'}]),latest)

    def test_report_adds_independent_governance_without_changing_financial_score(self):
        index=SimpleNamespace(_stock_name_lookup=lambda:{('sh','600519'):'TEST'},_pick=lambda v:v,load_industry_rows=lambda:[],_load_financial_snapshot=lambda:{})
        materialized={'report_date':'20251231','period':'2025A','year':'2025','metrics':{}}
        original={'score':72.0,'risk_overlay':{'status':'watch'}}
        result={'complete':False,'original_score':72.0,'adjusted_score':None,'items':[]}
        with ExitStack() as s:
            s.enter_context(patch('app.financial.warehouse_reports.load_symbol_financial_rows',return_value=[{'period':'2025A','row':{'report_date':'20251231'}}]))
            s.enter_context(patch.object(reports,'_materialize_financial_report',return_value=materialized))
            s.enter_context(patch.object(reports,'build_financial_health',return_value={'score':75}))
            s.enter_context(patch.object(reports,'build_quarterly_financial_monitor',return_value={'status':'available'}))
            s.enter_context(patch.object(reports,'build_composite_financial_health',return_value=original))
            s.enter_context(patch.object(reports,'build_financial_reversal_indicator',return_value={}))
            s.enter_context(patch.object(reports,'build_latest_report_release_price_performance',return_value={'performance':{},'trend':{}}))
            s.enter_context(patch.object(reports,'build_industry_financial_position',return_value={}))
            load=s.enter_context(patch.object(reports,'load_governance_evidence',return_value=None,create=True))
            build=s.enter_context(patch.object(reports,'build_governance_risk',return_value=result,create=True))
            s.enter_context(patch.object(reports.importlib,'import_module',return_value=index))
            payload=reports.load_recent_three_year_financial_reports('sh','600519')
        self.assertIn('governance_risk',payload)
        self.assertEqual(payload['governance_risk'],result)
        self.assertEqual(payload['composite_financial_health'],original)
        self.assertEqual(payload['health']['score'],75)
        load.assert_called_once_with('600519')
        build.assert_called_once_with(72.0,None)
