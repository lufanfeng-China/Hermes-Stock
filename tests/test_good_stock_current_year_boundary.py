"""Daily refresh must retain the newest available annual base across January."""
import pandas as pd
from scripts import build_good_stock_financial_snapshot as builder


def test_new_year_without_new_annual_keeps_last_available_five_annuals(tmp_path, monkeypatch):
    warehouse=tmp_path/'warehouse';warehouse.mkdir()
    for year in range(2021,2026):
        pd.DataFrame({'announce_date':[int(f'{year+1}0430')], '资产总计':[1000.0]},index=['600000']).to_parquet(warehouse/f'{year}A.parquet')
    monkeypatch.setattr(builder,'ROOT',tmp_path)
    monkeypatch.setattr(builder,'WAREHOUSE',warehouse)
    monkeypatch.setattr(builder,'_market_map',lambda:{'600000':'sh'})
    monkeypatch.setattr(builder,'_industry_map',lambda:{('sh','600000'):('机械设备','通用设备')})
    result=builder.build_snapshot('2027-01-02')
    assert result['annual_anchor']=='2025A'
    assert result['annual_periods']==['2021A','2022A','2023A','2024A','2025A']
    assert result['stocks']['sh:600000']['latest_report_period']=='2025A'
