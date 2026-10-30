"""Identity reads must not recompute unused live valuation/financial inputs."""
from app.undervaluation import service
import app.relative_valuation.data_loader as loader


def test_diagnosis_identity_uses_mapping_without_live_financial_recalculation(monkeypatch):
    monkeypatch.setattr(loader,'_industry_row_lookup',lambda:{('sz','000001'):{'stock_name':'测试股票','industry_level_2_name':'测试行业'}})
    monkeypatch.setattr(loader,'_stock_name_lookup',lambda:{})
    monkeypatch.setattr(service,'_strict_snapshot',lambda:{'stocks':{'sz:000001':{'good_stock_quality':{},'latest_report_period':'2026Q3'}}})
    monkeypatch.setattr(service,'load_industry_valuation_snapshot',lambda name:{})
    def forbidden(*args,**kwargs):
        raise AssertionError('identity-only call must not recompute all valuation inputs')
    monkeypatch.setattr(loader,'load_stock_relative_valuation_inputs',forbidden)
    result=service.build_current_diagnosis('sz','000001')
    assert result['ok'] is True
    assert result['stock_name']=='测试股票'
    assert result['industry_level_2_name']=='测试行业'
