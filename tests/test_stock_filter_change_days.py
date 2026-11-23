"""Configurable up/down trading-day count filter over a 1..250 day QFQ window."""
from pathlib import Path
from unittest.mock import patch

from app.stock_filter import filter_response

ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-11-19'


def _row(index):
    return {
        'market': 'sz', 'symbol': f'{index:06d}', 'rps_total': float(1000-index),
        'annual_dimensions': {}, 'quarterly_dimensions': {}, 'qfq_as_of': DAY,
    }


def test_up_down_counts_filter_whole_universe_before_pagination_and_return_evidence():
    rows = [_row(i) for i in range(53)]
    passing = [100.0, 101.0, 102.0, 101.0, 103.0, 103.0]  # up 3, down 1, flat 1
    failing = [100.0, 99.0, 98.0, 99.0, 98.0, 97.0]      # up 1, down 4
    qfq = {('sz', f'{i:06d}'): {'qfq_as_of': DAY, 'return_close_history': passing if i < 52 else failing}
           for i in range(53)}
    params = {'change_days_n': ['5'], 'up_days_min': ['3'], 'up_days_max': ['3'],
              'down_days_min': ['1'], 'down_days_max': ['1']}
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._qfq_latest', return_value=qfq):
        first = filter_response(params)
        second = filter_response({**params, 'page': ['2']})
    assert first['ok'] and first['total_matched'] == 52 and len(first['rows']) == 50
    assert second['ok'] and second['total_matched'] == 52 and len(second['rows']) == 2
    for row in first['rows'] + second['rows']:
        assert (row['change_days_n'], row['up_days'], row['down_days'], row['flat_days']) == (5, 3, 1, 1)
        assert row['change_days_price_basis'] == 'tdx_export_qfq'
    assert first['change_days_filter'] == {
        'days': 5, 'up_min': 3, 'up_max': 3, 'down_min': 1, 'down_max': 1,
        'price_basis': 'tdx_export_qfq',
        'definition': 'compare_each_valid_close_with_previous_valid_close',
    }


def test_up_down_filter_accepts_independent_one_sided_ranges_and_keeps_flat_separate():
    rows = [_row(1)]
    qfq = {('sz', '000001'): {'qfq_as_of': DAY,
                               'return_close_history': [100, 101, 100, 100, 102, 101]}}
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._qfq_latest', return_value=qfq):
        up = filter_response({'change_days_n': ['5'], 'up_days_min': ['2']})
        down = filter_response({'change_days_n': ['5'], 'down_days_max': ['2']})
        too_many = filter_response({'change_days_n': ['5'], 'up_days_min': ['3']})
    assert up['total_matched'] == 1 and down['total_matched'] == 1
    assert too_many['total_matched'] == 0
    row = up['rows'][0]
    assert (row['up_days'], row['down_days'], row['flat_days']) == (2, 2, 1)


def test_up_down_filter_rejects_ambiguous_impossible_or_historical_inputs():
    invalid = (
        {'change_days_n': ['0'], 'up_days_min': ['1']},
        {'change_days_n': ['251'], 'up_days_min': ['1']},
        {'change_days_n': ['2.5'], 'up_days_min': ['1']},
        {'up_days_min': ['1']},
        {'change_days_n': ['5']},
        {'change_days_n': ['5'], 'up_days_min': ['-1']},
        {'change_days_n': ['5'], 'up_days_max': ['6']},
        {'change_days_n': ['5'], 'up_days_min': ['4'], 'up_days_max': ['3']},
        {'change_days_n': ['5'], 'down_days_min': ['4'], 'down_days_max': ['3']},
        {'change_days_n': ['5'], 'up_days_min': ['3'], 'down_days_min': ['3']},
        {'change_days_n': ['5'], 'up_days_min': ['1'], 'as_of_date': [DAY]},
    )
    for params in invalid:
        assert filter_response(params)['error']['code'] == 'invalid_filter', params


def test_up_down_filter_old_stale_or_short_snapshot_fails_loudly():
    rows = [_row(1)]
    snapshots = (
        {('sz', '000001'): {'qfq_as_of': DAY}},
        {('sz', '000001'): {'qfq_as_of': '2026-11-18', 'return_close_history': [1, 2, 3]}},
        {('sz', '000001'): {'qfq_as_of': DAY, 'return_close_history': [1, 2, 3]}},
    )
    for qfq in snapshots:
        with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
             patch('app.stock_filter._qfq_latest', return_value=qfq):
            result = filter_response({'change_days_n': ['5'], 'up_days_min': ['1']})
        assert result['error']['code'] == 'change_days_unavailable'


def test_page_wires_up_down_count_controls_display_and_historical_guard():
    html = (ROOT / 'web/stock-filter.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-filter.js').read_text(encoding='utf-8')
    market = html.split('data-filter-group="market"', 1)[1].split('</fieldset>', 1)[0]
    for name in ('change_days_n', 'up_days_min', 'up_days_max', 'down_days_min', 'down_days_max'):
        assert f'name="{name}"' in market
    assert 'N日涨跌天数' in market and '上涨天数' in market and '下跌天数' in market
    assert 'row.up_days' in js and 'row.down_days' in js and 'row.flat_days' in js
    historical = (ROOT / 'web/stock-filter-history-capabilities.js').read_text(encoding='utf-8')
    assert all(f"'{name}'" in historical for name in
               ('change_days_n', 'up_days_min', 'up_days_max', 'down_days_min', 'down_days_max'))
