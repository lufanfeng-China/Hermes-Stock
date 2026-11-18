"""Publication reads enough prehistory for contemporaneous historical ranks."""
import json
from datetime import date, timedelta

import pandas as pd

from scripts import build_stock_filter_turnover_percentile_snapshot as publication


def test_main_publishes_current_json_and_contemporaneous_daily_parquet(tmp_path, monkeypatch):
    final = tmp_path / 'final'
    final.mkdir()
    warehouse = tmp_path / 'quarters'
    warehouse.mkdir()
    start = date(2023, 1, 1)
    days = [start + timedelta(days=i * 2) for i in range(380)]
    pd.DataFrame([{'date': day, 'market': 'sz', 'symbol': '000001',
                   'open': 10., 'close': 10., 'volume': float(100 + i)}
                  for i, day in enumerate(days)]).to_parquet(final / 'qfq.parquet')
    pd.DataFrame([{'trading_day': days[-1].isoformat(), 'market': 'sz',
                   'symbol': '000001'}]).to_parquet(final / 'rps.parquet')
    pd.DataFrame([{'已上市流通A股': 1000., 'announce_date': 20221201}],
                 index=pd.Index(['000001'], name='code')).to_parquet(warehouse / '2022A.parquet')
    monkeypatch.setattr(publication, 'FINAL', final)
    monkeypatch.setattr(publication, 'WAREHOUSE', warehouse)
    monkeypatch.setattr(publication, 'QFQ', final / 'qfq.parquet')
    monkeypatch.setattr(publication, 'RPS', final / 'rps.parquet')
    monkeypatch.setattr(publication, 'OUTPUT', final / 'current.json')
    publication.main()
    current = json.loads((final / 'current.json').read_text())
    history = pd.read_parquet(final / current['daily_audit_file'])
    assert current['schema_version'].endswith('v2')
    assert current['stocks']['sz:000001']['turnover_percentile_1y'] == 100.0
    assert history.iloc[0]['eligible_window_count'] >= 120
    assert pd.notna(history.iloc[0]['rolling_percentile'])
    assert history.iloc[-1]['rolling_percentile'] == 100.0
    assert current['daily_audit_rows'] == len(history)
