"""Causal, audit-ready pressure-line observation boundaries."""
import json

import pandas as pd
import pytest

from app.swing_structure import classify


def fixture(valleys='down', extra=45):
    n = 10 + 20 * 12 + extra
    high = [60.] * n
    low = [20.] * n
    close = [45.] * n
    for k in range(12):
        high[10 + 20*k] = 120. - 3*k
        low[20 + 20*k] = (15. - k if valleys == 'down' else
                          8. + k if valleys == 'up' else 9. + (k % 3))
    idx = pd.bdate_range('2025-01-01', periods=n)
    frame = pd.DataFrame({'open':close, 'high':high, 'low':low, 'close':close,
                          'volume':[100.] * n}, index=idx)
    c = 10 + 20*11
    return frame, c


def set_close(frame, index, price):
    frame.iloc[index, frame.columns.get_loc('close')] = price
    frame.iloc[index, frame.columns.get_loc('open')] = price
    frame.iloc[index, frame.columns.get_loc('high')] = max(frame.iloc[index]['high'], price)


@pytest.mark.parametrize('valleys,shape', [('down','orthodox_down'), ('mixed','weak_down')])
def test_trigger_uses_occurrence_indices_and_freezes_three_lines(valleys, shape):
    frame, c = fixture(valleys)
    set_close(frame, c+6, 86.5)
    result = classify(frame.iloc[:c+7])
    observation = result['pressure_line']
    assert observation['status'] == 'triggered'
    assert observation['shape'] == shape
    assert observation['trigger_age'] == 1
    assert observation['c_confirmed'] == str(frame.index[c+5].date())
    assert observation['trigger_date'] == str(frame.index[c+6].date())
    assert observation['trigger_close'] == 86.5
    assert observation['days_above_after_trigger'] == 0
    assert [point['high'] for point in observation['peaks']] == [93., 90., 87.]
    assert all(point['confirmed'] <= observation['trigger_date'] for point in observation['peaks'])
    assert set(observation['lines']) == {'AB', 'AC', 'BC'}
    assert observation['key_price'] == max(observation['lines'].values())
    assert observation['key_price'] < 86.5
    assert result['state'] != '原正统下行／突破最近峰（反转候选）'
    json.dumps(result, allow_nan=False)


def test_five_subsequent_valid_bars_are_strict_and_sustained_is_not_reversal():
    frame, c = fixture()
    set_close(frame, c+6, 86.5)
    for i in range(c+7, c+12):
        set_close(frame, i, 86.5)
    frame.iloc[c+8] = 0  # zero-price placeholder is not a valid day
    four = classify(frame.iloc[:c+12])['pressure_line']
    assert four['status'] == 'triggered' and four['days_above_after_trigger'] == 4
    set_close(frame, c+12, 86.5)
    five = classify(frame.iloc[:c+13])
    assert five['pressure_line']['status'] == 'sustained'
    assert five['pressure_line']['days_above_after_trigger'] == 5
    assert five['pressure_line']['key_price'] == four['key_price']
    assert five['state'] == classify(frame.iloc[:c+7])['state']


def test_failure_can_retrigger_within_window_and_day_31_cannot_new_trigger():
    frame, c = fixture()
    set_close(frame, c+6, 86.5)
    set_close(frame, c+7, 45.)
    assert classify(frame.iloc[:c+8])['pressure_line'] is None
    set_close(frame, c+8, 86.5)
    assert classify(frame.iloc[:c+9])['pressure_line']['trigger_age'] == 3
    expired, c = fixture()
    set_close(expired, c+5+31, 86.5)
    assert classify(expired.iloc[:c+5+31])['pressure_line'] is None
    assert classify(expired.iloc[:c+5+32])['pressure_line'] is None
    set_close(expired, c+5+30, 86.5)
    assert classify(expired.iloc[:c+5+31])['pressure_line']['trigger_age'] == 30


def test_ineligible_valley_shape_and_break_above_c_cannot_trigger():
    up, c = fixture('up')
    set_close(up, c+6, 86.5)
    assert classify(up.iloc[:c+7])['pressure_line'] is None
    frame, c = fixture()
    set_close(frame, c+6, 88.)
    result = classify(frame.iloc[:c+7])
    assert result['pressure_line'] is None
    assert '突破最近峰' in result['state']


def test_day_zero_and_exact_key_do_not_trigger():
    frame, c = fixture()
    set_close(frame, c+5, 86.25)
    assert classify(frame.iloc[:c+6])['pressure_line'] is None
    # Three equally spaced falling peaks project to exactly 86.1 on valid day one.
    set_close(frame, c+6, 86.1)
    assert classify(frame.iloc[:c+7])['pressure_line'] is None


def test_failed_candidate_at_exact_frozen_key_clears_without_changing_main_state():
    frame, c = fixture()
    set_close(frame, c+6, 86.5)
    set_close(frame, c+7, 86.1)
    result = classify(frame.iloc[:c+8])
    assert result['pressure_line'] is None
    assert result['state'] == classify(frame.iloc[:c+7])['state']


def test_confirmation_and_new_c_invalidate_without_backdating():
    frame, c = fixture()
    set_close(frame, c+6, 86.5)
    prior = classify(frame.iloc[:c+7])['pressure_line']
    # A later valley and peak become canonical only on their confirmation dates.
    for i in range(c+7, c+25):
        set_close(frame, i, 86.5)
    frame.iloc[c+13, frame.columns.get_loc('low')] = 0.5
    frame.iloc[c+19, frame.columns.get_loc('high')] = 86.6
    before = classify(frame.iloc[:c+24])
    after = classify(frame.iloc[:c+25])
    assert before['pressure_line']['trigger_date'] == prior['trigger_date']
    assert after['pressure_line'] is None
    assert classify(frame.iloc[:c+7])['pressure_line'] == prior


def test_sustained_observation_invalidates_after_falling_back_to_frozen_key():
    frame, c = fixture()
    for i in range(c+6, c+12):
        set_close(frame, i, 86.5)
    assert classify(frame.iloc[:c+12])['pressure_line']['status'] == 'sustained'
    set_close(frame, c+12, 86.1)
    assert classify(frame.iloc[:c+13])['pressure_line'] is None


def test_observation_is_not_carried_into_close_above_c_peak():
    frame, c = fixture()
    set_close(frame, c+6, 86.5)
    assert classify(frame.iloc[:c+7])['pressure_line']['status'] == 'triggered'
    set_close(frame, c+7, 88.)
    result = classify(frame.iloc[:c+8])
    assert result['pressure_line'] is None
    assert '突破最近峰' in result['state']


def test_already_above_line_at_confirmation_is_not_new_crossover_on_day_one():
    frame, c = fixture()
    set_close(frame, c+5, 86.5)
    assert classify(frame.iloc[:c+6])['pressure_line'] is None
    set_close(frame, c+6, 86.5)
    assert classify(frame.iloc[:c+7])['pressure_line'] is None


def test_day_30_trigger_continuation_is_not_cut_off_by_first_trigger_window():
    frame, c = fixture()
    trigger = c+5+30
    set_close(frame, trigger, 82.)
    assert classify(frame.iloc[:trigger+1])['pressure_line']['trigger_age'] == 30
    for i in range(trigger+1, trigger+6):
        set_close(frame, i, 82.)
    # The trigger bar must not itself become a newly confirmed C on bar five:
    # a slightly higher next-bar high prevents that separate reanchor event.
    frame.iloc[trigger+1, frame.columns.get_loc('high')] = 82.1
    continued = classify(frame.iloc[:trigger+6])['pressure_line']
    assert continued['status'] == 'sustained'
    assert continued['days_above_after_trigger'] == 5
