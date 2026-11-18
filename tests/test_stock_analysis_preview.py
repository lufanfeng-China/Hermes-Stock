"""Preview page must preserve the existing analysis contract while changing presentation only."""
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if "id" in props:
            self.ids.append(props["id"])
        if tag == "script" and props.get("src"):
            self.scripts.append(props["src"])
        if tag == "link" and props.get("rel") == "stylesheet":
            self.styles.append(props.get("href"))


def test_default_reuses_all_legacy_analysis_targets_and_loads_adapter_first():
    original = Elements()
    original.feed((WEB / "stock-analysis-legacy.html").read_text(encoding="utf-8"))
    preview = Elements()
    preview.feed((WEB / "stock-analysis.html").read_text(encoding="utf-8"))
    assert len(preview.ids) == len(set(preview.ids))
    assert set(original.ids).issubset(preview.ids)
    assert any(x.startswith("/stock-analysis-preview.css?") for x in preview.styles)
    adapter = next(i for i, x in enumerate(preview.scripts) if x.startswith("/stock-analysis-preview.js?"))
    renderer = next(i for i, x in enumerate(preview.scripts) if x.startswith("stock-analysis.js?"))
    assert adapter < renderer
    assert "stock-analysis-preview" not in " ".join(original.scripts)
    assert any(x.startswith('/stock-analysis-legacy.js?') for x in original.scripts)


def test_default_and_legacy_routes_preserve_deep_links():
    page = (WEB / "stock-analysis.html").read_text(encoding="utf-8")
    legacy = (WEB / "stock-analysis-legacy.html").read_text(encoding="utf-8")
    adapter = (WEB / "stock-analysis-preview.js").read_text(encoding="utf-8")
    assert 'id="stock-analysis-search-form"' in page
    assert 'id="stock-analysis-search-form"' in legacy
    assert 'href="/stock-analysis-legacy.html"' in adapter
    assert 'stock-analysis-legacy.html?${new URLSearchParams' in adapter
    assert 'location.href = `/stock-analysis.html?${new URLSearchParams' in adapter
    assert '股票分析 · 旧版' in legacy
    assert '股票分析 · 预览版' not in page
    assert (WEB / 'stock-analysis-legacy.js').is_file()


def test_preview_adapter_has_four_views_and_evidence_controls():
    script = (WEB / "stock-analysis-preview.js").read_text(encoding="utf-8")
    assert all(x in script for x in ('overview', 'financial', 'valuation', 'technical'))
    assert 'health-comparison-body' in script
    assert 'wyckoff-observation' in script
    assert 'analysis-metric-card' in script
    assert 'stock-analysis:select' in script


def test_valuation_summary_has_auditable_price_and_turnover_percentiles():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    assert "summaryCard('股价5年分位'" in script
    assert "summaryCard('换手率分位'" in script
    assert 'positionAligned && position?.scope === \'five_year\'' in script
    assert "get('/api/stock-filter-turnover-trend'" in script
    assert "turnoverTrend?.as_of_date === positionDate" in script
    assert "last?.date === positionDate" in script
    assert "last?.sample_count >= 120" in script
    assert "Number.isFinite(last?.percentile)" in script


def test_valuation_four_cards_open_their_matching_history_without_tab_navigation():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    assert "data-stock-pe-history" in script
    assert "data-valuation-trend" in script
    assert "get('/api/stock-daily-pe-percentile', '&history=1')" in script
    assert '/api/stock-qfq-trend?' in script
    assert 'turnoverTrend.rows' in script
    assert 'preview-valuation-trend-dialog' in script
    assert 'position.window_start' in script
    assert 'payload.as_of_date !== position.as_of_date' in script
    # SVGElement.hidden assignment need not reflect an HTML attribute; the CSS selector needs one.
    assert "trendChart.setAttribute('hidden', '')" in script
    assert "trendChart.removeAttribute('hidden')" in script
    assert '.preview-valuation-trend-dialog svg[hidden] { display:none; }' in (WEB / 'stock-analysis-preview.css').read_text(encoding='utf-8')
