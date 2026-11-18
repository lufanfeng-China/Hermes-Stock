"""当天首次突破 75%：需要完整的前 30 个市场交易日 PIT 分位证据。"""
import json
from unittest.mock import patch

import pandas as pd

from app.stock_filter import filter_response


def fixture(tmp_path):
    days = [d.date().isoformat() for d in pd.bdate_range('2026-09-29', periods=32)]
    rows = []
    for symbol in ('000001', '000002', '000003', '000004'):
        for index, day in enumerate(days):
            percentile = 50.0
            if symbol == '000001' and index >= 30: percentile = 80.0
            if symbol == '000002' and index == 31: percentile = 75.01
            if symbol == '000003' and index in (15, 31): percentile = 90.0
            if symbol == '000004' and index == 31: percentile = 88.0
            if symbol == '000004' and index == 19: percentile = None
            rows.append({'market': 'sz', 'symbol': symbol, 'date': day,
                         'rolling_percentile': percentile})
    audit = f'stock_filter_turnover_daily_{days[-1]}.parquet'
    pd.DataFrame(rows).to_parquet(tmp_path / audit)
    (tmp_path / 'stock_filter_turnover_percentile_current.json').write_text(json.dumps({
        'schema_version': 'stock-filter-turnover-percentile-v2',
        'as_of_date': days[-1], 'daily_audit_file': audit,
    }))
    return days


def test_first_cross_is_only_on_signal_day_and_requires_all_prior_30_trading_days(tmp_path):
    from app.stock_filter_turnover_cross import crossing_keys
    days = fixture(tmp_path)
    assert crossing_keys(days[-1], tmp_path) == {'sz:000002': {'cross_date': days[-1], 'previous_30_start': days[1], 'percentile': 75.01}}
    assert crossing_keys(days[-2], tmp_path) == {'sz:000001': {'cross_date': days[-2], 'previous_30_start': days[0], 'percentile': 80.0}}


def test_invalid_or_insufficient_audit_never_falls_back_to_current_values(tmp_path):
    from app.stock_filter_turnover_cross import crossing_keys
    days = fixture(tmp_path)
    assert crossing_keys(days[29], tmp_path) is None
    (tmp_path / f'stock_filter_turnover_daily_{days[-1]}.parquet').unlink()
    assert crossing_keys(days[-1], tmp_path) is None


def test_preset_filters_all_stocks_before_pagination_and_keeps_evidence(tmp_path):
    days = fixture(tmp_path)
    stocks = [{'market': 'sz', 'symbol': symbol, 'stock_name': symbol,
               'annual_dimensions': {}, 'quarterly_dimensions': {}, 'rps_total': 100,
               'turnover_percentile_1y': 75.01 if symbol == '000002' else 80,
               'turnover_percentile_1y_as_of': days[-1],
               'blowup_break_return_5d': 10.0, 'qfq_as_of': days[-1]}
              for symbol in ('000001', '000002', '000003', '000004')]
    with patch('app.stock_filter._historical_universe', return_value=(stocks, days[-1])), \
         patch('app.stock_filter.TURNOVER_PERCENTILE_SNAPSHOT', tmp_path / 'stock_filter_turnover_percentile_current.json'):
        response = filter_response({'as_of_date': [days[-1]], 'preset': ['turnover_high']})
    assert response['ok'] and response['total_matched'] == 1
    assert response['rows'][0]['symbol'] == '000002'
    assert response['rows'][0]['turnover_first_cross_75_30d']['cross_date'] == days[-1]


def test_turnover_high_requires_positive_under_twenty_percent_5d_qfq_gain(tmp_path):
    days = fixture(tmp_path)
    stocks = [{'market': 'sz', 'symbol': '000002', 'stock_name': 'test',
               'annual_dimensions': {}, 'quarterly_dimensions': {}, 'rps_total': 100,
               'turnover_percentile_1y': 75.01, 'turnover_percentile_1y_as_of': days[-1],
               'qfq_as_of': days[-1], 'blowup_break_return_5d': 10.0}]
    with patch('app.stock_filter._historical_universe', return_value=(stocks, days[-1])), \
         patch('app.stock_filter.TURNOVER_PERCENTILE_SNAPSHOT', tmp_path / 'stock_filter_turnover_percentile_current.json'):
        for value, expected in ((None, 0), (0, 0), (20, 0), (-0.1, 0), (20.1, 0), (0.0001, 1), (19.9999, 1)):
            stocks[0]['blowup_break_return_5d'] = value
            result = filter_response({'as_of_date': [days[-1]], 'preset': ['turnover_high']})
            assert result['ok'] and result['total_matched'] == expected, (value, result)
        stocks[0]['blowup_break_return_5d'] = 10.0
        stocks[0]['qfq_as_of'] = days[-2]
        result = filter_response({'as_of_date': [days[-1]], 'preset': ['turnover_high']})
        assert result['ok'] and result['total_matched'] == 0
        # The new gate belongs to this preset only, not the general market filter.
        result = filter_response({'as_of_date': [days[-1]]})
        assert result['ok'] and result['total_matched'] == 1


def test_turnover_high_button_explains_strict_day_and_30_trading_day_history():
    from pathlib import Path
    html = Path('web/stock-filter.html').read_text(encoding='utf-8')
    assert 'data-preset="turnover_high"' in html
    assert '筛选当天' in html and '此前30个交易日' in html
    assert '前复权收盘涨幅严格大于0%、小于20%' in html
    script = Path('web/stock-filter.js').read_text(encoding='utf-8')
    assert 'togglePreset(option.dataset.preset)' in script
