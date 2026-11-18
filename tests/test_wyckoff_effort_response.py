"""Causal equal-volume price-response evidence, separate from Wyckoff events/phases."""
import pandas as pd
import pytest


def _bars(recent_return=0.02):
    days = pd.bdate_range('2026-01-01', periods=80)
    closes = [100.0] * 60 + [100.0 * (1 + recent_return)] * 20
    frame = pd.DataFrame({'open': [100.0] * 80, 'high': [104.0] * 80,
                          'low': [96.0] * 80, 'close': closes,
                          'volume': [1000.0] * 60 + [1100.0] * 20}, index=days)
    index = pd.DataFrame({'open': [100.0] * 80, 'close': [100.0] * 80}, index=days)
    return frame, index


def test_equal_volume_response_matches_only_earlier_reference_and_reports_evidence():
    from app.wyckoff_effort_response import measure_equal_volume_response
    bars, index = _bars()
    result = measure_equal_volume_response(bars, index)
    assert result['status'] == 'available'
    assert result['as_of_date'] == str(bars.index[-1].date())
    assert result['observed_days'] == 20
    assert result['paired_days'] == 20
    assert result['pair_count'] == 1200
    assert result['median_excess_response_pct'] == pytest.approx(2.0)
    assert result['positive_pair_fraction'] == 1.0
    assert result['matched_volume_tolerance'] == 0.15
    assert result['reference_days'] == 120
    assert result['recent_days'] == 20


def test_sse_index_reader_converts_tdx_cents_and_fails_closed_on_missing_file(tmp_path):
    import struct
    from app.wyckoff_effort_response import load_sse_intraday_index
    path = tmp_path / 'sh000001.day'
    assert load_sse_intraday_index(path) is None
    path.write_bytes(b''.join(struct.pack('<5ifII', day, open_, high, low, close, 0.0, 0, 0)
                       for day, open_, high, low, close in
                       [(20261029, 340000, 345000, 339000, 344000),
                        (20261030, 345000, 346000, 341000, 343000)]))
    frame = load_sse_intraday_index(path)
    assert list(frame.index.strftime('%Y-%m-%d')) == ['2026-10-29', '2026-10-30']
    assert frame.iloc[-1]['open'] == 3450
    assert frame.iloc[-1]['close'] == 3430


def test_daily_evidence_lists_pair_dates_and_components_for_audit():
    from app.wyckoff_effort_response import measure_equal_volume_response
    bars, index = _bars()
    result = measure_equal_volume_response(bars, index)
    evidence = result['daily_evidence']
    assert len(evidence) == 20
    assert evidence[0]['date'] == str(bars.index[-20].date())
    assert evidence[0]['volume'] == 1100
    assert evidence[0]['reference_count'] == 60
    assert evidence[0]['matched_reference_dates'][0] == str(bars.index[0].date())
    assert evidence[0]['matched_reference_dates'][-1] == str(bars.index[-21].date())
    assert evidence[0]['stock_intraday_pct'] == pytest.approx(2.0)
    assert evidence[0]['benchmark_intraday_pct'] == 0
    assert evidence[0]['reference_excess_median_pct'] == 0
    assert evidence[0]['excess_response_pct'] == pytest.approx(2.0)


def test_equal_volume_response_exposes_negative_residual_without_phase_label():
    from app.wyckoff_effort_response import measure_equal_volume_response
    bars, index = _bars(recent_return=-0.02)
    result = measure_equal_volume_response(bars, index)
    assert result['median_excess_response_pct'] == pytest.approx(-2.0)
    assert result['positive_pair_fraction'] == 0
    assert 'phase' not in result
    assert 'distribution' not in result


def test_missing_benchmark_blocks_metric_without_raw_stock_fallback():
    from app.wyckoff_effort_response import measure_equal_volume_response
    bars, index = _bars()
    index = index.drop(index.index[-1])
    result = measure_equal_volume_response(bars, index)
    assert result['status'] == 'unavailable'
    assert result['reason'] == 'benchmark_missing_sessions'
    assert result['median_excess_response_pct'] is None


def test_as_of_discards_future_stock_bars_and_index_changes():
    from app.wyckoff_effort_response import measure_equal_volume_response
    bars, index = _bars()
    as_of = str(bars.index[-1].date())
    expected = measure_equal_volume_response(bars, index)
    next_day = bars.index[-1] + pd.offsets.BDay(1)
    bars.loc[next_day] = {'open': 100.0, 'high': 105.0, 'low': 90.0,
                          'close': 90.0, 'volume': 1100.0}
    index.loc[next_day] = {'open': 100.0, 'close': 110.0}
    result = measure_equal_volume_response(bars, index, as_of_date=as_of)
    assert result == expected


def test_insufficient_comparable_volume_days_is_not_a_zero_score():
    from app.wyckoff_effort_response import measure_equal_volume_response
    bars, index = _bars()
    bars.loc[bars.index[-20:], 'volume'] = 2000
    result = measure_equal_volume_response(bars, index)
    assert result['status'] == 'unavailable'
    assert result['reason'] == 'insufficient_matched_volume_days'
    assert result['paired_days'] == 0
    assert result['median_excess_response_pct'] is None
