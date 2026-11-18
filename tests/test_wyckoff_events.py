"""Causal, observational Wyckoff event contracts (no ABCD phases)."""
import pandas as pd

from app.wyckoff_events import observe_wyckoff


def bars(closes, *, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({"open": closes, "high": highs or [x + 0.5 for x in closes],
                         "low": lows or [x - 0.5 for x in closes],
                         "close": closes, "volume": [1000] * n},
                        index=pd.bdate_range("2024-01-01", periods=n))


def test_insufficient_history_is_explicit_not_a_fabricated_phase():
    result = observe_wyckoff(bars([100.] * 39))
    assert set(result) == {"ok", "as_of_date", "price_basis", "box", "trend", "events", "current", "reason"}
    assert "insufficient_traded_bars" in result["reason"]
    assert result["ok"] is False
    assert result["box"] is None
    assert result["events"] == []
    assert result["current"] is None
    assert result["as_of_date"] == "2024-02-22"


def test_spring_is_candidate_then_confirmed_with_frozen_prior_box():
    spring = bars([100.] * 61)
    spring.loc[spring.index[-1], ["low", "close"]] = [97., 100.]
    first = observe_wyckoff(spring)
    assert first["box"]["lower"] == 99.5
    assert first["events"][-1]["type"] == "Spring"
    assert first["events"][-1]["status"] == "candidate"
    assert first["events"][-1]["confirmation_date"] is None
    assert first["events"][-1]["evidence"]["boundary"] == 99.5
    next_day = bars([100.] * 62)
    next_day.loc[next_day.index[-2], ["low", "close"]] = [97., 100.]
    next_day.loc[next_day.index[-1], ["open", "high", "low", "close"]] = [100., 101.5, 99.5, 101.]
    confirmed = next(e for e in observe_wyckoff(next_day)["events"] if e["type"] == "Spring")
    assert confirmed["type"] == "Spring"
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmation_date"] == str(next_day.index[-1].date())
    assert confirmed["evidence"]["boundary"] == first["events"][-1]["evidence"]["boundary"]
    assert confirmed["invalidated_by"] is None


def test_ut_candidate_invalidates_on_close_above_old_upper():
    frame = bars([100.] * 62)
    frame.loc[frame.index[-2], ["high", "close"]] = [104., 100.]
    frame.loc[frame.index[-1], ["high", "close"]] = [105., 103.]
    result = observe_wyckoff(frame)
    ut = next(e for e in result["events"] if e["type"] == "UT")
    assert ut["status"] == "invalidated"
    assert ut["invalidated_by"]["date"] == str(frame.index[-1].date())
    assert ut["evidence"]["boundary"] == 100.5


def test_breakout_retest_requires_later_confirmation_not_same_day():
    frame = bars([100.] * 64)
    frame.loc[frame.index[-4], ["high", "close"]] = [104., 103.]
    frame.loc[frame.index[-3], ["open", "high", "low", "close"]] = [103., 104.5, 102.5, 103.5]
    frame.loc[frame.index[-2], ["open", "high", "low", "close"]] = [102., 103., 100.2, 102.]
    frame.loc[frame.index[-1], ["high", "close"]] = [105., 104.]
    at_break = observe_wyckoff(frame.iloc[:61])
    assert at_break["events"][-1]["type"] == "SOS"
    assert at_break["events"][-1]["status"] == "candidate"
    assert at_break["events"][-1]["evidence"]["boundary"] == 100.5
    at_retest = observe_wyckoff(frame.iloc[:63])
    assert at_retest["events"][-1]["type"] == "LPS"
    assert at_retest["events"][-1]["status"] == "candidate"
    assert at_retest["events"][-1]["evidence"]["box_lower"] == at_break["events"][-1]["evidence"]["box_lower"]
    assert at_retest["events"][-1]["evidence"]["box_upper"] == at_break["events"][-1]["evidence"]["box_upper"]
    assert observe_wyckoff(frame)["events"][-1]["status"] == "confirmed"


def test_down_breakout_and_retest_are_symmetric():
    frame = bars([100.] * 64)
    frame.loc[frame.index[-4], ["low", "close"]] = [96., 97.]
    frame.loc[frame.index[-3], ["open", "high", "low", "close"]] = [97., 98., 95.5, 96.5]
    frame.loc[frame.index[-2], ["open", "high", "low", "close"]] = [98., 99.8, 97.5, 98.]
    frame.loc[frame.index[-1], ["low", "close"]] = [95., 96.]
    events = observe_wyckoff(frame)["events"]
    assert [(e["type"], e["status"]) for e in events] == [("SOW", "confirmed"), ("LPSY", "confirmed")]


def test_zero_volume_bar_cannot_create_or_confirm_price_volume_event():
    frame = bars([100.] * 62)
    frame.loc[frame.index[-2], ['low', 'close', 'volume']] = [97., 100., 0.]
    assert observe_wyckoff(frame)['events'] == []


def test_event_exposes_observed_volume_and_prior_comparison_without_claiming_intent():
    frame = bars([100.] * 61)
    frame.loc[frame.index[-1], ['low', 'volume']] = [97., 1500.]
    event = observe_wyckoff(frame)['events'][-1]
    assert event['evidence']['volume'] == 1500.
    assert event['evidence']['prior_volume_median_20'] == 1000.
    assert event['evidence']['volume_ratio_20'] == 1.5


def test_holding_frozen_boundary_without_strength_is_not_confirmation():
    frame = bars([100.] * 62)
    frame.loc[frame.index[-2], 'low'] = 97.
    frame.loc[frame.index[-1], ['open', 'high', 'low', 'close']] = [99.6, 100.2, 99.5, 99.6]
    spring = next(e for e in observe_wyckoff(frame)['events'] if e['type'] == 'Spring')
    assert spring['status'] == 'candidate'
    assert spring['confirmation_date'] is None


def test_sos_holding_edge_without_new_high_close_remains_candidate():
    frame = bars([100.] * 62)
    frame.loc[frame.index[-2], ['open', 'high', 'low', 'close']] = [100., 104., 100., 103.]
    frame.loc[frame.index[-1], ['open', 'high', 'low', 'close']] = [103., 104., 102., 103.]
    sos = next(e for e in observe_wyckoff(frame)['events'] if e['type'] == 'SOS')
    assert sos['status'] == 'candidate'


def test_confirmed_event_can_later_invalidate_when_frozen_boundary_breaks():
    frame = bars([100.] * 63)
    frame.loc[frame.index[-3], 'low'] = 97.
    frame.loc[frame.index[-2], ['open', 'high', 'low', 'close']] = [100., 101.5, 99.5, 101.]
    frame.loc[frame.index[-1], ['open', 'high', 'low', 'close']] = [99., 99.5, 98.5, 99.]
    confirmed = next(e for e in observe_wyckoff(frame.iloc[:62])['events'] if e['type'] == 'Spring')
    invalidated = next(e for e in observe_wyckoff(frame)['events'] if e['type'] == 'Spring')
    assert confirmed['status'] == 'confirmed'
    assert invalidated['status'] == 'invalidated'
    assert invalidated['confirmation_date'] == str(frame.index[-2].date())
    assert invalidated['invalidated_by']['date'] == str(frame.index[-1].date())
    assert invalidated['evidence'] == confirmed['evidence']


def test_no_fabricated_event_when_both_box_edges_are_pierced():
    frame = bars([100.] * 61)
    frame.loc[frame.index[-1], ["high", "low", "close"]] = [104., 98., 100.]
    assert observe_wyckoff(frame)["events"] == []
    assert observe_wyckoff(frame)["current"] is None


def test_zero_price_placeholder_and_calendar_gaps_do_not_shift_event():
    frame = bars([100.] * 61)
    frame.loc[frame.index[-1], ["low", "close"]] = [97., 100.]
    result = observe_wyckoff(frame)
    zero = pd.DataFrame({"open": [0.], "high": [0.], "low": [0.],
                         "close": [0.], "volume": [0.]}, index=[pd.Timestamp("2024-02-01")])
    with_zero = pd.concat([frame, zero]).sort_index()
    assert observe_wyckoff(with_zero) == result
    assert observe_wyckoff(frame.iloc[:30])["events"] == []


def test_prefix_recomputation_never_changes_old_snapshot():
    frame = bars([100.] * 64)
    frame.loc[frame.index[-4], ["low", "close"]] = [97., 100.]
    frame.loc[frame.index[-3], ["low", "close"]] = [98., 100.]
    frame.loc[frame.index[-2], ["high", "close"]] = [105., 104.]
    frame.loc[frame.index[-1], ["high", "close"]] = [106., 105.]
    prefix = frame.iloc[:61].copy()
    before = observe_wyckoff(prefix)
    observe_wyckoff(frame)
    assert observe_wyckoff(prefix) == before
    assert before["events"][-1]["status"] == "candidate"
    assert "stage" not in before and "score" not in before
