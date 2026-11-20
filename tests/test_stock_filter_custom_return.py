"""User-configurable 1..250 trading-day QFQ return filter."""
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.stock_filter import filter_response
from app.stock_filter_market_snapshot import build_market_metrics

ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-11-19'


def _row(index):
    return {
        'market': 'sz', 'symbol': f'{index:06d}', 'rps_total': float(1000-index),
        'annual_dimensions': {}, 'quarterly_dimensions': {}, 'qfq_as_of': DAY,
    }


def _history(end):
    return [100.0] * 5 + [float(end)]


def test_snapshot_keeps_only_251_latest_valid_qfq_closes_for_dynamic_return():
    closes = [float(i) for i in range(1, 260)] + [0.0, 260.0]
    frame = pd.DataFrame({
        'date': pd.bdate_range('2025-11-20', periods=len(closes)),
        'market': 'sz', 'symbol': '002370', 'open': closes, 'close': closes,
        'volume': [100.0] * len(closes), 'free_float_shares': [1_000_000] * len(closes),
    })
    payload = build_market_metrics(frame, annual_eps={})
    metric = payload['metrics']['sz:002370']
    assert payload['schema_version'] == 'stock-filter-market-metrics-v6'
    assert len(metric['return_close_history']) == 251
    assert metric['return_close_history'][0] == 10.0
    assert metric['return_close_history'][-1] == 260.0
    assert 0.0 not in metric['return_close_history']


def test_dynamic_return_filters_whole_universe_before_pagination_and_returns_evidence():
    rows = [_row(i) for i in range(53)]
    qfq = {('sz', f'{i:06d}'): {'qfq_as_of': DAY, 'return_close_history': _history(110 if i < 52 else 90)}
           for i in range(53)}
    params = {'return_n_days': ['5'], 'return_n_pct_min': ['5'],
              'return_n_pct_max': ['15']}
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._qfq_latest', return_value=qfq):
        first = filter_response(params)
        second = filter_response({**params, 'page': ['2']})
    assert first['ok'] and first['total_matched'] == 52 and len(first['rows']) == 50
    assert second['ok'] and second['total_matched'] == 52 and len(second['rows']) == 2
    assert all(row['return_n_days'] == 5 and row['return_n_pct'] == 10.0
               for row in first['rows'] + second['rows'])
    assert first['return_n_filter'] == {
        'days': 5, 'min_pct': 5.0, 'max_pct': 15.0,
        'price_basis': 'tdx_export_qfq', 'definition': 'close_today/close_N_valid_trading_days_ago-1',
    }


def test_dynamic_return_accepts_one_sided_bounds_and_rejects_ambiguous_or_invalid_input():
    rows = [_row(1)]
    qfq = {('sz', '000001'): {'qfq_as_of': DAY, 'return_close_history': _history(110)}}
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._qfq_latest', return_value=qfq):
        assert filter_response({'return_n_days': ['5'], 'return_n_pct_min': ['10']})['total_matched'] == 1
        assert filter_response({'return_n_days': ['5'], 'return_n_pct_max': ['9.9']})['total_matched'] == 0
    invalid = (
        {'return_n_days': ['0'], 'return_n_pct_min': ['1']},
        {'return_n_days': ['251'], 'return_n_pct_min': ['1']},
        {'return_n_days': ['2.5'], 'return_n_pct_min': ['1']},
        {'return_n_pct_min': ['1']},
        {'return_n_days': ['5']},
        {'return_n_days': ['5'], 'return_n_pct_min': ['nan']},
        {'return_n_days': ['5'], 'return_n_pct_max': ['inf']},
        {'return_n_days': ['5'], 'return_n_pct_min': ['3'], 'return_n_pct_max': ['2']},
        {'return_n_days': ['5'], 'return_n_pct_min': ['1'], 'as_of_date': [DAY]},
    )
    for params in invalid:
        assert filter_response(params)['error']['code'] == 'invalid_filter', params


def test_dynamic_return_old_or_stale_snapshot_fails_loudly_instead_of_zero_matches():
    rows = [_row(1)]
    for qfq in (
        {('sz', '000001'): {'qfq_as_of': DAY}},
        {('sz', '000001'): {'qfq_as_of': '2026-11-18', 'return_close_history': _history(110)}},
    ):
        with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
             patch('app.stock_filter._qfq_latest', return_value=qfq):
            result = filter_response({'return_n_days': ['5'], 'return_n_pct_min': ['1']})
        assert result['error']['code'] == 'return_n_unavailable'


def test_page_wires_dynamic_return_controls_display_and_historical_guard():
    html = (ROOT / 'web/stock-filter.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-filter.js').read_text(encoding='utf-8')
    market = html.split('data-filter-group="market"', 1)[1].split('</fieldset>', 1)[0]
    assert 'name="return_n_days"' in market
    assert 'name="return_n_pct_min"' in market
    assert 'name="return_n_pct_max"' in market
    assert 'N日涨跌幅' in market and '1—250' in market
    assert 'row.return_n_pct' in js and 'row.return_n_days' in js
    historical = js.split('function updateHistoricalMode()', 1)[1]
    assert all(f"'{name}'" in historical for name in
               ('return_n_days', 'return_n_pct_min', 'return_n_pct_max'))
