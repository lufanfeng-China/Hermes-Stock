"""Four strict QFQ moving-average alignment choices in filter group 06."""
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.stock_filter import filter_response
from app.stock_filter_market_snapshot import build_market_metrics

ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-11-12'


def _metric(closes):
    return build_market_metrics(pd.DataFrame({
        'date': pd.bdate_range('2026-05-01', periods=len(closes)),
        'market': 'sz', 'symbol': '002370', 'open': closes, 'close': closes,
        'volume': [100.] * len(closes), 'free_float_shares': [1000000] * len(closes),
    }), annual_eps={})['metrics']['sz:002370']


def _row(index, choices, date=DAY, durations=None):
    return {'market': 'sz', 'symbol': f'{index:06d}', 'rps_total': float(200-index),
            'annual_dimensions': {}, 'quarterly_dimensions': {},
            'qfq_as_of': date, 'ma_alignment': choices,
            'ma_alignment_duration': (durations if durations is not None else
                                      {choice: 1 for choice in (choices or [])})}


def test_strict_alignments_from_valid_qfq_bars_and_minimum_120_days():
    rising = _metric([10 + i * 0.01 for i in range(120)])
    assert rising['ma_alignment'] == ['5/10/20', '10/20/30', '10/30/60', '20/60/120']
    assert rising['ma_alignment_duration'] == {
        '5/10/20': 101, '10/20/30': 91, '10/30/60': 61, '20/60/120': 1,
    }
    assert rising['ma_alignment_ma']['120'] is not None
    flat = _metric([10.] * 120)
    assert flat['ma_alignment'] == []  # equality is not bullish
    assert flat['ma_alignment_duration'] == {
        '5/10/20': 0, '10/20/30': 0, '10/30/60': 0, '20/60/120': 0,
    }
    assert _metric([10 + i * 0.01 for i in range(119)])['ma_alignment'] == ['5/10/20', '10/20/30', '10/30/60']
    with_halt = _metric([10 + i * 0.01 for i in range(120)] + [0.])
    assert with_halt['ma_alignment'] == rising['ma_alignment']
    assert with_halt['qfq_as_of'] != str(pd.bdate_range('2026-05-01', periods=121)[-1].date())


def test_multiple_choices_are_or_and_apply_before_pagination():
    rows = [_row(i, ['5/10/20'] if i < 50 else ['20/60/120']) for i in range(51)]
    rows[0]['ma_alignment'] = []
    with patch('app.stock_filter._universe', return_value=(rows, DAY)):
        a = filter_response({'ma_alignment': ['5/10/20,20/60/120']})
        b = filter_response({'ma_alignment': ['5/10/20,20/60/120'], 'page': ['2']})
        c = filter_response({'ma_alignment': ['20/60/120']})
    assert a['ok'] and a['total_matched'] == 50 and len(a['rows']) == 50
    assert b['ok'] and b['total_matched'] == 50 and b['rows'] == []
    assert c['ok'] and c['total_matched'] == 1 and c['rows'][0]['symbol'] == '000050'


def test_missing_or_stale_ma_snapshot_is_not_zero_matches_or_raw_fallback():
    with patch('app.stock_filter._universe', return_value=([_row(1, None)], DAY)):
        missing = filter_response({'ma_alignment': ['5/10/20']})
    with patch('app.stock_filter._universe', return_value=([_row(1, ['5/10/20'], '2026-11-11')], DAY)):
        stale = filter_response({'ma_alignment': ['5/10/20']})
    assert missing['error']['code'] == 'ma_alignment_unavailable'
    assert stale['error']['code'] == 'ma_alignment_unavailable'
    assert filter_response({'ma_alignment': ['not-a-group']})['error']['code'] == 'invalid_filter'
    assert filter_response({'ma_alignment': ['5/10/20'], 'as_of_date': [DAY]})['error']['code'] == 'invalid_filter'


def test_current_bullish_duration_range_constrains_selected_or_any_alignment():
    rows = [
        _row(1, ['5/10/20'], durations={'5/10/20': 2}),
        _row(2, ['5/10/20'], durations={'5/10/20': 5}),
        _row(3, ['20/60/120'], durations={'20/60/120': 5}),
        _row(4, [], durations={'5/10/20': 0, '20/60/120': 0}),
    ]
    with patch('app.stock_filter._universe', return_value=(rows, DAY)):
        selected = filter_response({'ma_alignment': ['5/10/20'],
                                    'ma_alignment_days_min': ['4'],
                                    'ma_alignment_days_max': ['6']})
        any_group = filter_response({'ma_alignment_days_min': ['4'],
                                     'ma_alignment_days_max': ['6']})
    assert selected['ok'] and [row['symbol'] for row in selected['rows']] == ['000002']
    assert any_group['ok'] and [row['symbol'] for row in any_group['rows']] == ['000002', '000003']


def test_duration_range_rejects_invalid_historical_or_missing_snapshot_values():
    for params in (
        {'ma_alignment_days_min': ['0']},
        {'ma_alignment_days_min': ['2.5']},
        {'ma_alignment_days_min': ['7'], 'ma_alignment_days_max': ['3']},
        {'ma_alignment_days_min': ['3'], 'as_of_date': [DAY]},
    ):
        assert filter_response(params)['error']['code'] == 'invalid_filter'
    with patch('app.stock_filter._universe', return_value=([_row(1, ['5/10/20'], durations=None)], DAY)):
        # Explicitly remove the new field to emulate an old current snapshot.
        row = _row(1, ['5/10/20'])
        row.pop('ma_alignment_duration')
        with patch('app.stock_filter._universe', return_value=([row], DAY)):
            result = filter_response({'ma_alignment_days_min': ['3']})
    assert result['error']['code'] == 'ma_alignment_unavailable'


def test_ui_four_choices_are_real_multiselect_and_historical_is_explicitly_disabled():
    html = (ROOT / 'web/stock-filter.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-filter.js').read_text(encoding='utf-8')
    group = html.split('data-filter-group="technical"', 1)[1].split('</fieldset>', 1)[0]
    assert 'name="ma_alignment" multiple' in group
    assert all(f'value="{item}"' in group for item in ('5/10/20', '10/20/30', '10/30/60', '20/60/120'))
    assert 'name="ma_alignment_days_min"' in group
    assert 'name="ma_alignment_days_max"' in group
    assert '当前多头持续天数' in group
    assert 'ma_alignment: true' in js
    assert "'ma_alignment'" in js.split('function updateHistoricalMode()', 1)[1]
    historical = js.split('function updateHistoricalMode()', 1)[1]
    assert "'ma_alignment_days_min'" in historical
    assert "'ma_alignment_days_max'" in historical
