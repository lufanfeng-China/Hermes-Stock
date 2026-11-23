from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_historical_disabled_controls_have_explicit_visual_language():
    html = (ROOT / 'web/stock-filter.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-filter.js').read_text(encoding='utf-8')

    for token in (
        '.history-disabled-field',
        '.history-disabled-group',
        '.history-partial-control',
        'content:attr(data-history-badge)',
        'border-style:dashed',
        'cursor:not-allowed',
        '.history-disabled-group.is-collapsed',
        'transform:none',
    ):
        assert token in html

    assert "classList.toggle('history-disabled-group', historical)" in js
    assert "classList.toggle('history-partial-control', historical)" in js
    assert "dataset.historyBadge = '历史不可用'" in js
    assert "dataset.historyBadge = '部分选项不可用'" in js
    assert "document.querySelector('label[for=\"sort\"]')" in js
