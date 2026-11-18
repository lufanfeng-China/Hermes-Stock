"""QFQ trend API must return only actual as-of-date Tongdaxin export bars."""
from http import HTTPStatus

import pytest

from app import handler, stock_qfq_trend


def _export(tmp_path, name='SZ#300017.txt', rows=None):
    rows = rows or [
        '2026/11/06\t10\t11\t9\t10.5\t100\t1000',
        '2026/11/09\t11\t12\t10\t11.5\t120\t1200',
        '2026/11/10\t12\t13\t11\t12.5\t140\t1400',
        '2026/11/11\t13\t14\t12\t13.5\t160\t1600',
    ]
    (tmp_path / name).write_text('股票名\n日期\t开盘\t最高\t最低\t收盘\t成交量\t成交额\n' + '\n'.join(rows) + '\n', encoding='gb18030')


def test_qfq_trend_is_ascending_bounded_and_never_includes_future_or_suspension(tmp_path):
    _export(tmp_path, rows=[
        '2026/11/05\t9\t10\t8\t9.5\t90\t900',
        '2026/11/06\t10\t11\t9\t10.5\t100\t1000',
        '2026/11/07\t0\t0\t0\t0\t0\t0',
        '2026/11/09\t11\t12\t10\t11.5\t120\t1200',
        '2026/11/10\t12\t13\t11\t12.5\t140\t1400',
        '2026/11/11\t13\t14\t12\t13.5\t160\t1600',
    ])
    result = stock_qfq_trend.trend_response('sz', '300017', '2026-11-10', limit=2, export_dir=tmp_path)
    assert result == {
        'ok': True, 'market': 'sz', 'symbol': '300017',
        'price_basis': 'tdx_export_qfq', 'as_of_date': '2026-11-10',
        'bars': [
            {'trading_day': '2026-11-09', 'open': 11., 'high': 12., 'low': 10., 'close': 11.5, 'volume': 120.},
            {'trading_day': '2026-11-10', 'open': 12., 'high': 13., 'low': 11., 'close': 12.5, 'volume': 140.},
        ],
    }


def test_missing_export_or_stale_date_is_explicit_failure(tmp_path):
    missing = stock_qfq_trend.trend_response('sz', '300017', '2026-11-10', export_dir=tmp_path)
    assert missing['ok'] is False
    assert missing['error']['code'] == 'qfq_export_unavailable'
    _export(tmp_path)
    stale = stock_qfq_trend.trend_response('sz', '300017', '2026-11-08', export_dir=tmp_path)
    assert stale['ok'] is False
    assert stale['error']['code'] == 'qfq_source_stale'
    assert stale.get('bars') is None


@pytest.mark.parametrize('market,symbol,day,limit,code', [
    ('xx', '300017', '2026-11-10', 300, 'invalid_market'),
    ('sh', '300017', '2026-11-10', 300, 'invalid_market'),
    ('sz', '../foo', '2026-11-10', 300, 'invalid_symbol'),
    ('sz', '300017', '2026-02-30', 300, 'invalid_date'),
    ('sz', '300017', '2026-11-10junk', 300, 'invalid_date'),
    ('sz', '300017', '', 300, 'invalid_date'),
    ('sz', '300017', '2026-11-10', 0, 'invalid_limit'),
    ('sz', '300017', '2026-11-10', 999999, 'invalid_limit'),
])
def test_invalid_parameters_rejected_before_loading(market, symbol, day, limit, code, tmp_path):
    response = stock_qfq_trend.trend_response(market, symbol, day, limit=limit, export_dir=tmp_path)
    assert response['ok'] is False
    assert response['error']['code'] == code


def test_invalid_last_bar_does_not_claim_requested_day(tmp_path):
    _export(tmp_path, rows=[
        '2026/11/09\t11\t12\t10\t11.5\t120\t1200',
        '2026/11/10\t0\t0\t0\t0\t0\t0',
    ])
    response = stock_qfq_trend.trend_response('sz', '300017', '2026-11-10', export_dir=tmp_path)
    assert response['error']['code'] == 'qfq_source_stale'


def test_get_route_returns_400_on_missing_export_and_200_for_real_data(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_qfq_trend, 'TDX_QFQ_EXPORT_DIR', tmp_path)
    target = object.__new__(handler.StockDashboardHandler)
    responses = []
    target.respond_json = lambda status, body: responses.append((status, body))
    target.path = '/api/stock-qfq-trend?market=sz&symbol=300017&as_of_date=2026-11-10&limit=1'
    target.do_GET()
    assert responses[-1][0] == HTTPStatus.BAD_REQUEST
    assert responses[-1][1]['error']['code'] == 'qfq_export_unavailable'
    _export(tmp_path)
    target.do_GET()
    status, body = responses[-1]
    assert status == HTTPStatus.OK
    assert body['bars'] == [{'trading_day': '2026-11-10', 'open': 12., 'high': 13., 'low': 11., 'close': 12.5, 'volume': 140.}]
    target.path = '/api/stock-qfq-trend?market=sz&symbol=300017&as_of_date=2026-11-08'
    target.do_GET()
    assert responses[-1][0] == HTTPStatus.BAD_REQUEST
    assert responses[-1][1]['error']['code'] == 'qfq_source_stale'
