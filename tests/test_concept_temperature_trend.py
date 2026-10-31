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


def _fixture():
    return {"as_of_date": "2026-10-30", "price_basis": "tdx_export_qfq", "min_members": 10,
            "windows": {"10": {"concepts": [
                {"concept_code": "A", "temperature": 3, "temperature_trend": "cooling", "temperature_previous": 4},
                {"concept_code": "B", "temperature": 3, "temperature_trend": "warming", "temperature_previous": 2},
                {"concept_code": "C", "temperature": 5, "temperature_trend": "warming", "temperature_previous": 4},
                {"concept_code": "D", "temperature": 2, "temperature_trend": "unknown", "temperature_previous": None},
            ]}}}


def test_api_filters_by_trend_only():
    from unittest.mock import patch

    from app.api.concept_temperature import handle_concept_temperature

    with patch("app.api.concept_temperature._load", return_value=_fixture()):
        cooling = handle_concept_temperature("window=10&trend=cooling")
        warming = handle_concept_temperature("window=10&trend=warming")
        everything = handle_concept_temperature("window=10")

    assert [row["concept_code"] for row in cooling["concepts"]] == ["A"]
    assert [row["concept_code"] for row in warming["concepts"]] == ["B", "C"]
    assert len(everything["concepts"]) == 4
    assert cooling["trend"] == "cooling"


def test_api_combines_trend_with_temperature_level():
    from unittest.mock import patch

    from app.api.concept_temperature import handle_concept_temperature

    with patch("app.api.concept_temperature._load", return_value=_fixture()):
        combo = handle_concept_temperature("window=10&temperature=3&trend=warming")
    assert [row["concept_code"] for row in combo["concepts"]] == ["B"]


def test_api_rejects_unknown_trend():
    from unittest.mock import patch

    from app.api.concept_temperature import handle_concept_temperature

    with patch("app.api.concept_temperature._load", return_value=_fixture()):
        bad = handle_concept_temperature("window=10&trend=up")
    assert bad["ok"] is False and bad["status"] == 400


def test_page_has_trend_buttons_and_sends_the_param():
    html = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")
    assert 'data-trend="warming"' in html and 'data-trend="cooling"' in html
    assert "仅升温" in html and "仅退坡" in html
    assert "trend-filter" in js and "trendFilter" in js
    assert "'&trend=' + encodeURIComponent(trendFilter)" in js


def _streak_fixture():
    return {"as_of_date": "2026-10-30", "price_basis": "tdx_export_qfq", "min_members": 10,
            "windows": {"10": {"concepts": [
                {"concept_code": "A", "temperature": 3, "temperature_streak_days": 1},
                {"concept_code": "B", "temperature": 3, "temperature_streak_days": 7},
                {"concept_code": "C", "temperature": 4, "temperature_streak_days": 20, "temperature_streak_capped": True},
                {"concept_code": "D", "temperature": None, "temperature_streak_days": None},
            ]}}}


def _api(query):
    from unittest.mock import patch

    from app.api.concept_temperature import handle_concept_temperature

    with patch("app.api.concept_temperature._load", return_value=_streak_fixture()):
        return handle_concept_temperature(query)


def test_api_filters_by_streak_days_range():
    assert [r["concept_code"] for r in _api("window=10&min_days=7")["concepts"]] == ["B", "C"]
    assert [r["concept_code"] for r in _api("window=10&max_days=1")["concepts"]] == ["A"]
    assert [r["concept_code"] for r in _api("window=10&min_days=2&max_days=10")["concepts"]] == ["B"]


def test_streak_filter_excludes_unknown_streaks():
    # D 当天数据不足、没有持续天数，启用天数条件时不计入
    assert "D" not in [r["concept_code"] for r in _api("window=10&min_days=1")["concepts"]]
    assert len(_api("window=10")["concepts"]) == 4


@pytest.mark.parametrize("query", ["window=10&min_days=0", "window=10&max_days=0",
                                   "window=10&min_days=5&max_days=2", "window=10&min_days=abc"])
def test_invalid_streak_bounds_are_rejected(query):
    result = _api(query)
    assert result["ok"] is False and result["status"] == 400


def test_page_wires_the_streak_inputs():
    html = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")
    assert 'id="min-days"' in html and 'id="max-days"' in html
    assert "持续天数" in html
    assert "min_days=" in js and "max_days=" in js
    assert "[minDaysEl, maxDaysEl]" in js
