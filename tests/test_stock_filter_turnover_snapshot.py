"""PIT turnover publication respects source dates and whole-universe keys."""
import pandas as pd
from datetime import date, timedelta

from app.stock_filter_turnover_snapshot import build_turnover_snapshot


def test_snapshot_ranks_seven_day_mean_using_two_year_prehistory():
    start = date(2023, 1, 1)
    bars = pd.DataFrame([{'date': start + timedelta(days=i * 2), 'market': 'sz',
                          'symbol': '000001', 'open': 10, 'close': 10, 'volume': 100 + i}
                         for i in range(380)])
    end = bars.iloc[-1]['date'].isoformat()
    reports = {'000001': [{'period': '2022A', 'announce_date': 20221201,
                           '已上市流通A股': 1000}]}
    payload, history = build_turnover_snapshot(bars, reports, as_of_date=end,
                                               universe_keys={'sz:000001'})
    item = payload['stocks']['sz:000001']
    assert item['turnover_percentile_1y'] == 100.0
    assert item['turnover_percentile_1y_status'] == 'ok'
    assert item['turnover_percentile_1y_sample_count'] > 120
    assert item['turnover_percentile_1y_rolling_7_trimmed_avg_pct'] > 0
    assert history[0]['eligible_window_count'] >= 120
    assert history[0]['rolling_percentile'] is not None
    assert history[-1]['rolling_percentile'] == item['turnover_percentile_1y']
    assert payload['schema_version'].endswith('v2')


def test_historical_percentile_uses_each_ending_day_not_todays_rank():
    start = date(2023, 1, 1)
    bars = pd.DataFrame([{'date': start + timedelta(days=2 * i), 'market': 'sz',
                          'symbol': '000001', 'open': 10, 'close': 10,
                          'volume': 500 - i if i < 200 else i + 100}
                         for i in range(380)])
    end = bars.iloc[-1]['date'].isoformat()
    reports = {'000001': [{'period': '2022A', 'announce_date': 20221201,
                           '已上市流通A股': 1000}]}
    payload, history = build_turnover_snapshot(bars, reports, as_of_date=end,
                                               universe_keys={'sz:000001'})
    assert history[0]['rolling_percentile'] < history[-1]['rolling_percentile']
    assert history[-1]['rolling_percentile'] == payload['stocks']['sz:000001']['turnover_percentile_1y']
    assert history[0]['eligible_window_count'] >= 120


def test_build_snapshot_keeps_missing_and_daily_audit():
    bars = pd.DataFrame([
        {'date': '2025-04-17', 'market': 'sz', 'symbol': '000001', 'open': 10, 'close': 10, 'volume': 100},
        {'date': '2025-04-18', 'market': 'sz', 'symbol': '000001', 'open': 10, 'close': 10, 'volume': 200},
        {'date': '2025-04-18', 'market': 'sz', 'symbol': '000002', 'open': 10, 'close': 10, 'volume': 100},
    ])
    reports = {'000001': [{'period': '2024A', 'announce_date': 20250417, '已上市流通A股': 1000}]}
    payload, history = build_turnover_snapshot(bars, reports, as_of_date='2025-04-18',
                                               universe_keys={'sz:000001', 'sz:000002', 'sz:000003'})
    assert set(payload['stocks']) == {'sz:000001', 'sz:000002', 'sz:000003'}
    item = payload['stocks']['sz:000001']
    assert item['turnover_percentile_1y'] is None
    assert item['turnover_percentile_1y_status'] == 'insufficient_history'
    assert item['turnover_percentile_1y_sample_count'] == 0
    assert item['turnover_percentile_1y_current_pct'] == 20.0
    assert item['turnover_percentile_1y_source'] == 'report_proxy'
    assert item['turnover_percentile_1y_current_turnover'] == item['turnover_percentile_1y_current_pct']
    assert item['turnover_percentile_1y_current_shares_source'] == 'report_proxy'
    assert item['turnover_percentile_1y_report_fallback_count'] == 1
    assert payload['stocks']['sz:000002']['turnover_percentile_1y'] is None
    assert payload['stocks']['sz:000003']['turnover_percentile_1y'] is None
    assert len(history) == 1 and history[0]['date'] == '2025-04-18'
    assert history[0]['shares'] == 1000
    assert history[0]['report_period'] == '2024A'
    assert history[0]['report_announce'] == '2025-04-17'


def test_future_qfq_bar_never_changes_historical_result():
    bars = pd.DataFrame([
        {'date': '2025-04-18', 'market': 'sz', 'symbol': '000001', 'open': 10, 'close': 10, 'volume': 100},
        {'date': '2025-04-21', 'market': 'sz', 'symbol': '000001', 'open': 10, 'close': 10, 'volume': 900},
    ])
    reports = {'000001': [{'period': '2024A', 'announce_date': 20250417, '已上市流通A股': 1000}]}
    payload, history = build_turnover_snapshot(bars, reports, as_of_date='2025-04-18', universe_keys={'sz:000001'})
    assert payload['stocks']['sz:000001']['turnover_percentile_1y_current_pct'] == 10.0
    assert len(history) == 1


def test_no_matching_latest_bar_does_not_mislabel_stale_signal():
    bars = pd.DataFrame([{'date': '2025-04-17', 'market': 'sz', 'symbol': '000001',
                          'open': 10, 'close': 10, 'volume': 100}])
    reports = {'000001': [{'period': '2024A', 'announce_date': 20250416, '已上市流通A股': 1000}]}
    payload, _ = build_turnover_snapshot(bars, reports, as_of_date='2025-04-18', universe_keys={'sz:000001'})
    assert payload['stocks']['sz:000001']['turnover_percentile_1y'] is None
    assert payload['stocks']['sz:000001']['turnover_percentile_1y_status'] == 'stale_bar'
