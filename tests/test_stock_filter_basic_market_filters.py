"""Signed QFQ market filters are computed once and applied before pagination."""
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.stock_filter import filter_response
from app.stock_filter_market_snapshot import build_market_metrics


def _frame(closes, volumes):
    dates = pd.bdate_range('2026-10-01', periods=len(closes))
    return pd.DataFrame({'date': dates, 'market': 'sz', 'symbol': '002370',
                         'open': closes, 'close': closes, 'volume': volumes,
                         'free_float_shares': [1000000] * len(closes)})


def test_daily_return_volume_ratio_and_signed_ma_distance_use_valid_qfq_bars():
    frame = _frame([10.] * 19 + [11., 0.], [100.] * 19 + [300., 0.])
    metric = build_market_metrics(frame, annual_eps={})['metrics']['sz:002370']
    assert metric['qfq_as_of'] == str(frame['date'].iloc[-2].date())
    assert metric['return_1d'] == 10.
    assert metric['volume_ratio_5'] == 3.
    assert metric['ma5_distance_pct'] == round((11 / 10.2 - 1) * 100, 4)
    assert metric['ma10_distance_pct'] == round((11 / 10.1 - 1) * 100, 4)
    assert metric['ma20_distance_pct'] == round((11 / 10.05 - 1) * 100, 4)
    assert metric['ma5'] == 10.2
    assert metric['ma10'] == 10.1
    assert metric['ma20'] == 10.05


def test_insufficient_history_and_zero_previous_volume_do_not_create_ratios():
    short = build_market_metrics(_frame([10.] * 4 + [11.], [100.] * 5), annual_eps={})['metrics']['sz:002370']
    assert short['ma5_distance_pct'] is not None
    assert short['ma10_distance_pct'] is None
    assert short['ma20_distance_pct'] is None
    assert short['volume_ratio_5'] is None
    zero = build_market_metrics(_frame([10.] * 6, [0.] * 5 + [200.]), annual_eps={})['metrics']['sz:002370']
    assert zero['volume_ratio_5'] is None


def test_signed_bounds_filter_full_universe_before_pagination_and_exclude_missing():
    rows = [{'market': 'sz', 'symbol': f'{i:06d}', 'rps_total': float(200 - i),
             'annual_dimensions': {}, 'quarterly_dimensions': {}, 'qfq_as_of': '2026-11-12',
             'return_1d': 2., 'volume_ratio_5': 2.,
             'ma5_distance_pct': 1., 'ma10_distance_pct': 2., 'ma20_distance_pct': -1.}
            for i in range(55)]
    rows[-1]['ma20_distance_pct'] = None
    rows[0]['ma5_distance_pct'] = -2.
    rows[1]['volume_ratio_5'] = 0.5
    with patch('app.stock_filter._universe', return_value=(rows, '2026-11-12')):
        a = filter_response({'return_1d_min': ['1'], 'volume_ratio_5_min': ['1'],
                             'ma5_distance_pct_min': ['0'], 'ma10_distance_pct_max': ['2'],
                             'ma20_distance_pct_max': ['0']})
        b = filter_response({'return_1d_min': ['1'], 'volume_ratio_5_min': ['1'],
                             'ma5_distance_pct_min': ['0'], 'ma10_distance_pct_max': ['2'],
                             'ma20_distance_pct_max': ['0'], 'page': ['2']})
    assert a['ok'] and a['total_matched'] == 52
    assert len(a['rows']) == 50 and len(b['rows']) == 2
    assert {r['symbol'] for r in a['rows'] + b['rows']} == {r['symbol'] for r in rows[2:-1]}


def test_missing_market_snapshot_fails_loudly_for_requested_filters():
    rows = [{'market': 'sz', 'symbol': '002370', 'annual_dimensions': {}, 'quarterly_dimensions': {}}]
    with patch('app.stock_filter._universe', return_value=(rows, '2026-11-12')):
        result = filter_response({'ma5_distance_pct_min': ['0']})
    assert not result['ok']
    assert result['error']['code'] == 'market_metrics_unavailable'


def test_old_snapshot_with_default_none_fields_fails_loudly():
    rows = [{'market': 'sz', 'symbol': '002370', 'qfq_as_of': '2026-11-12',
             'volume_ratio_5': None, 'annual_dimensions': {}, 'quarterly_dimensions': {}}]
    with patch('app.stock_filter._universe', return_value=(rows, '2026-11-12')):
        result = filter_response({'volume_ratio_5_min': ['1']})
    assert result['error']['code'] == 'market_metrics_unavailable'


def test_invalid_nonfinite_bound_is_rejected():
    result = filter_response({'volume_ratio_5_min': ['nan']})
    assert result['error']['code'] == 'invalid_filter'


def test_historical_projection_keeps_market_fields_and_rejects_legacy_schema():
    from app.stock_filter_fundamental_history import build_historical_fundamental_snapshot
    from app.stock_filter_market_snapshot import BASIC_MARKET_FIELDS
    frame = pd.DataFrame([{'symbol': '002370', 'announce_date': '2026-04-15', '基本每股收益': 0.3}]).set_index('symbol')
    market = {'return_1d': -2., 'qfq_as_of': '2026-11-12',
              **{field: 1. for field in BASIC_MARKET_FIELDS}}
    snapshot = build_historical_fundamental_snapshot(
        as_of_date='2026-11-12', period_frames={'2025A': frame},
        raw_close_by_symbol={'002370': 4.63}, market_by_symbol={'002370': 'sz'},
        industry_by_key={}, market_metrics_by_key={'sz:002370': market})
    assert snapshot['schema_version'] == 'stock-filter-fundamental-history-v7'
    row = snapshot['stocks']['sz:002370']
    assert all(row[field] == 1. for field in BASIC_MARKET_FIELDS)
    assert row['return_1d'] == -2.


def test_basic_market_controls_are_in_sidebar_and_explain_sign_and_volume_baseline():
    html = (Path(__file__).resolve().parents[1] / 'web/stock-filter.html').read_text(encoding='utf-8')
    group = html.split('data-filter-group="market"', 1)[1].split('</fieldset>', 1)[0]
    for field in ('return_1d', 'volume_ratio_5', 'ma5_distance_pct', 'ma10_distance_pct', 'ma20_distance_pct'):
        assert f'name="{field}_min"' in group
        assert f'name="{field}_max"' in group
    assert '前5个有效交易日' in group
    assert '负值在线下' in group


def test_result_price_cell_exposes_filtered_market_evidence_on_hover():
    script = (Path(__file__).resolve().parents[1] / 'web/stock-filter.js').read_text(encoding='utf-8')
    assert 'basicMarketTitle(row)' in script
    assert 'row.volume_ratio_5' in script
    assert 'row.ma5_distance_pct' in script
    assert 'row.ma10_distance_pct' in script
    assert 'row.ma20_distance_pct' in script
