"""趋势模版（Trend Template）前 7 条：指标、预设过滤、页面契约。"""
from pathlib import Path

import pandas as pd
import pytest

from app.stock_filter import matches_trend_template
from app.stock_filter_market_snapshot import (
    TREND_TEMPLATE_MIN_BARS,
    _trend_template_metrics,
)

ROOT = Path(__file__).resolve().parents[1]


def _frame(closes):
    return pd.DataFrame({"close": closes})


def _rising(n=300, start=10.0, step=0.05):
    return [start + index * step for index in range(n)]


def test_a_clean_uptrend_passes_all_seven_legs():
    metrics = _trend_template_metrics(_frame(_rising()))
    assert metrics["trend_template_ok"] is True
    assert metrics["trend_template_status"] == "evaluated"
    assert sum(metrics["trend_template_legs"].values()) == 7
    assert metrics["trend_template_price_basis"] == "close_only"


def test_short_history_cannot_be_evaluated():
    metrics = _trend_template_metrics(_frame(_rising(n=TREND_TEMPLATE_MIN_BARS - 1)))
    assert metrics["trend_template_ok"] is False
    assert metrics["trend_template_status"] == "insufficient_history"
    assert metrics["trend_template_bars"] == TREND_TEMPLATE_MIN_BARS - 1
    assert metrics["trend_template_legs"] == {}


@pytest.mark.parametrize("leg", ["above_ma150", "ma150_above_ma200", "ma200_rising_1m", "above_ma50"])
def test_individual_legs_are_required(leg):
    """任何一条腿不成立，整体就不成立（逐条验证）。"""
    base = _rising(n=190)
    if leg == "above_ma150":
        closes = base + [_rising(110)[-1]] * 110
        closes[-1] = closes[-151] * 0.5              # 收盘价跌到 150 日线之下
    elif leg == "ma150_above_ma200":
        closes = base + [base[-1] * (1 - 0.01 * index) for index in range(110)]   # 后段持续下跌
    elif leg == "ma200_rising_1m":
        top = _rising(n=270)[-1]
        closes = _rising(n=270) + [top * (1 - 0.02 * index) for index in range(1, 31)]  # 末段回落，200 日线转为下行
    else:
        closes = base + [base[-1]] * 110                                        # 末段横盘，50 日线追平并压过收盘价
    metrics = _trend_template_metrics(_frame(closes))
    assert metrics["trend_template_legs"][leg] is False, metrics["trend_template_legs"]
    assert metrics["trend_template_ok"] is False


def test_52_week_legs_use_closing_extremes():
    closes = _rising()
    metrics = _trend_template_metrics(_frame(closes))
    window = closes[-250:]
    assert metrics["trend_template_high_52w"] == round(max(window), 4)
    assert metrics["trend_template_low_52w"] == round(min(window), 4)
    assert metrics["trend_template_off_low_pct"] >= 30
    assert metrics["trend_template_from_high_pct"] >= -25


def test_far_below_the_52_week_high_fails():
    closes = _rising() + [0.0]
    closes[-1] = max(closes[-251:]) * 0.5       # 距高点 50%
    metrics = _trend_template_metrics(_frame(closes))
    assert metrics["trend_template_legs"]["within_25pct_of_52w_high"] is False
    assert metrics["trend_template_ok"] is False


def test_matcher_reads_the_snapshot_flag():
    assert matches_trend_template({"trend_template_ok": True}) is True
    assert matches_trend_template({"trend_template_ok": False}) is False
    assert matches_trend_template({}) is False


def test_filter_accepts_the_preset_and_rejects_unknown_values():
    from app.stock_filter import filter_response

    accepted = filter_response({"preset": ["trend_template"], "page": ["1"]})
    assert accepted.get("ok") is not False
    rejected = filter_response({"preset": ["trend_template_v2"], "page": ["1"]})
    assert rejected.get("ok") is False or "unsupported preset" in str(rejected)


def test_page_exposes_the_preset_with_its_seven_conditions():
    html = (ROOT / "web" / "stock-filter.html").read_text(encoding="utf-8")
    start = html.index('data-preset="trend_template"')
    tip = html[html.index('data-tip="', start) + len('data-tip="'):]
    tip = tip[:tip.index('"')]

    assert "<strong>趋势模版</strong>" in html
    for token in ("150 日线", "200 日线", "50 日线", "52 周", "30%", "25%", "20 个交易日"):
        assert token in tip, f"说明缺少 {token}"
    # 第 8 条本次不纳入，必须写明
    assert "相对强度" in tip and "不纳入" in tip
