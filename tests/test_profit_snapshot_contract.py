from app.stock_filter_snapshot import build_strict_financial_record
from app.financial.quarterly_monitor import build_quarterly_financial_monitor
from app.undervaluation.quarterly_momentum import evaluate_quarterly_momentum
import pytest


@pytest.mark.parametrize('industry,missing',[(None,None),('银行',None),('计算机','2025A'),('计算机','2025Q3')])
def test_unavailable_monitor_keeps_latest_profit_evidence(industry,missing):
    rows=[row for row in reports() if row['period']!=missing]
    monitor=build_quarterly_financial_monitor(rows,industry)
    assert monitor['status']!='available'
    assert monitor['latest_period']=='2026Q3'
    change=monitor['profit_comparisons']['ex_net_profit']
    assert change['current']==-20
    assert change['previous']==(None if missing=='2025Q3' else -10)
    assert change['direction']==('unavailable' if missing=='2025Q3' else 'deteriorating')
    momentum=evaluate_quarterly_momentum(monitor)
    assert momentum['status']=='UNAVAILABLE'
    assert momentum['evidence']['profit_change']==change


def reports():
    return [{'period':p,'report_date':p[:4]+('1231' if p.endswith('A') else '0930'),'metrics':{'revenue':r,'ex_net_profit':n,'gross_margin':20,'net_margin':-10}} for p,r,n in [('2025Q3',100,-10),('2025A',130,5),('2026Q3',120,-20)]]


def test_snapshot_preserves_identical_monitor_and_momentum_profit_evidence():
    row=build_strict_financial_record(reports(),industry_level_1='计算机',annual_anchor='2025A',quarterly_anchor='2026Q3')
    evidence=row['quarterly']['profit_comparisons']['ex_net_profit']
    assert evidence==row['quarterly_momentum']['evidence']['profit_change']
    assert evidence['direction']=='deteriorating'
    assert evidence['yoy_pct']==-100


def test_missing_profit_label_distinguishes_missing_data_from_zero_base():
    rows=reports()
    rows[-1]['metrics']['ex_net_profit']=None
    change=build_quarterly_financial_monitor(rows,'计算机')['profit_comparisons']['ex_net_profit']
    assert change['label']=='数据不足'
    assert change['direction']=='unavailable'


def test_revised_profit_calculation_has_distinct_versions():
    monitor=build_quarterly_financial_monitor(reports(),'计算机')
    assert monitor['realtime_score']['version']=='quarterly-v2-profit-direction'
    assert evaluate_quarterly_momentum(monitor)['version']=='good-stock-quarterly-momentum-v2-profit-direction'
