"""Turnover trend API uses PIT, published per-day percentiles, never future data."""
import json
from http import HTTPStatus

import pandas as pd

from app import handler
from app.stock_filter_turnover_trend import turnover_trend_response


def _publication(tmp_path):
    day = '2026-11-12'
    filename = f'stock_filter_turnover_daily_{day}.parquet'
    pd.DataFrame([
        {'market': 'sz', 'symbol': '000001', 'date': '2026-11-10',
         'rolling_percentile': 70.0, 'rolling_7_trimmed_avg_pct': 4.0, 'eligible_window_count': 127,
         'turnover': 0.04, 'source': 'report_proxy'},
        {'market': 'sz', 'symbol': '000001', 'date': '2026-11-11',
         'rolling_percentile': 74.0, 'rolling_7_trimmed_avg_pct': 4.2, 'eligible_window_count': 128,
         'turnover': 0.05, 'source': 'report_proxy'},
        {'market': 'sz', 'symbol': '000001', 'date': '2026-11-12',
         'rolling_percentile': 76.0, 'rolling_7_trimmed_avg_pct': 4.5, 'eligible_window_count': 129,
         'turnover': 0.06, 'source': 'report_proxy'},
        {'market': 'sz', 'symbol': '000002', 'date': '2026-11-12',
         'rolling_percentile': 20.0, 'rolling_7_trimmed_avg_pct': 1.0, 'eligible_window_count': 150,
         'turnover': 0.01, 'source': 'report_proxy'},
    ]).to_parquet(tmp_path / filename, index=False)
    (tmp_path / 'stock_filter_turnover_percentile_current.json').write_text(json.dumps({
        'schema_version': 'stock-filter-turnover-percentile-v2',
        'as_of_date': day, 'daily_audit_file': filename,
        'stocks': {'sz:000001': {'turnover_percentile_1y': 76.0,
                                 'turnover_percentile_1y_as_of': day}}
    }), encoding='utf-8')


def test_trend_uses_each_day_published_percentile_and_cuts_future(tmp_path):
    _publication(tmp_path)
    result = turnover_trend_response('sz', '000001', '2026-11-12', final_dir=tmp_path)
    assert result['ok'] is True
    assert [r['date'] for r in result['rows']] == ['2026-11-10', '2026-11-11', '2026-11-12']
    assert [r['percentile'] for r in result['rows']] == [70.0, 74.0, 76.0]
    assert result['rows'][-1]['sample_count'] == 129
    assert result['rows'][-1]['trimmed_average_pct'] == 4.5
    assert result['as_of_date'] == '2026-11-12'


def test_missing_day_or_stale_publication_fails_closed(tmp_path, monkeypatch):
    _publication(tmp_path)
    from app import stock_filter_turnover_trend as trend
    monkeypatch.setattr(trend, 'QFQ_DAILY', tmp_path / 'not_published.parquet')
    assert turnover_trend_response('sz', '000001', '2026-11-09', final_dir=tmp_path)['ok'] is False
    assert turnover_trend_response('sz', '000001', '2026-11-13', final_dir=tmp_path)['ok'] is False
    publication = tmp_path / 'stock_filter_turnover_percentile_current.json'
    payload = json.loads(publication.read_text(encoding='utf-8'))
    payload['schema_version'] = 'stock-filter-turnover-percentile-v1'
    publication.write_text(json.dumps(payload), encoding='utf-8')
    assert turnover_trend_response('sz', '000001', '2026-11-12', final_dir=tmp_path)['ok'] is False


def test_historical_as_of_recomputes_full_year_without_today_rank(tmp_path, monkeypatch):
    _publication(tmp_path)
    from app import stock_filter_turnover_trend as trend
    days = pd.bdate_range('2024-12-02', periods=155)
    history = pd.DataFrame([{'date': day, 'market': 'sz', 'symbol': '000001',
                             'open': 10.0, 'close': 10.0, 'volume': 10000.0}
                            for day in days])
    qfq_path = tmp_path / 'qfq.parquet'
    history.to_parquet(qfq_path, index=False)
    monkeypatch.setattr(trend, 'QFQ_DAILY', qfq_path)
    monkeypatch.setattr(trend, 'read_stock_share_reports', lambda path, symbol: [
        {'period': '2024A', 'announce_date': '2024-11-01', '已上市流通A股': 1000000.0}])
    chosen = days[139].date().isoformat()
    result = turnover_trend_response('sz', '000001', chosen, final_dir=tmp_path)
    assert result['ok'] is True
    assert result['as_of_date'] == chosen
    assert result['rows'][-1]['date'] == chosen
    assert result['rows'][-1]['percentile'] == 100.0
    assert len(result['rows']) == 140
    assert result['rows'][0]['percentile'] is None


def test_published_last_point_must_match_result_table(tmp_path):
    _publication(tmp_path)
    path = tmp_path / 'stock_filter_turnover_percentile_current.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['stocks']['sz:000001']['turnover_percentile_1y'] = 77.0
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert turnover_trend_response('sz', '000001', '2026-11-12', final_dir=tmp_path)['ok'] is False


def test_bad_identity_is_rejected_before_io(tmp_path):
    for market, symbol, day in [('sh', '000001', '2026-11-12'), ('sz', '../etc', '2026-11-12'),
                                 ('sz', '000001', '2026-02-30')]:
        assert turnover_trend_response(market, symbol, day, final_dir=tmp_path)['ok'] is False


def test_handler_get_route_returns_real_trend(tmp_path, monkeypatch):
    _publication(tmp_path)
    from app import stock_filter_turnover_trend
    monkeypatch.setattr(stock_filter_turnover_trend, 'FINAL', tmp_path)
    target = object.__new__(handler.StockDashboardHandler)
    responses = []
    target.respond_json = lambda status, body: responses.append((status, body))
    target.path = '/api/stock-filter-turnover-trend?market=sz&symbol=000001&as_of_date=2026-11-12'
    target.do_GET()
    assert responses[-1][0] == HTTPStatus.OK
    assert responses[-1][1]['rows'][-1]['percentile'] == 76.0
