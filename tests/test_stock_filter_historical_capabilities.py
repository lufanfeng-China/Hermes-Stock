from unittest.mock import patch

from app import stock_filter

DAY = '2026-11-19'

LATEST_ONLY = {
    'industry_l2_codes', 'industry_temperature_levels', 'concept_codes', 'concept_temperature_levels',
    'rps_20_min', 'rps_20_max', 'rps_50_min', 'rps_50_max', 'rps_120_min', 'rps_120_max',
    'rps_250_min', 'rps_250_max', 'rps_total_min', 'rps_total_max',
    'return_n_days', 'return_n_pct_min', 'return_n_pct_max',
    'change_days_n', 'up_days_min', 'up_days_max', 'down_days_min', 'down_days_max',
    'limit_up_n_days', 'eps_ratio_5y_min', 'eps_ratio_5y_max',
    'total_market_cap_min', 'total_market_cap_max',
    'free_float_market_cap_min', 'free_float_market_cap_max',
    'niche_leader', 'composite_total_min', 'composite_total_max',
    'trend_weekly', 'trend_monthly', 'macd_cross', 'golden_cross',
    'ma_alignment', 'ma_alignment_days_min', 'ma_alignment_days_max',
    'mrs_score_min', 'mrs_score_max', 'excess_return_5_pp_min', 'excess_return_5_pp_max',
    'excess_return_20_pp_min', 'excess_return_20_pp_max',
    'excess_return_50_pp_min', 'excess_return_50_pp_max',
    'excess_return_120_pp_min', 'excess_return_120_pp_max',
    'excess_return_250_pp_min', 'excess_return_250_pp_max',
    'down_market_win_rate_20_min', 'down_market_win_rate_20_max',
    'down_market_total_excess_pp_20_min', 'down_market_total_excess_pp_20_max',
    'return_5d_min', 'return_5d_max', 'return_20d_min', 'return_20d_max',
    'turnover_5_sum_min', 'turnover_5_sum_max', 'turnover_5_avg_min', 'turnover_5_avg_max',
}

VALID_VALUES = {
    'industry_l2_codes': '801010', 'industry_temperature_levels': '3',
    'concept_codes': 'C001', 'concept_temperature_levels': '3',
    'niche_leader': 'yes', 'trend_weekly': 'bullish', 'trend_monthly': 'bullish',
    'macd_cross': 'zero_above', 'golden_cross': '5/10', 'ma_alignment': '5/10/20',
}


def _row():
    return {
        'market': 'sz', 'symbol': '000001', 'stock_name': '平安银行',
        'financial_model_code': 'general', 'annual_period': '2025A',
        'annual_total': 60.0, 'quarterly_total': 55.0,
        'annual_dimensions': {}, 'quarterly_dimensions': {},
        'price': 10.0, 'qfq_as_of': DAY, 'trend_daily': 'bullish',
    }


def test_backend_declares_every_latest_only_historical_parameter():
    assert set(stock_filter.HISTORICAL_LATEST_ONLY_PARAMS) == LATEST_ONLY


def test_direct_api_rejects_every_latest_only_parameter_before_snapshot_loading():
    for name in sorted(LATEST_ONLY):
        value = VALID_VALUES.get(name, '1')
        with patch.object(stock_filter, '_historical_universe', side_effect=AssertionError('must reject first')):
            result = stock_filter.filter_response({'as_of_date': [DAY], name: [value]})
        assert result['error']['code'] == 'invalid_filter', name
        assert name in result['error']['message'], name


def test_historical_scope_rejects_current_csi300_but_keeps_code_based_boards():
    with patch.object(stock_filter, '_historical_universe', side_effect=AssertionError('must reject first')):
        rejected = stock_filter.filter_response({'as_of_date': [DAY], 'stock_scope': ['csi300']})
    assert rejected['error']['code'] == 'invalid_filter'
    assert 'stock_scope' in rejected['error']['message']

    with patch.object(stock_filter, '_historical_universe', return_value=([_row()], DAY)):
        accepted = stock_filter.filter_response({'as_of_date': [DAY], 'stock_scope': ['main_board'],
                                                 'sort': ['annual_total']})
    assert accepted['ok']


def test_historical_sort_rejects_latest_only_values_and_has_supported_default():
    for value in ('rps_total', 'mrs_score', 'excess_return_20_pp', 'composite_total',
                  'total_market_cap', 'free_float_market_cap', 'eps_ratio_5y', 'return_pct', 'turnover_sum'):
        with patch.object(stock_filter, '_historical_universe', side_effect=AssertionError('must reject first')):
            result = stock_filter.filter_response({'as_of_date': [DAY], 'sort': [value]})
        assert result['error']['code'] == 'invalid_filter', value
        assert 'sort' in result['error']['message']

    with patch.object(stock_filter, '_historical_universe', return_value=([_row()], DAY)):
        result = stock_filter.filter_response({'as_of_date': [DAY]})
    assert result['ok'] and result['sort'] == 'pe_ttm'


def test_supported_historical_filters_are_not_misclassified():
    with patch.object(stock_filter, '_historical_universe', return_value=([_row()], DAY)):
        result = stock_filter.filter_response({
            'as_of_date': [DAY], 'price_min': ['9'], 'annual_total_min': ['50'],
            'financial_model_code': ['general'], 'annual_period': ['2025A'],
            'trend_daily': ['bullish'], 'sort': ['annual_total'],
        })
    assert result['ok'] and result['total_matched'] == 1
