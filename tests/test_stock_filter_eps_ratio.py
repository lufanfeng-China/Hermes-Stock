"""股价收益比 = 5 年累计基本每股收益 ÷ 当前股价（%），不足五年按用户口径年化。"""
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app.stock_filter import filter_response
from app.stock_filter_market_snapshot import (
    EPS_ANNUALISATION,
    _eps_ratio_fields,
    build_market_metrics,
    load_annual_eps,
)

ROOT = Path(__file__).resolve().parents[1]


def bars(closes, symbol="600519", market="sh"):
    dates = pd.date_range("2026-01-01", periods=len(closes))
    return pd.DataFrame(dict(date=dates, close=closes, open=closes,
                             market=market, symbol=symbol, volume=100.0, free_float_shares=10000.0))


@pytest.mark.parametrize("years, factor", [(5, 1.0), (4, 1.25), (3, 5 / 3), (2, 2.5), (1, 5.0)])
def test_annualisation_factors_match_the_requested_rule(years, factor):
    assert EPS_ANNUALISATION[years] == pytest.approx(factor)

    fields = _eps_ratio_fields({"sum": 10.0, "years": years}, price=100.0)

    assert fields["eps_ratio_5y"] == pytest.approx(round(10.0 * factor / 100.0 * 100, 2))
    assert fields["eps_ratio_5y_years"] == years
    assert fields["eps_ratio_5y_factor"] == pytest.approx(round(factor, 4))


def test_negative_cumulative_eps_keeps_the_sign():
    fields = _eps_ratio_fields({"sum": -6.6953, "years": 5}, price=3.19)
    assert fields["eps_ratio_5y"] == pytest.approx(-209.88, abs=0.01)


def test_missing_eps_or_price_yields_no_ratio():
    for info, price in ((None, 10.0), ({"sum": 5.0, "years": 5}, None), ({"sum": 5.0, "years": 5}, 0.0)):
        fields = _eps_ratio_fields(info, price)
        assert fields["eps_ratio_5y"] is None
        assert fields["eps_ratio_5y_years"] is None


def test_snapshot_uses_annual_eps_map_and_current_close():
    payload = build_market_metrics(
        bars([90.0, 95.0, 100.0]),
        annual_eps={"600519": {"sum": 20.0, "years": 4}},
    )
    row = payload["metrics"]["sh:600519"]

    assert row["eps_ratio_5y_eps_sum"] == 20.0
    assert row["eps_ratio_5y_factor"] == 1.25
    assert row["eps_ratio_5y_price"] == 100.0
    assert row["eps_ratio_5y"] == 25.0          # 20 * 1.25 / 100
    assert row["eps_ratio_5y_years"] == 4


def test_real_financial_warehouse_exposes_both_five_and_four_year_symbols():
    eps = load_annual_eps()
    assert len(eps) > 5000
    assert eps["600519"]["years"] == 5
    assert any(info["years"] == 4 for info in eps.values()), "应有上市不足五年的成分，用于验证年化分支"


def stock(i, ratio):
    return dict(market="sz", symbol=f"{i:06d}", stock_name=f"S{i}", rps_total=i,
                annual_dimensions={}, quarterly_dimensions={}, eps_ratio_5y=ratio)


def test_filter_applies_to_the_whole_universe_before_pagination():
    rows = [stock(i, value) for i, value in enumerate([-5.0, 10.0, 35.0, 80.0, None])]
    with patch("app.stock_filter._universe", return_value=(rows, "2026-10-30")):
        result = filter_response({"eps_ratio_5y_min": ["30"], "page": ["1"]})

    assert result["ok"] is True
    assert result["total_matched"] == 2          # 35 和 80，None 与低值都被排除
    assert {row["eps_ratio_5y"] for row in result["rows"]} == {35.0, 80.0}


def test_filter_note_and_column_are_wired():
    html = (ROOT / "web" / "stock-filter.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

    assert 'name="eps_ratio_5y_min"' in html and 'name="eps_ratio_5y_max"' in html
    assert "股价收益比" in html
    assert "4 年 ×1.25" in html              # 年化口径必须写在页面上
    assert "epsRatioCell(row)" in js and "row.eps_ratio_5y" in js

    # 结果表不再有日/周/月趋势列与金叉列
    header = html.split("<th>日 / 周 / 月趋势</th>")[0] if "<th>日 / 周 / 月趋势</th>" in html else html
    assert "<th>日 / 周 / 月趋势</th>" not in html
    assert "<th>金叉</th>" not in html
    assert "trend_daily_label" not in js and "golden_cross_label" not in js
    # 结果表列数随红旗数量列一起调整为 10
    assert 'colspan="10"' in js and 'colspan="11"' not in js and 'colspan="12"' not in js
