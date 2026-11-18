"""Quality audit aggregation contracts; names are current, never historical PIT."""
import csv
import json
from scripts.report_wyckoff_quality import select_pool, margin_fraction, analyze, publish, duration_for_symbol, summarize_durations


def test_current_non_st_pool_requires_matching_name_full_end_and_valid_bars():
    coverage = [
        dict(market='BJ', symbol='920001', status='short_warmup', end_covered='True', traded_bars='210'),
        dict(market='SZ', symbol='000001', status='ok', end_covered='True', traded_bars='1000'),
        dict(market='SH', symbol='600000', status='source_ended_early', end_covered='False', traded_bars='1000'),
        dict(market='SZ', symbol='300001', status='ok', end_covered='True', traded_bars='39'),
    ]
    names = {('bj', '920001'): '示例公司', ('sz', '000001'): '*ST甲',
             ('sh', '600000'): '示例银行', ('sz', '300001'): '示例科技'}
    pool, reasons = select_pool(coverage, names)
    assert pool == {('BJ', '920001')}
    assert reasons == {'current_st_or_s': 1, 'source_not_asof': 1, 'insufficient_bars': 1}


def test_aggregation_separates_event_year_from_later_confirm_and_loss(tmp_path):
    with (tmp_path / 'coverage.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['market', 'symbol', 'status', 'end_covered', 'traded_bars'])
        w.writeheader()
        w.writerows([dict(market='BJ', symbol='920001', status='ok', end_covered='True', traded_bars='300'),
                     dict(market='SZ', symbol='000001', status='ok', end_covered='True', traded_bars='300')])
    fields = ['market', 'symbol', 'date', 'type', 'status', 'confirmation_date', 'invalidated_date',
              'boundary', 'low', 'high', 'close', 'volume_ratio_20']
    with (tmp_path / 'events.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows([
            dict(market='BJ', symbol='920001', date='2023-12-29', type='Spring', status='invalidated',
                 confirmation_date='2024-01-02', invalidated_date='2024-01-05',
                 boundary='10', low='9.99', high='10.4', close='10.1', volume_ratio_20='1.2'),
            dict(market='BJ', symbol='920001', date='2024-03-04', type='LPSY', status='confirmed',
                 confirmation_date='2024-03-05', invalidated_date='',
                 boundary='10', low='9.5', high='10.1', close='9.9', volume_ratio_20=''),
            dict(market='SZ', symbol='000001', date='2024-04-01', type='SOS', status='invalidated',
                 confirmation_date='', invalidated_date='2024-04-02',
                 boundary='10', low='9.8', high='10.3', close='10.2', volume_ratio_20='2')])
    (tmp_path / 'manifest.json').write_text(json.dumps({'events_total': 3, 'symbols_total': 2, 'resolution_as_of': '2026-10-30'}))
    with (tmp_path / 'year_type_status.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['year', 'type', 'status', 'count'])
        w.writeheader()
        w.writerows([dict(year='2023', type='Spring', status='invalidated', count=1),
                     dict(year='2024', type='LPSY', status='confirmed', count=1),
                     dict(year='2024', type='SOS', status='invalidated', count=1)])
    summary, samples = analyze(tmp_path, {('bj', '920001'): '示例公司', ('sz', '000001'): '*ST甲'})
    assert summary['raw_events'] == 3
    assert summary['current_eligible_symbols'] == 1
    assert summary['eligible_events'] == 2
    assert summary['event_year_type_status']['2023']['Spring']['invalidated'] == 1
    assert summary['event_year_type_status']['2024']['SOS']['invalidated'] == 0
    assert summary['resolution_year_type']['2024']['Spring']['confirmed'] == 1
    assert summary['resolution_year_type']['2024']['Spring']['invalidated'] == 1
    assert summary['ever_confirmed_then_invalidated'] == 1
    assert summary['margin_below_half_percent']['Spring'] == 1
    assert len(samples) == 2
    publish(tmp_path, {('bj', '920001'): '示例公司', ('sz', '000001'): '*ST甲'})
    assert (tmp_path / 'quality_summary.json').exists()
    assert (tmp_path / 'stratified_samples.csv').exists()
    assert (tmp_path / 'current_non_st_pool.csv').exists()
    assert (tmp_path / 'year_type_status_current_pool.csv').exists()
    assert (tmp_path / 'report_manifest.json').exists()


def test_lifecycle_durations_count_actual_valid_bars_not_calendar_days():
    rows = [
        dict(date='2023-01-05', type='Spring', invalidated_date='2023-01-09'),
        dict(date='2023-01-05', type='SOS', invalidated_date='2023-01-10'),
        dict(date='2023-01-10', type='UT', invalidated_date=''),
    ]
    dates = ['2023-01-02', '2023-01-05', '2023-01-09', '2023-01-10']
    c = duration_for_symbol(rows, dates)
    assert c[('Spring', 'invalidated')] == 1
    assert c[('Spring', 'within_1_valid_bar')] == 1
    assert c[('Spring', 'within_5_valid_bars')] == 1
    assert c[('SOS', 'within_1_valid_bar')] == 0
    assert c[('SOS', 'within_5_valid_bars')] == 1
    assert c[('UT', 'unresolved_asof')] == 1


def test_duration_summary_reloads_valid_qfq_dates_per_security(tmp_path, monkeypatch):
    import pandas as pd
    import scripts.report_wyckoff_quality as report
    with (tmp_path / 'events.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, ['market', 'symbol', 'date', 'type', 'invalidated_date'])
        w.writeheader()
        w.writerow(dict(market='SZ', symbol='000001', date='2023-01-05', type='Spring', invalidated_date='2023-01-09'))
    # The gap from Thu 5th to Mon 9th is exactly one VALID bar, not four days.
    bars = pd.DataFrame({'open': [10, 10, 10], 'high': [11, 11, 11],
                         'low': [9, 9, 9], 'close': [10, 10, 10], 'volume': [1, 1, 1]},
                        index=pd.to_datetime(['2023-01-02', '2023-01-05', '2023-01-09']))
    monkeypatch.setattr(report, 'load_tdx_qfq_daily', lambda symbol, source: bars)
    monkeypatch.setattr(report, 'clean_wyckoff_bars', lambda source: source)
    got = summarize_durations(tmp_path, {('SZ', '000001')}, '2026-10-30', tmp_path)
    assert got[('Spring', 'within_1_valid_bar')] == 1
    assert got[('Spring', 'invalidated')] == 1


def test_duration_summary_rejects_nonfinite_source_bars(tmp_path, monkeypatch):
    import pandas as pd
    import scripts.report_wyckoff_quality as report
    with (tmp_path / 'events.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, ['market', 'symbol', 'date', 'type', 'invalidated_date'])
        w.writeheader()
        w.writerow(dict(market='SZ', symbol='000001', date='2023-01-05', type='Spring', invalidated_date=''))
    bars = pd.DataFrame({'open': [10], 'high': [float('inf')], 'low': [9],
                         'close': [10], 'volume': [1]}, index=pd.to_datetime(['2023-01-05']))
    monkeypatch.setattr(report, 'load_tdx_qfq_daily', lambda symbol, source: bars)
    monkeypatch.setattr(report, 'clean_wyckoff_bars', lambda source: source)
    import pytest
    with pytest.raises(ValueError, match='nonfinite'):
        summarize_durations(tmp_path, {('SZ', '000001')}, '2026-10-30', tmp_path)


def test_margin_is_relative_to_event_frozen_boundary_not_current_box():
    row = dict(type='Spring', boundary='10', low='9.98', high='10.40', close='10.21')
    assert abs(margin_fraction(row) - 0.002) < 1e-12
    row = dict(type='SOS', boundary='11', low='10.95', high='11.20', close='11.11')
    assert abs(margin_fraction(row) - 0.01) < 1e-12
