"""A golden cross means a crossing on the effective QFQ screening day, never an old technical snapshot."""
from unittest.mock import patch

import pandas as pd

from app.stock_filter import filter_response
from app.stock_filter_market_snapshot import build_market_metrics

DAY = '2026-11-16'


def _metric(closes):
    return build_market_metrics(pd.DataFrame({
        'date': pd.bdate_range('2026-08-24', periods=len(closes)),
        'market': 'sz', 'symbol': '000157', 'open': closes, 'close': closes,
        'volume': [100.] * len(closes), 'free_float_shares': [1000000.] * len(closes),
    }), annual_eps={})['metrics']['sz:000157']


def _row(day=DAY, cross=None, cross_day=DAY):
    return {'market': 'sz', 'symbol': '000157', 'stock_name': '中联重科',
            'rps_total': 100, 'annual_dimensions': {}, 'quarterly_dimensions': {},
            'qfq_as_of': day, 'golden_cross': cross, 'golden_cross_as_of': cross_day,
            'legacy_golden_cross': '20/60'}


def test_qfq_snapshot_detects_only_today_cross_and_ignores_zero_price_halts():
    closes = [10.] * 41 + [9.] * 19 + [30.]
    crossed = _metric(closes)
    assert '20/60' in crossed['golden_cross'].split(',')
    assert '20/60' not in _metric(closes + [30.])['golden_cross'].split(',')
    halted = _metric(closes + [0.])
    assert '20/60' in halted['golden_cross'].split(',')
    assert halted['qfq_as_of'] == str(pd.bdate_range('2026-08-24', periods=61)[-1].date())


def test_filter_does_not_use_old_technical_cross_when_current_qfq_does_not_cross():
    with patch('app.stock_filter._universe', return_value=([_row(cross='')], DAY)):
        result = filter_response({'golden_cross': ['20/60']})
    assert result['ok'] and result['total_matched'] == 0


def test_filter_fails_closed_when_cross_snapshot_missing_or_stale():
    with patch('app.stock_filter._universe', return_value=([_row(cross=None)], DAY)):
        missing = filter_response({'golden_cross': ['20/60']})
    with patch('app.stock_filter._universe', return_value=([_row(day='2026-08-01', cross='20/60')], DAY)):
        stale = filter_response({'golden_cross': ['20/60']})
    assert missing['error']['code'] == 'golden_cross_unavailable'
    assert stale['error']['code'] == 'golden_cross_unavailable'


def test_cross_pairs_require_all_selected_pairs():
    with patch('app.stock_filter._universe', return_value=([_row(cross='5/10,20/60')], DAY)):
        both = filter_response({'golden_cross': ['5/10,20/60']})
        missing_one = filter_response({'golden_cross': ['5/10,10/20']})
    assert both['ok'] and both['total_matched'] == 1
    assert missing_one['ok'] and missing_one['total_matched'] == 0
