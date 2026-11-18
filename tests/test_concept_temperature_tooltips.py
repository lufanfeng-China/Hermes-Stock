"""0–5 温度档位的悬浮说明必须与判定代码里的阈值一致。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")
CODE = (ROOT / "app" / "concept_temperature.py").read_text(encoding="utf-8")

EXPECTED = {
    "0": ("≤ −5/−7/−12/−18/−30%",),
    "1": ("−2/−3/−5/−7/−10%",),
    "2": ("≤0%", "分化上涨", "50%"),
    "3": (">0%", "50%"),
    "4": ("1.5/2/3/4.5/8%", "60%", "超额 >0"),
    "5": ("3/4.5/6/9/15%", "75%", "30%", "超额 >0"),
}


def tip_for(level: str) -> str:
    match = re.search(r'data-temp="%s" data-tip="([^"]+)"' % re.escape(level), HTML)
    assert match, f"缺少档位 {level} 的悬浮说明"
    return match.group(1)


def test_every_level_has_a_tooltip():
    for level in EXPECTED:
        assert tip_for(level).strip()


def test_tooltips_state_the_thresholds_from_the_classifier():
    for level, tokens in EXPECTED.items():
        text = tip_for(level)
        for token in tokens:
            assert token in text, f"{level} 的说明缺少阈值 {token}：{text}"


def test_classifier_still_uses_the_documented_thresholds():
    from app.concept_temperature import TEMPERATURE_CUTS
    assert TEMPERATURE_CUTS == {
        3: (-5, -2, 1.5, 3), 5: (-7, -3, 2, 4.5),
        10: (-12, -5, 3, 6), 20: (-18, -7, 4.5, 9),
        60: (-30, -10, 8, 15),
    }
    for literal in ("breadth < 50", "breadth >= 60", "breadth >= 75",
                    "strong >= 30", "excess > 0"):
        assert literal in CODE, f"判定代码里找不到 {literal}，说明文字可能已过期"


def test_tooltip_binding_survives_the_element_order():
    # 气泡元素在脚本之后解析，绑定必须等 DOMContentLoaded
    assert "temp-tip" in HTML and 'role="tooltip"' in HTML
    assert "DOMContentLoaded" in JS and "document.readyState === 'loading'" in JS
    assert "data-tip" in JS            # 只绑带说明的按钮
    assert "aria-hidden" in JS         # 无障碍状态同步


def test_all_button_has_a_tooltip_too():
    match = re.search(r'data-temp="" data-tip="([^"]+)"', HTML)
    assert match and "全部" in match.group(1)


def test_rule_note_is_not_pulled_into_the_clipping_container():
    """.block-body 用了 overflow-x:auto（等于 overflow-y 也是 auto），
    说明文字若用负的上边距就会被裁掉上半截——这里锁死不许出现负 margin。"""
    rule = re.search(r"\.rule-note\{([^}]*)\}", HTML)
    assert rule, ".rule-note 样式缺失"
    body = rule.group(1)
    assert "margin" in body
    margin = re.search(r"margin:\s*([^;]+)", body).group(1)
    numbers = re.findall(r"-?\d*\.?\d+", margin)
    assert numbers and float(numbers[0]) >= 0, f"rule-note 上边距不能为负：{body}"
    line_height = re.search(r"line-height:\s*([\d.]+)", body)
    assert line_height and float(line_height.group(1)) >= 1.4, f"说明文字行高过低：{body}"
    assert "overflow:auto" not in body.replace(" ", "")


HEADERS = {
    "热度分": ("30%", "25%", "20%", "15%", "10%", "分位", "不参与绝对档位"),
    "相对排名": ("热度分", "不参与绝对档位"),
    "X日中位涨幅": ("中位数", "前复权"),
    "上涨广度": ("> 0", "比例"),
    "相对超额": ("全市场", "中位数", "pp"),
}


def header_tip(label: str) -> str:
    match = re.search(r'<th data-tip="([^"]+)">%s</th>' % re.escape(label), HTML)
    assert match, f"表头 {label} 没有悬浮说明"
    return match.group(1)


def test_key_headers_explain_their_formula():
    for label, tokens in HEADERS.items():
        text = header_tip(label)
        for token in tokens:
            assert token in text, f"{label} 的说明缺少 {token}：{text}"


def test_header_copy_matches_the_scoring_code():
    # 权重必须与 build_temperature_rows 里的加权一致
    assert "scores[0] * 30" in CODE and "scores[4] * 10" in CODE
    assert "30%" in header_tip("热度分") and "10%" in header_tip("热度分")
    # 相对超额 = 概念中位 − 全市场中位
    assert "market_median" in CODE and "全市场" in header_tip("相对超额")
    # 广度 = 涨跌幅 > 0 的占比
    assert "value > 0" in CODE and "> 0" in header_tip("上涨广度")


def test_tooltip_binding_covers_any_element_with_a_tip():
    assert "querySelectorAll('[data-tip]')" in JS
    assert "th[data-tip]" in HTML and "cursor:help" in HTML
