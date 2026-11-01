"""预设条件的悬浮说明必须写清真实门槛，并与判定代码保持一致。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "stock-filter.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
CODE = (ROOT / "app" / "stock_filter.py").read_text(encoding="utf-8")
SNAPSHOT = (ROOT / "app" / "stock_filter_market_snapshot.py").read_text(encoding="utf-8")


def tip(preset: str) -> str:
    match = re.search(r'data-preset="%s"[^>]*data-tip="([^"]+)"' % preset, HTML)
    assert match, f"{preset} 缺少悬浮说明"
    return match.group(1)


def test_financial_reversal_tip_states_every_gate():
    text = tip("financial_reversal")
    for token in ("≤55", "≥70", "25 分", "85%", "营业收入同比", "扣非净利润同比", "自由现金流", "红旗"):
        assert token in text, f"财报反转说明缺少 {token}"
    # 这些门槛必须仍然是代码里的门槛
    assert "annual <= 55 and quarterly >= 70 and quarterly - annual >= 25" in CODE
    assert '< 85 or' in CODE
    assert "quarterly_ttm_fcf_margin" in CODE


def test_blowup_break_tip_states_volume_and_return_bands():
    text = tip("blowup_break")
    for token in ("5 个交易日", "3 倍", "2 倍", "+5%", "+20%", "强多头", "修复中"):
        assert token in text, f"爆量突破说明缺少 {token}"
    assert "3.0 if closes[idx] > opens[idx] else 2.0" in SNAPSHOT
    assert "5.0 < ret_5d < 20.0" in SNAPSHOT
    assert 'allowed = {"strong_bullish", "bullish", "recovering"}' in CODE


def test_tooltip_binding_covers_preset_buttons():
    assert 'id="filter-tip"' in HTML
    assert "bindPresetTooltips" in JS
    assert "querySelectorAll('[data-tip]')" in JS
    assert "DOMContentLoaded" in JS          # 气泡元素在脚本之后
    assert ".filter-tip{" in HTML and "data-open" in HTML
