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


def test_previous_level_is_the_most_recent_different_one():
    # 连续 3 天都是 3，前温要取再往前的 4（不是昨天那一档的 3）
    current = rows(3, 3, 3)
    attach_temperature_streaks(current, history([3, 3, 3], [3, 3, 3], [3, 3, 3], [4, 2, 4], [1, 5, 2]))
    assert (current[0]["temperature_previous"], current[0]["temperature_previous_gap_days"]) == (4, 3)
    assert (current[0]["temperature_change"], current[0]["temperature_trend_label"]) == (-1, "退坡")
    assert (current[1]["temperature_previous"], current[1]["temperature_previous_gap_days"]) == (2, 3)
    assert (current[1]["temperature_change"], current[1]["temperature_trend_label"]) == (1, "升温")
    assert (current[2]["temperature_previous"], current[2]["temperature_previous_gap_days"]) == (4, 3)


def test_equal_levels_are_never_reported_as_the_previous_value():
    current = rows(4)
    attach_temperature_streaks(current, history([4], [4], [4], [4]))
    assert current[0]["temperature_previous"] is None
    assert current[0]["temperature_trend"] == "unknown"
    assert current[0]["temperature_trend_label"] == "无前值"


def test_missing_days_are_skipped_and_the_gap_is_reported():
    current = rows(3)
    attach_temperature_streaks(current, history([3], [None], [3], [None], [2]))
    row = current[0]
    assert (row["temperature_previous"], row["temperature_previous_gap_days"]) == (2, 4)
    assert row["temperature_trend"] == "warming"


def test_row_without_current_data_says_data_missing():
    current = rows(None)
    attach_temperature_streaks(current, history([None], [3]))
    assert current[0]["temperature_trend_label"] == "数据不足"
    assert current[0]["temperature_previous"] is None


def test_streak_still_counted_independently():
    current = rows(3)
    attach_temperature_streaks(current, history([3], [3], [4]))
    assert current[0]["temperature_streak_days"] == 2
    assert current[0]["temperature_previous"] == 4


def test_labels_cover_every_state():
    assert set(TREND_LABELS) == {"warming", "cooling", "unknown"}


def test_page_renders_the_previous_temperature_column():
    html = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")

    assert ">温度变化</th>" in html
    header = re.search(r'<th data-tip="([^"]+)">温度变化</th>', html)
    assert header and "升温" in header.group(1) and "退坡" in header.group(1)
    assert "function tempTrend(row)" in js and "tempTrend(row)" in js
    assert "row.temperature_previous" in js and "temperature_trend_label" in js
    assert 'colspan="9"' in js and 'colspan="8"' not in js
