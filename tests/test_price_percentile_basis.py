"""五年分位：满五年用五年窗口，不足五年用上市以来全部历史。"""
import pandas as pd
import pytest

from app.stock_filter_market_snapshot import PRICE_PERCENTILE_MIN_SAMPLES, _price_percentile_5y


def _frame(start: str, days: int, base: float = 10.0) -> pd.DataFrame:
    index = pd.bdate_range(start, periods=days)
    closes = [base + 0.01 * i for i in range(days)]
    return pd.DataFrame({"close": closes}, index=index)


def test_full_five_year_history_uses_the_five_year_window():
    frame = _frame("2019-01-01", 1800)
    result = _price_percentile_5y(frame)
    assert result["price_percentile_5y_basis"] == "five_year"
    assert result["price_percentile_5y"] is not None
    # 单调上涨的历史里，最新价就是最高价 → 分位 100
    assert result["price_percentile_5y"] == 100.0
    cutoff = (frame.index[-1] - pd.DateOffset(years=5)).date().isoformat()
    assert result["price_percentile_5y_window_start"] == cutoff


def test_short_history_falls_back_to_everything_available():
    frame = _frame("2024-01-02", 400)          # 约 1.6 年，上市不足五年
    result = _price_percentile_5y(frame)
    assert result["price_percentile_5y_basis"] == "since_listing"
    assert result["price_percentile_5y"] is not None
    assert result["price_percentile_5y_sample_count"] == len(frame)
    assert result["price_percentile_5y_window_start"] == frame.index[0].date().isoformat()


def test_short_history_percentile_counts_every_available_bar():
    index = pd.bdate_range("2025-01-01", periods=200)
    closes = list(range(200, 0, -1))            # 单调下跌 → 最新价是最低价
    result = _price_percentile_5y(pd.DataFrame({"close": closes}, index=index))
    assert result["price_percentile_5y_basis"] == "since_listing"
    # 最新价 1 是最低价，只有它自己 ≤ 它自己 → 1/200
    assert result["price_percentile_5y"] == pytest.approx(1 / 200 * 100, abs=0.1)


def test_history_shorter_than_the_minimum_still_reports_nothing():
    frame = _frame("2026-09-01", PRICE_PERCENTILE_MIN_SAMPLES - 1)
    result = _price_percentile_5y(frame)
    assert result["price_percentile_5y"] is None
    assert result["price_percentile_5y_basis"] == "since_listing"


def test_empty_series_stays_unavailable():
    result = _price_percentile_5y(pd.DataFrame({"close": []}, index=pd.DatetimeIndex([])))
    assert result["price_percentile_5y"] is None
    assert result["price_percentile_5y_sample_count"] == 0


def test_page_discloses_the_short_history_basis():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    html = (root / "web" / "stock-filter.html").read_text(encoding="utf-8")
    js = (root / "web" / "stock-filter.js").read_text(encoding="utf-8")
    assert "不足五年按上市以来全部历史计算" in html
    assert "（上市以来）" in js
    assert "price_percentile_5y_basis" in js
