"""当季健康：每只股票取自己最近一期已披露季报。"""
from pathlib import Path

import pytest

from app.stock_filter_snapshot import build_strict_financial_record
from scripts.build_strict_financial_health_snapshot import ANNUAL_PERIODS, PERIODS, QUARTERLY_PERIODS

ROOT = Path(__file__).resolve().parent.parent


def _annual(year: int, revenue: float = 100.0, profit: float = 10.0) -> dict:
    return {"period": f"{year}A", "year": str(year), "report_date": f"{year}1231",
            "metrics": {"revenue": revenue, "ex_net_profit": profit, "ocf": profit, "capex": profit * 0.3,
                        "gross_margin": 30.0, "net_margin": 10.0, "roe_ex": 8.0, "debt_ratio": 40.0,
                        "accounts_receivable": 12.0, "inventory": 9.0, "goodwill": 1.0,
                        "equity": 80.0, "total_assets": 140.0}}


def _quarter(period: str, revenue: float, profit: float) -> dict:
    year, suffix = period[:4], period[4:]
    report_date = {"Q1": f"{year}0331", "Q2": f"{year}0630", "Q3": f"{year}0930"}[suffix]
    return {"period": period, "year": year, "report_date": report_date,
            "metrics": {"revenue": revenue, "ex_net_profit": profit, "ocf": profit, "capex": profit * 0.3,
                        "gross_margin": 30.0, "net_margin": 10.0, "debt_ratio": 40.0,
                        "accounts_receivable": 12.0, "inventory": 9.0}}


def _annuals() -> list[dict]:
    return [_annual(2021), _annual(2022), _annual(2023), _annual(2024), _annual(2025, 120, 12)]


def test_stock_with_a_third_quarter_report_anchors_on_that_quarter():
    reports = _annuals() + [
        _quarter("2025Q2", 50.0, 5.0), _quarter("2025Q3", 78.0, 7.8),
        _quarter("2026Q2", 55.0, 5.5), _quarter("2026Q3", 88.0, 9.1),
    ]
    record = build_strict_financial_record(reports, industry_level_1="电子",
                                          annual_anchor="2025A", quarterly_anchor="2026Q3")
    assert record["quarterly"]["anchor_period"] == "2026Q3"
    assert record["quarterly"]["period"] == "2026Q3"


def test_stock_without_a_third_quarter_falls_back_to_the_newest_it_filed():
    reports = _annuals() + [
        _quarter("2025Q2", 50.0, 5.0), _quarter("2026Q1", 30.0, 3.0), _quarter("2026Q2", 55.0, 5.5),
    ]
    record = build_strict_financial_record(reports, industry_level_1="电子",
                                          annual_anchor="2025A", quarterly_anchor="2026Q3")
    assert record["quarterly"]["anchor_period"] == "2026Q2"
    assert record["quarterly"]["anchor_period_global"] == "2026Q3"


def test_a_stock_that_skipped_a_quarter_uses_the_one_before_it():
    reports = _annuals() + [_quarter("2025Q2", 50.0, 5.0), _quarter("2026Q1", 30.0, 3.0)]
    record = build_strict_financial_record(reports, industry_level_1="电子",
                                          annual_anchor="2025A", quarterly_anchor="2026Q3")
    assert record["quarterly"]["anchor_period"] == "2026Q1"


def test_snapshot_build_loads_the_frames_needed_for_q3_year_on_year():
    assert "2026Q3" in QUARTERLY_PERIODS and "2025Q3" in QUARTERLY_PERIODS
    assert PERIODS.index("2025Q3") < PERIODS.index("2026Q3")
    assert PERIODS == ANNUAL_PERIODS + QUARTERLY_PERIODS


def test_membership_only_requires_the_annual_frames():
    source = (ROOT / "scripts/build_strict_financial_health_snapshot.py").read_text(encoding="utf-8")
    assert "set.intersection(*(set(frames[period].index) for period in ANNUAL_PERIODS))" in source
    # 季报缺失不再把股票踢出池子
    assert "for period in PERIODS if symbol in frames[period].index" in source


def test_screener_row_shows_the_stock_period_not_the_global_anchor():
    source = (ROOT / "app/stock_filter.py").read_text(encoding="utf-8")
    assert '"quarterly_period": q.get("period") or q.get("anchor_period")' in source
    assert 'strict_financial_health_snapshot_2025A__latest_quarter.json' in source


def test_page_explains_the_per_stock_quarter_rule():
    html = (ROOT / "web/stock-filter.html").read_text(encoding="utf-8")
    assert "每只股票取自己最近一期已披露季报" in html
