from pathlib import Path
from unittest.mock import patch

from app.stock_filter import filter_response

ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-11-19'


def _row(symbol, industry_code, industry_name, pe, niche=''):
    return {
        'market': 'sz', 'symbol': symbol, 'stock_name': symbol,
        'industry_level_2_code': industry_code,
        'industry_level_2_name': industry_name,
        'industry': industry_name,
        'pe_ttm': pe, 'rps_total': 100.0,
        'niche_leader': niche,
        'annual_dimensions': {}, 'quarterly_dimensions': {},
    }


def test_default_sort_is_pe_ttm_and_distribution_uses_all_filtered_rows_before_pagination():
    rows = [
        _row('000001', 'I1', '医疗器械', 20),
        _row('000002', 'I1', '医疗器械', 10, '细分龙头'),
        _row('000003', 'I2', '休闲食品', 30),
        _row('000004', '', '', 15),
    ]
    temperature_index = {'industry_temperature_as_of': DAY, 'industry_temperature_window': 10,
                         'industry_temperature': {
                             'I1': {'temperature': 5, 'temperature_label': '极热',
                                    'temperature_previous': 4, 'temperature_previous_label': '热门',
                                    'temperature_change': 1, 'temperature_trend': 'warming',
                                    'temperature_trend_label': '升温', 'temperature_previous_gap_days': 1},
                             'I2': {'temperature': 2, 'temperature_label': '正常',
                                    'temperature_previous': 2, 'temperature_previous_label': '正常',
                                    'temperature_change': 0, 'temperature_trend': 'flat',
                                    'temperature_trend_label': '持平', 'temperature_previous_gap_days': 1},
                         }}
    with patch('app.stock_filter._universe', return_value=(rows, DAY)), \
         patch('app.stock_filter._swing_snapshot', side_effect=ValueError('not published')), \
         patch('app.stock_filter.stock_scope_index', return_value=temperature_index):
        result = filter_response({})

    assert result['ok'] and result['sort'] == 'pe_ttm'
    assert [row['symbol'] for row in result['rows']] == ['000002', '000004', '000001', '000003']
    distribution = result['industry_distribution']
    assert distribution['total'] == 4
    assert distribution['classified'] == 3
    assert distribution['unknown'] == 1
    assert distribution['membership_basis'] == 'current_industry_membership'
    assert distribution['temperature_as_of'] == DAY
    assert distribution['temperature_window'] == 10
    assert sum(row['count'] for row in distribution['rows']) == 4
    assert distribution['rows'][0] == {
        'industry_code': 'I1', 'industry_name': '医疗器械', 'count': 2, 'pct': 50.0,
        'temperature': 5, 'temperature_label': '极热',
        'temperature_previous': 4, 'temperature_previous_label': '热门',
        'temperature_change': 1, 'temperature_trend': 'warming',
        'temperature_trend_label': '升温', 'temperature_previous_gap_days': 1,
    }
    assert distribution['rows'][-1]['industry_name'] == '未分类'


def test_page_has_industry_distribution_default_pe_and_niche_leader_badge_contracts():
    html = (ROOT / 'web/stock-filter.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-filter.js').read_text(encoding='utf-8')

    assert 'id="open-industry-distribution"' in html
    assert html.index('id="open-industry-distribution"') < html.index('id="add-to-watchlist"')
    assert 'id="industry-distribution-dialog"' in html
    assert 'id="industry-distribution-rows"' in html
    assert '<th>当前温度</th>' in html
    assert '<th>温度变化</th>' in html
    assert '<option value="pe_ttm" data-order="asc" selected>' in html
    assert 'industry_distribution' in js
    assert 'temperatureChangeCell' in js
    assert 'temperature-current' in js
    assert 'niche-leader-badge' in js
    assert '细分龙头标签：' in js
