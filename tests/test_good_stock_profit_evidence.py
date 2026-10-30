from app.undervaluation import service


def test_list_preserves_profit_direction_evidence_and_missing_reasons(monkeypatch):
    change={'current':-20,'previous':-10,'delta':-10,'yoy_pct':-100,'direction':'deteriorating','label':'亏损扩大','current_period':'2026Q3','previous_period':'2025Q3'}
    payload={'stocks':[{'market':'sz','symbol':'002230','margin':{'status':'UNAVAILABLE'},'quarterly_momentum':{'status':'NOT_IMPROVING','evidence':{'profit_change':change},'reasons':['profit_deteriorating']}}]}
    monkeypatch.setattr(service,'_current_diagnosis_snapshot',lambda:payload)
    monkeypatch.setattr(service,'_load_price_percentile_records',lambda:{})
    row=service.load_current_diagnosis_list(category='evidence_unavailable')['rows'][0]
    assert row['quarterly_profit_change']==change
    assert row['quarterly_momentum_reasons']==['profit_deteriorating']
