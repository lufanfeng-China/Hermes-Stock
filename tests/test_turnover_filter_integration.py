"""Turnover percentile is date-aligned, auditable, and filtered before pagination."""
from unittest.mock import patch

from app.stock_filter import filter_response

DAY = '2026-11-12'


def stock(symbol: str) -> dict:
    return {'market': 'sz', 'symbol': symbol, 'stock_name': symbol,
            'annual_dimensions': {}, 'quarterly_dimensions': {}, 'rps_total': 100}


def snapshot(day: str = DAY) -> dict:
    return {'schema_version': 'stock-filter-turnover-percentile-v2', 'as_of_date': day,
            'stocks': {
                'sz:000001': {'turnover_percentile_1y': 20.0, 'turnover_percentile_1y_as_of': day,
                              'turnover_percentile_1y_sample_count': 233},
                'sz:000002': {'turnover_percentile_1y': 85.0, 'turnover_percentile_1y_as_of': day,
                              'turnover_percentile_1y_sample_count': 240},
                'sz:000003': {'turnover_percentile_1y': None, 'turnover_percentile_1y_as_of': day,
                              'turnover_percentile_1y_status': 'no_available_shares'},
            }}


def test_turnover_builder_runs_after_financial_refresh_and_is_retryable():
    from app.pipeline.commands import _data_update_commands
    from app.handler import DATA_UPDATE_TASK_PLAN
    ids = [name for name, _ in _data_update_commands(DAY)]
    task = 'build_stock_filter_turnover_percentile_snapshot'
    assert ids.index('update_financial_ts') < ids.index(task)
    assert ids.index('refresh_rps_daily') < ids.index(task)
    assert task in [name for name, _ in _data_update_commands(DAY, retry_failed=True)]
    assert ids == [row['id'] for row in DATA_UPDATE_TASK_PLAN]


def test_current_range_filters_entire_universe_and_excludes_unknown():
    rows = [stock('000001'), stock('000002'), stock('000003')]
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._read_turnover_snapshot', return_value=snapshot()):
        result = filter_response({'turnover_percentile_1y_min': ['80']})
    assert result['ok'] and result['total_matched'] == 1
    assert result['rows'][0]['symbol'] == '000002'
    assert result['excluded_missing'] == 1


def test_bad_bounds_rejected_without_loading_universe():
    with patch('app.stock_filter._universe', side_effect=AssertionError('unexpected universe load')):
        for params in ({'turnover_percentile_1y_min': ['101']},
                       {'turnover_percentile_1y_max': ['nan']},
                       {'turnover_percentile_1y_min': ['70'], 'turnover_percentile_1y_max': ['20']}):
            assert filter_response(params)['error']['code'] == 'invalid_filter'


def test_stale_snapshot_fails_closed_when_filter_active_but_display_is_unknown():
    rows = [stock('000001')]
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._read_turnover_snapshot', return_value=snapshot('2026-11-11')):
        enabled = filter_response({'turnover_percentile_1y_min': ['10']})
        display = filter_response({})
    assert not enabled['ok'] and enabled['error']['code'] == 'turnover_percentile_unavailable'
    assert display['ok'] and display['rows'][0]['turnover_percentile_1y'] is None


def test_historical_date_does_not_read_current_publication():
    row = {**stock('000001'), 'turnover_percentile_1y': 30.0,
           'turnover_percentile_1y_as_of': '2025-04-18'}
    with patch('app.stock_filter._historical_universe', return_value=([row], '2025-04-18')), \
         patch('app.stock_filter._read_turnover_snapshot', side_effect=AssertionError('current leak')):
        result = filter_response({'as_of_date': ['2025-04-18'], 'turnover_percentile_1y_max': ['50']})
    assert result['ok'] and result['total_matched'] == 1


def test_stale_historical_value_cannot_match_filter():
    row = {**stock('000001'), 'turnover_percentile_1y': 30.0,
           'turnover_percentile_1y_as_of': '2025-04-17'}
    with patch('app.stock_filter._historical_universe', return_value=([row], '2025-04-18')):
        result = filter_response({'as_of_date': ['2025-04-18'], 'turnover_percentile_1y_max': ['50']})
    assert not result['ok'] and result['error']['code'] == 'turnover_percentile_unavailable'
