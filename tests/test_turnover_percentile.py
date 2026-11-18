"""Point-in-time daily turnover percentile contract."""
from datetime import date
from datetime import timedelta

from app.turnover_percentile import compute_turnover_percentile, read_stock_share_reports


def bar(day, volume=100, close=10, open_=10):
    return {"date": day, "open": open_, "close": close, "volume": volume}


def report(period, announced, shares):
    return {"period": period, "announce_date": announced, "已上市流通A股": shares}


def test_seven_effective_days_trim_extremes_and_require_120_windows():
    start = date(2024, 1, 1)
    bars = [bar(start + timedelta(days=i), 1000 * (i + 1)) for i in range(126)]
    bars[-1]['volume'] = 999000
    result = compute_turnover_percentile(bars, [report('2023A', 20231201, 1000)])
    assert result['status'] == 'ok'
    assert result['sample_size'] == 120
    assert result['daily_samples'][-1]['rolling_7_trimmed_avg_pct'] == 12300.0
    assert result['daily_samples'][-1]['eligible_window_count'] == 120
    assert result['daily_samples'][0]['rolling_percentile'] is None
    assert result['daily_samples'][-1]['rolling_percentile'] == result['percentile']


def test_short_listing_has_null_rank_and_missing_share_day_does_not_enter_seven():
    start = date(2025, 1, 1)
    bars = [bar(start + timedelta(days=i), 100 * (i + 1)) for i in range(8)]
    reports = [report('2024A', 20241201, 1000), report('2025Q1', 20250104, 0)]
    result = compute_turnover_percentile(bars, reports)
    assert result['status'] == 'missing_current_shares'
    assert result['sample_size'] == 0
    assert all(row['date'] < '2025-01-05' for row in result['daily_samples'])


def test_current_day_included_and_one_calendar_year_window_with_ties():
    bars = [bar(date(2023, 2, 28), 900), bar(date(2024, 2, 28), 100),
            bar(date(2024, 2, 29), 200), bar(date(2025, 2, 28), 200)]
    result = compute_turnover_percentile(bars, [report("2022A", 20230101, 1000)])
    assert result["status"] == "insufficient_history"
    assert result["sample_size"] == 0
    assert result["percentile"] is None
    assert result["current_turnover"] == 0.2
    assert result["current_date"] == "2025-02-28"
    assert result["window_start"] == "2024-02-28"
    assert result["denominator_source"] == "report_proxy"


def test_announcement_day_excluded_and_latest_invalid_period_masks_old_report():
    bars = [bar(date(2025, 4, 1)), bar(date(2025, 4, 2)),
            bar(date(2025, 4, 3)), bar(date(2025, 4, 4))]
    reports = [report("2024A", 20250331, 1000),
               report("2025Q1", 20250402, 0)]
    result = compute_turnover_percentile(bars, reports)
    assert result["sample_size"] == 0
    assert result["current_turnover"] is None
    assert result["percentile"] is None
    assert result["latest_report_period"] == "2025Q1"
    assert result["status"] == "missing_current_shares"


def test_late_revision_of_old_period_does_not_override_newer_period():
    result = compute_turnover_percentile(
        [bar(date(2025, 7, 5), 200)],
        [report("2025Q1", 20250501, 1000), report("2024A", 20250701, 500)])
    assert result["current_turnover"] == 0.2
    assert result["latest_report_period"] == "2025Q1"


def test_no_announcement_before_current_day_means_null_not_future_shares():
    result = compute_turnover_percentile(
        [bar(date(2025, 4, 1))], [report("2025Q1", 20250402, 1000)])
    assert result["status"] == "missing_current_shares"
    assert result["sample_size"] == 0
    assert result["denominator_source"] is None


def test_gbbq_quarter_end_unverified_falls_back_to_pit_report():
    result = compute_turnover_percentile(
        [bar(date(2025, 4, 1), 200)], [report("2024A", 20250301, 1000)],
        gbbq_events=[{"date": 20250331, "category": 5, "post_shares_v3": 3,
                      "verified_effective_date": False}])
    assert result["current_turnover"] == 0.2
    assert result["denominator_source"] == "report_proxy"


def test_verified_category_9_v3_is_post_shares_in_ten_thousands():
    result = compute_turnover_percentile(
        [bar(date(2025, 4, 2), 100), bar(date(2025, 4, 3), 200)],
        [report("2024A", 20250301, 1000)],
        gbbq_events=[{"datetime": 20250402, "category": 9,
                      "songgu_qianzongguben": 2, "verified_effective_date": True}])
    assert result["current_turnover"] == 0.01
    assert result["denominator_source"] == "gbbq_verified"
    assert result["sample_size"] == 0


def test_bad_bars_filtered_without_changing_latest_valid_date():
    result = compute_turnover_percentile(
        [bar(date(2025, 2, 1)), bar(date(2025, 2, 2), close=0),
         bar(date(2025, 2, 3), volume=0)], [report("2024A", 20250101, 1000)])
    assert result["current_date"] == "2025-02-01"
    assert result["sample_size"] == 0


def test_six_digit_announcement_date_resolves_to_2000s_not_missing():
    result = compute_turnover_percentile(
        [bar(date(2025, 4, 2))], [report("2024A", 250401, 1000)])
    assert result["latest_announce_date"] == "2025-04-01"
    assert result["current_turnover"] == 0.1


def test_audit_daily_samples_show_share_source_and_excluded_invalid_day():
    result = compute_turnover_percentile(
        [bar(date(2025, 4, 1)), bar(date(2025, 4, 2)), bar(date(2025, 4, 3))],
        [report("2024A", 20250301, 1000), report("2025Q1", 20250402, None)])
    assert [{key: value for key, value in row.items()
             if key not in ('rolling_7_trimmed_avg_pct', 'rolling_percentile', 'eligible_window_count')}
            for row in result["daily_samples"]] == [
        {"date": "2025-04-01", "turnover": 0.1,
         "shares": 1000.0, "source": "report_proxy", "report_period": "2024A", "report_announce": "2025-03-01"},
        {"date": "2025-04-02", "turnover": 0.1,
         "shares": 1000.0, "source": "report_proxy", "report_period": "2024A", "report_announce": "2025-03-01"},
    ]
    assert all(row['rolling_percentile'] is None and row['eligible_window_count'] == 0
               for row in result['daily_samples'])


def test_reader_rejects_incomplete_quarter_schema_instead_of_using_older_report(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pytest

    pq.write_table(pa.table({"code": ["600519"], "announce_date": [20260430]}),
                   tmp_path / "2026Q1.parquet")
    with pytest.raises(ValueError, match="已上市流通A股"):
        read_stock_share_reports(tmp_path, "600519")


def test_parquet_reader_keeps_invalid_stock_row_and_filters_other_codes(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table({"code": ["600519", "000001"],
                             "已上市流通A股": [0.0, 999.0],
                             "announce_date": [20260430, 20260420]}),
                   tmp_path / "2026Q1.parquet")
    rows = read_stock_share_reports(tmp_path, "600519")
    assert rows == [{"period": "2026Q1", "已上市流通A股": 0.0,
                     "announce_date": 20260430}]
