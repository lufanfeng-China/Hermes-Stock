"""Causal QFQ swing structure and independent v5 research parity."""
import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from app.swing_structure import classify
from app.tdx.qfq_kline import load_tdx_qfq_daily, qfq_export_path

RESEARCH = Path('/mnt/c/Users/Sky.Lu/Desktop/output/swing_main_states_v5_2026-10-30.csv')


def bars(high, low, close=None):
    if close is None:
        close = [(h + l) / 2 for h, l in zip(high, low)]
    return pd.DataFrame({'open': close, 'high': high, 'low': low,
                         'close': close, 'volume': [100] * len(high)},
                        index=pd.bdate_range('2025-01-01', periods=len(high)))


def test_confirmation_is_prefix_causal_and_ties_preserve_earlier_point():
    high = [6.] * 22
    low = [4.] * 22
    high[5] = high[8] = 10
    first = classify(bars(high[:10], low[:10]))
    assert first['raw_confirmed_peaks'] == 0
    confirmed = classify(bars(high[:11], low[:11]))
    assert confirmed['last_10_peaks'][0]['date'] == '2025-01-08'
    assert confirmed['last_10_peaks'][0]['confirmed'] == '2025-01-15'
    later = classify(bars(high, low))
    assert later['last_10_peaks'] == confirmed['last_10_peaks']
    assert later['raw_confirmed_peaks'] == 1


def test_300990_rebound_keeps_confirmed_shape_but_discloses_lower_unconfirmed_low():
    source = qfq_export_path('300990')
    if not source.is_file():
        pytest.skip('TDX QFQ 300990 fixture unavailable')
    data = load_tdx_qfq_daily('300990')
    result = classify(data.loc[data.index <= '2026-11-11'])
    assert result['state'] == '低点抬升型上行'
    assert result['latest_valley']['date'] == '2026-10-09'
    assert result['new_low_risk'] == {
        'date': '2026-11-06', 'low': 62.5, 'confirmed_valley_date': '2026-10-09',
        'confirmed_valley_low': 86.57, 'waiting_bars': 3,
        'close_below_confirmed_valley': False,
        'break_day_close_below_confirmed_valley': True,
    }


def test_orthodox_down_break_above_highest_of_recent_three_confirmed_peaks_is_not_candidate():
    source = qfq_export_path('600327')
    if not source.is_file():
        pytest.skip('TDX QFQ 600327 fixture unavailable')
    result = classify(load_tdx_qfq_daily('600327').loc[:'2026-11-12'])
    assert result['peak_shape'] == result['valley_shape'] == 'down'
    assert result['close'] > max(p['high'] for p in result['last_10_peaks'][-3:])
    assert result['state'] == result['old_state'] == '结构转换／混合'


def test_new_low_risk_includes_current_intraday_low_and_clears_after_confirmation():
    if not qfq_export_path('300990').is_file():
        pytest.skip('TDX QFQ 300990 fixture unavailable')
    source = load_tdx_qfq_daily('300990').loc[:'2026-11-11'].copy()
    intraday = source.copy()
    intraday.loc[intraday.index[-1], 'low'] = 60.0
    today = classify(intraday)
    assert today['new_low_risk']['date'] == '2026-11-11'
    assert today['new_low_risk']['waiting_bars'] == 0
    assert today['new_low_risk']['close_below_confirmed_valley'] is False
    # Two hypothetical valid bars are only a boundary test, never published data.
    extra = pd.DataFrame([source.iloc[-1].to_dict()] * 2,
                         index=pd.bdate_range('2026-11-12', periods=2))
    confirmed = classify(pd.concat([source, extra]))
    assert confirmed['latest_valley']['date'] == '2026-11-06'
    assert confirmed['new_low_risk'] is None


def test_zero_qfq_placeholder_is_not_a_trading_bar_or_confirmation():
    high = [6.] * 13
    low = [4.] * 13
    high[5] = 10
    data = bars(high, low)
    data.iloc[9] = 0
    early = classify(data.iloc[:11])
    assert early['raw_confirmed_peaks'] == 0
    result = classify(data)
    assert result['raw_confirmed_peaks'] == 1
    assert result['last_10_peaks'][0]['confirmed'] == str(data.index[11].date())
    assert result['bars'] == 12


def test_mirror_reversal_and_priority_over_box():
    from app.swing_structure import classify_decision
    base = dict(peak_shape='up', valley_shape='up', close=8., peak=15., valley=10.,
                highest_recent_peak=20., old_state='区间震荡')
    assert classify_decision(**base) == '原正统上行／跌破最近谷（反转候选）'
    assert classify_decision(**(base | {'peak_shape': 'nonmonotone'})) == '原低点抬升型上行形状／跌破最近谷（反转候选）'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'down', 'close': 16.})) == '原正统下行／突破最近峰（反转候选）'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'down', 'close': 20.})) == '原正统下行／突破最近峰（反转候选）'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'down', 'close': 20.01})) == '区间震荡'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'nonmonotone', 'close': 20.01})) == '原高点降低型下行形状／突破最近峰（反转候选）'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'nonmonotone', 'close': 16.})) == '原高点降低型下行形状／突破最近峰（反转候选）'
    assert classify_decision(**(base | {'close': 10.})) == '区间震荡'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'up', 'close': 9.})) == '收敛／破位下行'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'up', 'close': 16.})) == '收敛／突破上行'
    assert classify_decision(**(base | {'peak_shape': 'down', 'valley_shape': 'up', 'close': 12.})) == '收敛／方向待确认'


def test_canonical_same_type_replacement_is_not_backdated():
    from app.swing_structure import _canonical
    high = [6.] * 35
    low = [4.] * 35
    high[5], high[14], high[20] = 10., 12., 12.
    low[25] = 2.
    before = _canonical([5], [], high, low)
    after = _canonical([5, 14, 20], [25], high, low)
    assert before[0] == [5]
    assert after[0] == [14]
    assert after[1] == [25]
    assert len(after[2]) == 2
    assert after[2][-1][-1] == 'weaker_or_equal_kept_earlier'


def test_inverted_contraction_prices_do_not_force_a_direction():
    from app.swing_structure import classify_decision
    args = dict(peak_shape='down', valley_shape='up', peak=3.17, valley=3.32,
                highest_recent_peak=4.0, old_state='结构转换／混合')
    assert classify_decision(close=3.25, **args) == '结构转换／混合'
    assert classify_decision(close=2.87, **args) == '收敛／破位下行'
    assert classify_decision(close=3.33, **args) == '收敛／突破上行'


@pytest.mark.skipif(not RESEARCH.is_file(), reason='desktop research CSV unavailable')
def test_v5_research_parity_one_stock_per_state():
    with RESEARCH.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    examples = {}
    for row in rows:
        if row['status'] == 'ok' and row['new_state_v5'] not in examples:
            examples[row['new_state_v5']] = row
    assert len(examples) == 22
    for label, row in examples.items():
        source_bars = load_tdx_qfq_daily(row['code'])
        result = classify(source_bars.loc[source_bars.index <= row['as_of']])
        assert result['state'] == label, (row['code'], result['state'], label)
        assert result['selected_peaks'] == int(row['selected_peaks']), row['code']
        assert result['selected_valleys'] == int(row['selected_valleys']), row['code']
        assert result['peak_shape'] == row['peak_shape'], row['code']
        assert result['valley_shape'] == row['valley_shape'], row['code']
        assert result['last_10_peaks'][0]['date'] == json.loads(row['last_10_peaks_json'])[0]['date']
        assert result['last_10_valleys'][-1]['confirmed'] == json.loads(row['last_10_valleys_json'])[-1]['confirmed']
