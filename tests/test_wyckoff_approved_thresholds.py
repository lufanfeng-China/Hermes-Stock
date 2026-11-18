"""User-approved Wyckoff v2 event gates; all prices use the same QFQ basis."""
import pandas as pd
import pytest

from app.wyckoff_events import observe_wyckoff
from scripts.audit_wyckoff_event_quality import assert_parity, fast_events


def flat(n=61):
    return pd.DataFrame({
        'open': [100.] * n, 'high': [100.5] * n, 'low': [99.5] * n,
        'close': [100.] * n, 'volume': [1000.] * n,
    }, index=pd.bdate_range('2024-01-01', periods=n))


def event_types(frame):
    return [event['type'] for event in observe_wyckoff(frame)['events']]


@pytest.mark.parametrize('kind,field,edge,gate', [
    ('Spring', 'low', 99.5, 99.5 * (1 - .005)),
    ('UT', 'high', 100.5, 100.5 * (1 + .002)),
    ('SOS', 'close', 100.5, 100.5 * (1 + .002)),
    ('SOW', 'close', 99.5, 99.5 * (1 - .005)),
])
def test_edge_gate_is_inclusive_and_weaker_intrusion_is_rejected(kind, field, edge, gate):
    frame = flat()
    if kind == 'Spring':
        frame.loc[frame.index[-1], ['low', 'close']] = [gate, 100.]
    elif kind == 'UT':
        frame.loc[frame.index[-1], ['high', 'close']] = [gate, 100.]
    elif kind == 'SOS':
        frame.loc[frame.index[-1], ['high', 'close']] = [102., gate]
    else:
        frame.loc[frame.index[-1], ['low', 'close']] = [97., gate]
    assert event_types(frame) == [kind]
    weak = frame.copy()
    weak.loc[weak.index[-1], field] = gate + (0.00001 if kind in ('Spring', 'SOW') else -0.00001)
    assert kind not in event_types(weak)


@pytest.mark.parametrize('kind,row', [
    ('Spring', {'low': 97., 'close': 100.}),
    ('UT', {'high': 104., 'close': 100.}),
    ('SOS', {'high': 104., 'close': 103.}),
    ('SOW', {'low': 96., 'close': 97.}),
])
def test_all_four_initial_events_require_prior_20_valid_bar_median_volume(kind, row):
    frame = flat()
    for key, value in row.items():
        frame.loc[frame.index[-1], key] = value
    frame.loc[frame.index[-1], 'volume'] = 999.
    assert kind not in event_types(frame)
    frame.loc[frame.index[-1], 'volume'] = 1000.
    assert event_types(frame) == [kind]


def parent_and_retest(kind, *, margin_valid=True, volume_valid=True, retest_extra=0.0):
    frame = flat(63)
    i = frame.index
    if kind == 'LPS':
        edge = 100.5
        parent_close = 103. if margin_valid else edge * (1 + .001)
        frame.loc[i[-3], ['high', 'close', 'volume']] = [104., parent_close, 1000. if volume_valid else 999.]
        frame.loc[i[-2], ['open', 'high', 'low', 'close']] = [103., 105., 102., 104.]
        retest_close = edge * (1 + .002) + retest_extra
        frame.loc[i[-1], ['open', 'high', 'low', 'close']] = [101., 102., 100.4, retest_close]
    else:
        edge = 99.5
        parent_close = 97. if margin_valid else edge * (1 - .001)
        frame.loc[i[-3], ['low', 'close', 'volume']] = [96., parent_close, 1000. if volume_valid else 999.]
        frame.loc[i[-2], ['open', 'high', 'low', 'close']] = [97., 98., 95.5, 96.]
        retest_close = edge * (1 - .002) - retest_extra
        frame.loc[i[-1], ['open', 'high', 'low', 'close']] = [98., 100., 97.5, retest_close]
    return frame, edge


@pytest.mark.parametrize('kind', ['LPS', 'LPSY'])
def test_retest_margin_is_inclusive_and_parent_must_pass_new_rules(kind):
    frame, edge = parent_and_retest(kind)
    expected_parent = 'SOS' if kind == 'LPS' else 'SOW'
    assert event_types(frame) == [expected_parent, kind]
    weak = frame.copy()
    weak.loc[weak.index[-1], 'close'] += -0.00001 if kind == 'LPS' else 0.00001
    assert event_types(weak) == [expected_parent]
    assert kind not in event_types(parent_and_retest(kind, margin_valid=False)[0])
    assert kind not in event_types(parent_and_retest(kind, volume_valid=False)[0])


@pytest.mark.parametrize('kind', ['LPS', 'LPSY'])
def test_weak_retest_does_not_consume_first_qualifying_parent_retest(kind):
    frame, edge = parent_and_retest(kind)
    weak = frame.copy()
    weak.loc[weak.index[-1], 'close'] = edge * (1 + (.001 if kind == 'LPS' else -.001))
    assert event_types(weak) == ['SOS' if kind == 'LPS' else 'SOW']
    advance = pd.DataFrame([weak.iloc[-1].to_dict(), weak.iloc[-1].to_dict()],
                           index=pd.bdate_range(weak.index[-1] + pd.offsets.BDay(1), periods=2))
    advance.loc[advance.index[0], ['open', 'high', 'low', 'close']] = (
        [102., 105., 102., 103.] if kind == 'LPS' else [98., 98., 95., 96.])
    advance.loc[advance.index[1], ['open', 'high', 'low', 'close']] = frame.iloc[-1][['open', 'high', 'low', 'close']].tolist()
    assert event_types(pd.concat([weak, advance]))[-1] == kind


@pytest.mark.parametrize('kind', ['Spring', 'UT', 'SOS', 'SOW', 'LPS', 'LPSY'])
def test_fast_full_market_auditor_matches_observer_under_new_rules(kind):
    if kind in ('LPS', 'LPSY'):
        frame = parent_and_retest(kind)[0]
    else:
        frame = flat()
        row = {'Spring': {'low': 97., 'close': 100.},
               'UT': {'high': 104., 'close': 100.},
               'SOS': {'high': 104., 'close': 103.},
               'SOW': {'low': 96., 'close': 97.}}[kind]
        for key, value in row.items():
            frame.loc[frame.index[-1], key] = value
    assert assert_parity(frame, fast_events(frame)) == len(observe_wyckoff(frame)['events'])
