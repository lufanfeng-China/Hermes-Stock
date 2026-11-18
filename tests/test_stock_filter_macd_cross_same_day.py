"""MACD zero-axis crosses must be real same-day QFQ events, not stale tech labels."""
from unittest.mock import patch

import pandas as pd

from app.stock_filter import filter_response
from app.stock_filter_market_snapshot import build_market_metrics

DAY = '2026-11-16'


def _row(*, qfq_day=DAY, cross=None, cross_day=DAY):
    return {'market': 'sz', 'symbol': '000513', 'stock_name': '丽珠集团',
            'rps_total': 100, 'annual_dimensions': {}, 'quarterly_dimensions': {},
            'qfq_as_of': qfq_day, 'macd_cross': cross,
            'macd_cross_as_of': cross_day, 'legacy_macd_cross': 'zero_above'}


def _metric(closes):
    return build_market_metrics(pd.DataFrame({
        'date': pd.bdate_range('2026-08-24', periods=len(closes)),
        'market': 'sz', 'symbol': '000513', 'open': closes, 'close': closes,
        'volume': [100.] * len(closes), 'free_float_shares': [1000000.] * len(closes),
    }), annual_eps={})['metrics']['sz:000513']


def test_filter_rejects_old_tech_macd_marker_without_same_day_cross():
    with patch('app.stock_filter._universe', return_value=([_row(cross='')], DAY)):
        result = filter_response({'macd_cross': ['zero_above']})
    assert result['ok'] and result['total_matched'] == 0


def test_filter_rejects_missing_or_stale_macd_snapshot():
    with patch('app.stock_filter._universe', return_value=([_row(cross=None)], DAY)):
        missing = filter_response({'macd_cross': ['zero_above']})
    with patch('app.stock_filter._universe', return_value=([_row(qfq_day='2026-08-01', cross='zero_above')], DAY)):
        stale = filter_response({'macd_cross': ['zero_above']})
    assert missing['error']['code'] == 'macd_cross_unavailable'
    assert stale['error']['code'] == 'macd_cross_unavailable'


def test_snapshot_macd_cross_only_on_actual_crossing_day():
    uptrend = [10 + x * 0.1 for x in range(80)]
    dip = [uptrend[-1] - 0.05 * x for x in range(1, 6)]
    rebound = [dip[-1] + 0.06 * x for x in range(1, 30)]
    closes = uptrend + dip + rebound
    crossed = _metric(closes[:-1])
    next_day = _metric(closes)
    assert crossed['macd_cross'] == 'zero_above'
    assert crossed['macd_cross_prev_dif'] <= crossed['macd_cross_prev_dea']
    assert crossed['macd_cross_dif'] > crossed['macd_cross_dea'] > 0
    assert next_day['macd_cross'] == ''


def test_snapshot_drops_zero_price_halt_without_advancing_date():
    valid = _metric([10.] * 80 + [9.] * 20 + [12.] * 10)
    halted = _metric([10.] * 80 + [9.] * 20 + [12.] * 10 + [0.])
    assert halted['qfq_as_of'] == valid['qfq_as_of']
    assert halted['macd_cross'] == valid['macd_cross']
