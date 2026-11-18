"""Single-stock swing display must disclose an older publication as historical evidence."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stock_analysis_labels_published_swing_date_and_old_chart_boundary():
    html = (ROOT / 'web' / 'stock-analysis.html').read_text(encoding='utf-8')
    js = (ROOT / 'web' / 'stock-analysis.js').read_text(encoding='utf-8')
    assert '最近已发布结构' in js
    assert 'data.snapshot_lagged' in js
    assert 'data.source_as_of_date' in js
    assert 'data.chart_unavailable_reason' in js
    assert '不要求全市场快照同步发布' in html


def test_stock_analysis_distinguishes_live_single_stock_from_published_snapshot():
    js = (ROOT / 'web/stock-analysis.js').read_text(encoding='utf-8')
    assert "data.source_type === 'live_qfq'" in js
    assert '/api/swing-structure?market=${encodeURIComponent(stock.market)}&symbol=${encodeURIComponent(stock.symbol)}' in js
    assert '本地最新有效前复权' in js
    assert '当前可得结构' in js


def test_stock_analysis_explains_consecutive_state_duration_and_missing_evidence():
    js = (ROOT / 'web/stock-analysis.js').read_text(encoding='utf-8')
    assert 'data.state_duration' in js
    assert 'data.duration_unavailable_reason' in js
    assert '连续有效交易日' in js
    assert '自可用历史起至少持续' in js
    assert '上一状态' in js
