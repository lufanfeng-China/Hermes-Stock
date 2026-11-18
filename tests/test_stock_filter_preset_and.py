"""Selected stock-filter presets must intersect before pagination."""
from unittest.mock import patch

from app.stock_filter import filter_response


def _rows(day):
    rows = []
    for i in range(52):
        rows.append({
            'market': 'sz', 'symbol': f'{i + 1:06d}', 'rps_total': 100 - i,
            'annual_dimensions': {}, 'quarterly_dimensions': {},
            'trend_template_ok': i in (1, 50, 51),
            'trend_template_status': 'evaluated',
            'blowup_break_volume_price_ok': i in (0, 50, 51),
            'trend_daily': 'bullish', 'short_trend': 'bullish',
        })
    return rows, day


def test_comma_selected_presets_intersect_before_pagination():
    with patch('app.stock_filter._universe', return_value=_rows('2026-11-12')):
        result = filter_response({'preset': ['trend_template,blowup_break']})
    assert result['ok'] is True
    assert result['total_matched'] == 2
    assert [row['symbol'] for row in result['rows']] == ['000051', '000052']


def test_repeated_preset_params_also_intersect_and_reject_unknown():
    with patch('app.stock_filter._universe', return_value=_rows('2026-11-12')):
        result = filter_response({'preset': ['blowup_break', 'trend_template']})
    assert result['ok'] is True
    assert result['total_matched'] == 2
    for raw in (['blowup_break,not_a_preset'], ['blowup_break', 'not_a_preset']):
        invalid = filter_response({'preset': raw})
        assert invalid['ok'] is False
        assert invalid['error']['code'] == 'invalid_filter'


def test_historical_combination_refuses_missing_trend_template_evidence():
    rows, day = _rows('2026-11-12')
    for row in rows:
        row.pop('trend_template_status')
    with patch('app.stock_filter._historical_universe', return_value=(rows, day)):
        result = filter_response({'preset': ['blowup_break,trend_template'], 'as_of_date': [day]})
    assert result['ok'] is False
    assert result['error']['code'] == 'trend_template_unavailable'
