"""温度变化：与上一交易日的等级比较（升温 / 退坡 / 持平 / 无前值）。"""
import re
from pathlib import Path

import pytest

from app.concept_temperature import TREND_LABELS, attach_temperature_streaks

ROOT = Path(__file__).resolve().parents[1]


def rows(*levels):
    return [{"concept_code": f"C{i}", "temperature": level} for i, level in enumerate(levels)]


def history(*days):
    """days 从今天往前走，每天一个 {code: level}。"""
    return [dict(zip([f"C{i}" for i in range(len(day))], day)) for day in days]


def test_cooling_warming_and_flat_are_labelled():
    current = rows(3, 3, 3, None)
    attach_temperature_streaks(current, history([3, 3, 3, None], [4, 2, 3, 1]))
    assert (current[0]["temperature_previous"], current[0]["temperature_change"], current[0]["temperature_trend"]) == (4, -1, "cooling")
    assert (current[1]["temperature_previous"], current[1]["temperature_change"], current[1]["temperature_trend"]) == (2, 1, "warming")
    assert (current[2]["temperature_previous"], current[2]["temperature_change"], current[2]["temperature_trend"]) == (3, 0, "flat")
    assert current[3]["temperature_trend"] == "unknown"
    assert [row["temperature_trend_label"] for row in current] == ["退坡", "升温", "持平", "数据不足"]


def test_missing_previous_day_looks_back_but_reports_the_gap():
    current = rows(3)
    attach_temperature_streaks(current, history([3], [None], [None], [2]))
    row = current[0]
    assert row["temperature_previous"] == 2
    assert row["temperature_previous_gap_days"] == 3
    assert row["temperature_trend"] == "warming"


def test_lookback_is_bounded():
    current = rows(3)
    attach_temperature_streaks(current, history([3], [None], [None], [None], [None], [None], [1]))
    assert current[0]["temperature_previous"] is None
    assert current[0]["temperature_trend"] == "unknown"
    assert current[0]["temperature_trend_label"] == "无前值"
    assert current[0]["temperature_previous_gap_days"] is None


def test_streak_still_counted_independently_of_the_trend():
    current = rows(3)
    attach_temperature_streaks(current, history([3], [3], [4]))
    assert current[0]["temperature_streak_days"] == 2
    assert current[0]["temperature_trend"] == "flat"


def test_labels_cover_every_state():
    assert set(TREND_LABELS) == {"warming", "cooling", "flat", "unknown"}


def test_page_renders_the_previous_temperature_column():
    html = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")

    assert ">温度变化</th>" in html
    header = re.search(r'<th data-tip="([^"]+)">温度变化</th>', html)
    assert header and "升温" in header.group(1) and "退坡" in header.group(1)
    assert "function tempTrend(row)" in js and "tempTrend(row)" in js
    assert "row.temperature_previous" in js and "temperature_trend_label" in js
    assert 'colspan="9"' in js and 'colspan="8"' not in js
