import importlib.util
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def builder():
    spec = importlib.util.spec_from_file_location('good_financial', ROOT / 'scripts/build_good_stock_financial_snapshot.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_select_latest_incomplete_quarter_not_older_complete_report():
    mod = builder()
    frames = {
        '2026Q2': pd.DataFrame([{'资产总计': 100, '其中：营业收入': 20, 'announce_date': 20260801}], index=['000001']),
        '2026Q3': pd.DataFrame([{'资产总计': 100, '其中：营业收入': None, 'announce_date': 20261020}], index=['000001']),
    }
    reports, evidence = mod.select_reports(frames, '000001', '2026-10-30')
    assert evidence['latest_report_period'] == '2026Q3'
    assert reports[-1]['metrics']['revenue'] is None


def test_snapshot_loaders_reload_atomic_replacement(tmp_path, monkeypatch):
    import json
    from app.undervaluation import service
    for name, loader in [('STRICT_SNAPSHOT', service._strict_snapshot), ('CURRENT_DIAGNOSIS_SNAPSHOT', service._current_diagnosis_snapshot), ('PRICE_PERCENTILE_SNAPSHOT', service._load_price_percentile_records)]:
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps({'version': 1}))
        monkeypatch.setattr(service, name, path)
        loader.cache_clear()
        assert loader()['version'] == 1
        temporary = path.with_suffix('.new')
        temporary.write_text(json.dumps({'version': 222}))
        temporary.replace(path)
        assert loader()['version'] == 222
        loader.cache_clear()

def test_future_placeholder_loss_zero_and_missing_dates():
    mod = builder()
    frames = {
        '2026Q1': pd.DataFrame([{'资产总计': 100, '其中：营业收入': 0, '归属于母公司所有者的净利润': -1, 'announce_date': 20260430}], index=['000001']),
        '2026Q2': pd.DataFrame([{'资产总计': 0, '其中：营业收入': 0, '归属于母公司所有者的净利润': 0, '总股本': 100, 'announce_date': 20260820}], index=['000001']),
        '2026Q3': pd.DataFrame([{'资产总计': 100, 'announce_date': 20261101}], index=['000001']),
    }
    reports, evidence = mod.select_reports(frames, '000001', '2026-10-30')
    assert evidence['latest_report_period'] == '2026Q1'
    assert reports[-1]['metrics']['revenue'] == 0
    assert reports[-1]['metrics']['net_profit'] == -1
    frames['2026Q3'].loc['000001', 'announce_date'] = None
    reports, evidence = mod.select_reports(frames, '000001', '2026-10-30')
    assert evidence['latest_report_period'] == '2026Q3'
    assert evidence['latest_announce_date'] is None
    assert evidence['availability_status'] == 'announcement_date_unknown_pending_verification'


def test_build_preserves_union_annual_track_and_latest_quarter(tmp_path, monkeypatch):
    mod = builder()
    for year in range(2021, 2026):
        pd.DataFrame([{"资产总计": 100, "其中：营业收入": 20}], index=["000001"]).to_parquet(tmp_path / f"{year}A.parquet")
    pd.DataFrame([{"资产总计": 100}], index=["000002"]).to_parquet(tmp_path / "2026Q2.parquet")
    pd.DataFrame([{"资产总计": 100}], index=["000002"]).to_parquet(tmp_path / "2026Q3.parquet")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "WAREHOUSE", tmp_path)
    monkeypatch.setattr(mod, "_market_map", lambda: {"000001": "sz", "000002": "sz"})
    monkeypatch.setattr(mod, "_industry_map", lambda: {("sz", "000001"): ("化工", "化工"), ("sz", "000002"): ("化工", "化工")})
    result = mod.build_snapshot("2026-10-30")
    assert len(result["stocks"]) == 2
    annual = result["stocks"]["sz:000001"]
    assert annual["latest_report_period"] == "2025A"
    assert annual["quarterly_momentum"]["status"] == "UNAVAILABLE"
    assert annual["quarterly_momentum"]["period"] is None
    assert annual["annual"]["periods"] == result["annual_periods"]
    quarter = result["stocks"]["sz:000002"]
    assert quarter["quarterly_momentum"]["period"] == "2026Q3"
    assert quarter["quarterly_momentum"]["status"] == "UNAVAILABLE"

def test_list_carries_financial_evidence_and_source_metadata(monkeypatch):
    from app.undervaluation import service
    payload = {"stocks": [{"symbol": "000001", "margin": {"status": "HAS_MARGIN"}, "latest_report_period": "2026Q3", "latest_announce_date": "2026-10-28", "financial_evidence": {"selection_reason": "latest"}}], "source_metadata": {"financial_as_of": "2026-10-30"}}
    monkeypatch.setattr(service, "_current_diagnosis_snapshot", lambda: payload)
    monkeypatch.setattr(service, "_load_price_percentile_records", lambda: {})
    result = service.load_current_diagnosis_list()
    assert result["source_metadata"] == payload["source_metadata"]
    assert result["rows"][0]["latest_report_period"] == "2026Q3"
    assert result["rows"][0]["latest_announce_date"] == "2026-10-28"


def test_missing_industry_is_complete_unavailable_diagnosis_not_dropped(monkeypatch):
    from app.undervaluation import service
    import app.relative_valuation.data_loader as loader
    monkeypatch.setattr(service, "_strict_snapshot", lambda: {"stocks": {"sz:000004": {"good_stock_quality": {"status": "QUALITY_ELIGIBLE", "eligible": True}, "latest_report_period": "2026Q1"}}})
    monkeypatch.setattr(loader, "load_stock_relative_valuation_inputs", lambda *args: {})
    monkeypatch.setattr(service, "load_industry_valuation_snapshot", lambda *args: {})
    result = service.build_current_diagnosis("sz", "000004")
    assert result["ok"] is True
    assert result["margin"]["status"] == "UNAVAILABLE"
    assert result["latest_report_period"] == "2026Q1"
