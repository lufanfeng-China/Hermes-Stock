"""0–5 温度档位的悬浮说明必须与判定代码里的阈值一致。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "concept-temperature.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "concept-temperature.js").read_text(encoding="utf-8")
CODE = (ROOT / "app" / "concept_temperature.py").read_text(encoding="utf-8")

EXPECTED = {
    "0": ("≤20%", "≤0", "35%"),
    "1": ("≤40%",),
    "2": ("≤60%",),
    "3": ("≤80%", "≤0", "55%", "≤0"),
    "4": ("80%", "55%", "0"),
    "5": ("≥95%", "75%", "30%", "20%", "15 只"),
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
    # 代码里的分位与广度阈值必须仍是说明文字所写的那些
    for literal in ("<= .20", "<= .40", "<= .60", "<= .80", ">= .95",
                    "breadth < 35", "breadth < 55", "breadth >= 75",
                    "strong >= 30", "active >= 20", "max(15, min_members)"):
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
