"""Daily own-history PE percentile: raw prices and point-in-time disclosed TTM earnings."""
from datetime import date
from pathlib import Path

import pandas as pd

from app.relative_valuation.daily_pe_percentile import compute_daily_pe_percentile, read_stock_disclosures


def test_report_only_affects_trading_day_after_announcement_and_uses_disclosed_shares():
    bars = [(date(2026, 10, 29), 10.0), (date(2026, 10, 30), 12.0),
            (date(2026, 11, 2), 12.0), (date(2026, 11, 3), 16.0)]
    reports = [
        {"period": "2026Q2", "announce_date": "20260820", "ttm_profit_yi": 2.0, "total_shares": 1e8},
        {"period": "2026Q3", "announce_date": "20261030", "ttm_profit_yi": 4.0, "total_shares": 2e8},
    ]
    result = compute_daily_pe_percentile(bars, reports)
    assert result["status"] == "ok"
    assert result["current_pe"] == 8.0
    assert result["latest_report_period"] == "2026Q3"
    assert result["latest_announce_date"] == "2026-10-30"
    assert result["valid_days"] == 4
    assert result["percentile"] == 100.0  # daily PE = 5, 6, 6, 8
    assert result["basis"] == "available_history"
    assert result["price_date"] == "2026-11-03"


def test_five_calendar_years_excludes_older_days_and_shorter_history_is_labeled():
    reports = [{"period": "2020A", "announce_date": "20210401", "ttm_profit_yi": 1.0, "total_shares": 1e8}]
    bars = [(date(2021, 1, 10), 1.0), (date(2021, 11, 2), 2.0),
            (date(2024, 1, 2), 3.0), (date(2026, 11, 3), 4.0)]
    result = compute_daily_pe_percentile(bars, reports)
    assert result["basis"] == "five_years"
    assert result["valid_days"] == 2
    assert result["window_start"] == "2021-11-03"
    assert result["first_valid_date"] == "2024-01-02"
    assert result["percentile"] == 100.0


def test_latest_report_loss_does_not_fallback_to_old_profit_or_old_percentile():
    bars = [(date(2026, 1, 2), 10), (date(2026, 5, 2), 10), (date(2026, 11, 2), 10)]
    reports = [
        {"period": "2025A", "announce_date": "20251231", "ttm_profit_yi": 1.0, "total_shares": 1e8},
        {"period": "2026Q3", "announce_date": "20261030", "ttm_profit_yi": -1.0, "total_shares": 1e8},
    ]
    result = compute_daily_pe_percentile(bars, reports)
    assert result["status"] == "nonpositive_ttm_profit"
    assert result["latest_report_period"] == "2026Q3"
    assert result["percentile"] is None
    assert result["current_pe"] is None
    assert result["valid_days"] == 2


def test_missing_announcement_or_shares_never_backfills_or_treats_as_valid():
    bars = [(date(2026, 11, 3), 9), (date(2026, 11, 4), 10)]
    reports = [
        {"period": "2026Q2", "announce_date": None, "ttm_profit_yi": 2, "total_shares": 1e8},
        {"period": "2026Q3", "announce_date": "20261030", "ttm_profit_yi": 2, "total_shares": None},
    ]
    result = compute_daily_pe_percentile(bars, reports)
    assert result["status"] == "missing_shares"
    assert result["valid_days"] == 0
    assert result["percentile"] is None


def test_current_quote_compares_against_daily_history_not_quarterly_pe():
    bars = [(date(2026, 11, 3), 10.0), (date(2026, 11, 4), 20.0)]
    reports = [{"period": "2026Q2", "announce_date": "20260820", "ttm_profit_yi": 2, "total_shares": 1e8}]
    result = compute_daily_pe_percentile(bars, reports, current_price=15.0)
    assert result["current_pe"] == 7.5
    assert result["percentile"] == 50.0
    assert result["valid_days"] == 2
    assert result["price_date"] == "2026-11-04"


def test_optional_daily_history_ranks_each_valid_pe_against_same_five_year_sample():
    bars = [(date(2026, 10, 30), 10.0), (date(2026, 11, 2), 20.0),
            (date(2026, 11, 3), 30.0)]
    reports = [{"period": "2026Q2", "announce_date": "20261030",
                "ttm_profit_yi": 2.0, "total_shares": 1e8}]
    result = compute_daily_pe_percentile(bars, reports, include_history=True)
    assert result["valid_days"] == 2
    assert result["history_basis"] == "fixed_current_window"
    assert result["history"] == [
        {"date": "2026-11-02", "pe": 10.0, "percentile": 50.0},
        {"date": "2026-11-03", "pe": 15.0, "percentile": 100.0},
    ]
    assert result["history"][-1]["percentile"] == result["percentile"]


def test_late_prior_quarter_revision_does_not_displace_newer_report_period():
    bars = [(date(2026, 11, 2), 10), (date(2026, 11, 5), 10)]
    reports = [
        {"period": "2026Q3", "announce_date": "20261030", "ttm_profit_yi": 4, "total_shares": 1e8},
        {"period": "2026Q2", "announce_date": "20261103", "ttm_profit_yi": 1, "total_shares": 1e8},
    ]
    result = compute_daily_pe_percentile(bars, reports)
    assert result["latest_report_period"] == "2026Q3"
    assert result["current_pe"] == 2.5


def test_multiple_same_day_reports_are_all_excluded_until_next_trading_day():
    bars = [(date(2026, 10, 30), 10), (date(2026, 11, 2), 20)]
    reports = [
        {"period": "2026Q1", "announce_date": "20260420", "ttm_profit_yi": 2, "total_shares": 1e8},
        {"period": "2026Q2", "announce_date": "20261030", "ttm_profit_yi": 4, "total_shares": 1e8},
        {"period": "2026Q3", "announce_date": "20261030", "ttm_profit_yi": 10, "total_shares": 1e8},
    ]
    result = compute_daily_pe_percentile(bars, reports)
    assert result["latest_report_period"] == "2026Q3"
    assert result["current_pe"] == 2.0
    assert result["percentile"] == 50.0  # Oct 30 uses Q1, Nov 2 uses Q3


def test_disclosure_reader_filters_one_stock_and_rejects_unknown_ttm(tmp_path: Path):
    data = pd.DataFrame([
        {"code": "002624", "announce_date": 20261030, "近一年归母净利润（万元）": 45247.5, "总股本": 1939968384},
        {"code": "600519", "announce_date": 20261031, "近一年归母净利润（万元）": 8216074.5, "总股本": 1250081664},
    ]).set_index("code")
    data.to_parquet(tmp_path / "2026Q3.parquet")
    old = pd.DataFrame([{"code": "002624", "announce_date": 20260428,
                         "近一年归母净利润（万元）": None, "总股本": 1939968384}]).set_index("code")
    old.to_parquet(tmp_path / "2026Q1.parquet")
    reports = read_stock_disclosures(tmp_path, "002624", 2025, 2026)
    assert [row["period"] for row in reports] == ["2026Q1", "2026Q3"]
    assert reports[0]["ttm_profit_yi"] is None
    assert reports[1]["ttm_profit_yi"] == 4.52475
    assert reports[1]["total_shares"] == 1939968384
    assert reports[1]["announce_date"] == "20261030"


def test_disclosure_reader_reuses_cumulative_ttm_formula_when_precomputed_value_is_zero(tmp_path: Path):
    rows = {
        "2025A": {"announce_date": 20260420, "近一年归母净利润（万元）": 1659977.0,
                  "归属于母公司所有者的净利润": 16_599_770_112.0, "总股本": 7_742_858_240},
        "2025Q3": {"announce_date": 20251030, "近一年归母净利润（万元）": 1500000.0,
                   "归属于母公司所有者的净利润": 11_518_290_944.0, "总股本": 7_742_858_240},
        "2026Q3": {"announce_date": 20261030, "近一年归母净利润（万元）": 0.0,
                   "归属于母公司所有者的净利润": 13_056_983_040.0, "总股本": 7_742_858_240},
    }
    for period, row in rows.items():
        pd.DataFrame([{"code": "002475", **row}]).set_index("code").to_parquet(tmp_path / f"{period}.parquet")

    reports = read_stock_disclosures(tmp_path, "002475", 2025, 2026)
    latest = next(row for row in reports if row["period"] == "2026Q3")

    assert latest["ttm_profit_yi"] == 181.38462208
    assert latest["ttm_profit_source"] == "cumulative_reports"
    assert compute_daily_pe_percentile(
        [(date(2026, 11, 19), 47.65)], reports,
    )["current_pe"] == 20.340599


def test_disclosure_reader_preserves_real_negative_precomputed_ttm(tmp_path: Path):
    pd.DataFrame([{
        "code": "000001", "announce_date": 20261030,
        "近一年归母净利润（万元）": -10000.0,
        "归属于母公司所有者的净利润": 5_000_000_000.0,
        "总股本": 1_000_000_000,
    }]).set_index("code").to_parquet(tmp_path / "2026Q3.parquet")

    report = read_stock_disclosures(tmp_path, "000001", 2026, 2026)[0]

    assert report["ttm_profit_yi"] == -1.0
    assert report["ttm_profit_source"] == "precomputed_tdx"


def test_disclosure_reader_does_not_treat_partial_quarter_profit_as_ttm(tmp_path: Path):
    pd.DataFrame([{
        "code": "000001", "announce_date": 20261030,
        "近一年归母净利润（万元）": 0.0,
        "归属于母公司所有者的净利润": 5_000_000_000.0,
        "总股本": 1_000_000_000,
    }]).set_index("code").to_parquet(tmp_path / "2026Q3.parquet")

    report = read_stock_disclosures(tmp_path, "000001", 2026, 2026)[0]

    assert report["ttm_profit_yi"] is None
    assert report["ttm_profit_source"] is None
