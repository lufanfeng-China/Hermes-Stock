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


def test_preview_removes_identity_banner_and_moves_actions_to_health_header():
    script = (WEB / "stock-analysis-preview.js").read_text(encoding="utf-8")
    css = (WEB / "stock-analysis-preview.css").read_text(encoding="utf-8")
    assert '<section class="preview-identity"' not in script
    assert '<div class="preview-block-actions">' in script
    assert 'id="preview-rbreaker-trigger"' in script
    assert 'id="preview-original-link"' in script
    assert script.index('id="preview-rbreaker-trigger"') < script.index('id="preview-financial-period"')
    assert '.preview-block-actions' in css


def test_rbreaker_button_is_never_disabled_and_explains_missing_stock():
    script = (WEB / "stock-analysis-preview.js").read_text(encoding="utf-8")
    trigger_tag = script.split('id="preview-rbreaker-trigger"', 1)[1].split('>', 1)[0]
    assert 'disabled' not in trigger_tag
    show = script.split('async function showRBreaker(trigger)', 1)[1].split('function loadMarketPosition', 1)[0]
    assert '请先选择股票' in show
    assert 'rbreakerDialog.showModal()' in show
    assert "if (!selectedStock) return;" not in show


def test_overview_four_valuation_cards_open_history_dialogs_without_tab_navigation():
    script = (WEB / "stock-analysis-preview.js").read_text(encoding="utf-8")
    assert "cards[0].setAttribute('data-stock-kline-history', '')" in script
    assert "cards[1].dataset.valuationTrend = 'price-rank'" in script
    assert "cards[2].setAttribute('data-industry-valuation-history', '')" in script
    assert "peCard.setAttribute('data-stock-pe-history', '')" in script
    assert "[cards[0], cards[1], cards[2], peCard, peFiveYearCard].forEach((card) => card.removeAttribute('data-preview-target'))" in script
    assert "byId('preview-market-summary').contains(trigger)" in script


def test_rbreaker_dialog_uses_qfq_evidence_and_contains_six_price_ladder():
    page = (WEB / "stock-analysis.html").read_text(encoding="utf-8")
    script = (WEB / "stock-analysis-preview.js").read_text(encoding="utf-8")
    assert '<script src="/rbreaker-levels.js?' in page
    assert page.index('rbreaker-levels.js') < page.index('stock-analysis-preview.js')
    assert 'id="preview-rbreaker-dialog"' in script
    assert 'id="preview-rbreaker-chart"' in script
    assert '/api/stock-qfq-trend' in script
    assert 'as_of_date=${encodeURIComponent(day)}&limit=2' in script
    assert 'RBreakerLevels.calculateRBreakerLevels' in script
    assert 'RBreakerLevels.orderedRBreakerLevels' in script
    assert 'if (rbreakerDialog.open) return;' in script
    for label in ('突破买入价', '观察卖出价', '反转卖出价', '反转买入价', '观察买入价', '突破卖出价'):
        assert label in script
    assert '不构成买卖建议' in script


def test_rbreaker_dialog_fits_common_desktop_viewport_without_clipping_sixth_level():
    css = (WEB / "stock-analysis-preview.css").read_text(encoding="utf-8")
    assert '.preview-rbreaker-dialog { width:min(900px,calc(100vw - 24px)); max-height:calc(100vh - 28px); box-sizing:border-box;' in css
    assert 'height:min(43vh,360px)' in css
    assert 'overflow:auto' in css


def test_overview_replaces_excess_response_with_strict_five_year_pe_percentile():
    script = (WEB / "stock-analysis-preview.js").read_text(encoding="utf-8")
    assert "display('PE 5年分位'" in script
    assert "dailyPe?.basis === 'five_years'" in script
    assert "peFiveYearCard.dataset.valuationTrend = 'pe-rank'" in script
    assert "peFiveYearCard, rpsCard" in script
    assert "display('超额日内响应差'" not in script
    assert "peCard.append(peFootnote)" not in script


def test_market_overview_uses_ten_cards_with_swapped_pe_order_and_single_width_structure():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    css = (WEB / 'stock-analysis-preview.css').read_text(encoding='utf-8')
    assert "multiMetricCard('RPS'" in script
    assert "rpsRows.push({ label: 'MRS'" in script
    assert "rpsCard.classList.add('preview-rps-mrs-card')" in script
    assert "multiMetricCard('ER'" in script
    assert "multiMetricCard('结构'" in script
    assert "const antiFall = cardData(relativeGrid, '抗跌强度（20日）')" in script
    assert "display('抗跌强度'" in script
    assert "const marketCards = [cards[0], cards[1], peCard, cards[2], peFiveYearCard, rpsCard, erCard, temperatureCard, antiFallCard, structureCard]" in script
    assert "setCards(byId('preview-market-summary'), marketCards)" in script
    assert "const mrsCard = display('MRS'" not in script
    assert "display(`RPS${days}`" not in script
    assert "display(`ER${days}`" not in script
    assert "display('当前结构'" not in script
    assert "display('结构倾向'" not in script
    assert 'preview-rps-mrs-card' in css
    assert 'preview-multi-metric-card' in css
    assert 'preview-metric-row' in css
    assert '.preview-structure-metric-card { grid-column:span 2;' not in css
    assert '.preview-structure-metric-card .preview-metric-list { grid-template-columns:repeat(2,minmax(0,1fr))' not in css


def test_overview_antifall_card_reuses_existing_audited_detail_dialog():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    html = (WEB / 'stock-analysis.html').read_text(encoding='utf-8')
    assert "antiFallCard.dataset.previewAntifallDetail = 'true'" in script
    assert "event.target.closest('[data-preview-antifall-detail]')" in script
    assert "byId('market-relative-strength-grid')?.querySelector('[data-market-antifall-detail]')?.click()" in script
    assert "const antiFallDialog = byId('market-antifall-detail-dialog')" in script
    assert "antiFallTrigger.focus({ preventScroll: true })" in script
    assert "hub.querySelector('[data-preview-antifall-detail]')?.focus({ preventScroll: true })" in script
    assert 'id="market-antifall-detail-dialog"' in html
    assert 'id="market-antifall-detail-table"' in html
    for heading in ('日期', '大盘涨跌幅', '股票涨跌幅', '超额收益'):
        assert f'>{heading}<' in html


def test_overview_industry_temperature_card_opens_history_trend_dialog():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    html = (WEB / 'stock-analysis.html').read_text(encoding='utf-8')
    css = (WEB / 'stock-analysis-preview.css').read_text(encoding='utf-8')
    assert "temperatureCard.dataset.industryTemperatureTrend = 'true'" in script
    assert "temperatureCard.dataset.industryCode = industryRow.concept_code" in script
    assert "temperatureCard.removeAttribute('data-preview-target')" in script
    assert "temperatureCard.setAttribute('aria-controls', 'industry-temperature-trend-dialog')" in script
    assert "event.target.closest('[data-industry-temperature-trend]')" in script
    assert "scope=industry" in script
    assert "metric=temperature" in script
    assert 'function renderIndustryTemperatureTrend' in script
    assert "['冰点', '偏冷', '中性', '升温', '热门', '极热']" in script
    assert '当前成分回算历史（非历史时点成分）' in script
    assert "industryTemperatureTrendController?.abort()" in script
    assert "industryTemperatureTrendTrigger.focus({ preventScroll: true })" in script
    assert 'id="industry-temperature-trend-dialog"' in html
    assert 'id="industry-temperature-trend-chart"' in html
    assert 'id="industry-temperature-trend-meta"' in html
    assert 'id="industry-temperature-trend-tooltip"' in html
    assert '.preview-industry-temperature-trend-chart' in css


def test_structure_card_shows_audited_duration_previous_state_and_left_aligned_values():
    preview = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    page = (WEB / 'stock-analysis.js').read_text(encoding='utf-8')
    css = (WEB / 'stock-analysis-preview.css').read_text(encoding='utf-8')
    assert "target.dataset.swingDurationDays" in page
    assert "target.dataset.swingDurationExact" in page
    assert "target.dataset.swingPreviousState" in page
    assert "duration?.start_confirmed ? 'true' : 'false'" in page
    assert "const durationDays = swingRoot?.dataset.swingDurationDays" in preview
    assert "durationExact ? `${durationDays}日` : `≥${durationDays}日`" in preview
    assert "label: '前结构'" in preview
    assert "const previousStructure = swingRoot?.dataset.swingPreviousState || '未知'" in preview
    assert '.preview-structure-metric-card .preview-metric-value { font-size:14px; text-align:left;' in css
    assert '.preview-structure-metric-card .preview-metric-row { grid-template-columns:64px minmax(0,1fr); min-height:27px;' in css


def test_overview_structure_card_opens_shared_swing_evidence_dialog_without_tab_navigation():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    assert "structureCard.dataset.swingChartTrigger = 'true'" in script
    assert "structureCard.removeAttribute('data-preview-target')" in script
    assert "structureCard.setAttribute('aria-haspopup', 'dialog')" in script
    assert "structureCard.setAttribute('aria-controls', 'swing-chart-dialog')" in script


def test_marked_overview_cards_apply_direction_aware_tones():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    css = (WEB / 'stock-analysis-preview.css').read_text(encoding='utf-8')
    html = (WEB / 'stock-analysis.html').read_text(encoding='utf-8')
    assert html.index('overview-card-tones.js') < html.index('stock-analysis-preview.js')
    assert "setCardTone(cards[1], OverviewCardTones.valuationPercentile(positionValue === '—' ? null : position?.price_percentile))" in script
    assert "setCardTone(cards[2], OverviewCardTones.valuationPercentile(peComparable ? marketValuation?.primary_percentile : null))" in script
    assert "OverviewCardTones.valuationPercentile(fiveYearPePct)" in script
    assert "const rpsTone = OverviewCardTones.mrs(Number.parseFloat(mrs?.value))" in script
    assert "const erTone = OverviewCardTones.er20(Number.parseFloat(erRows[1]?.value))" in script
    assert "OverviewCardTones.temperature(industryRow.temperature)" in script
    assert "OverviewCardTones.antiFall(antiFall?.antiFallWinRate, antiFall?.antiFallStatus)" in script
    assert "rpsCard.classList.add('preview-tone-driven-card')" in script
    assert "erCard.classList.add('preview-tone-driven-card')" in script
    assert '.preview-tone-driven-card.strong .preview-metric-value' in css
    assert '.preview-tone-driven-card.risk .preview-metric-value' in css
    assert '.preview-tone-driven-card.watch .preview-metric-value' in css


def test_overview_removes_marked_visible_explanations_but_keeps_audit_tooltips():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    assert "cards[1].append(scope)" not in script
    assert "cards[2].append(source)" not in script
    assert "peCard.append(source)" not in script
    assert "peFiveYearCard.append(source)" not in script
    assert "temperatureCard.append(source)" not in script
    assert '窗口内前复权收盘价的经验分位' in script
    assert 'PE行业分位不可用' in script
    assert 'const peEvidence =' in script
    assert '前复权10日绝对涨幅与广度温度档位' in script


def test_market_header_replaces_evidence_strip_with_industry_and_concept_actions():
    html = (WEB / 'stock-analysis.html').read_text(encoding='utf-8')
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')

    assert 'id="preview-market-period"' not in script
    assert '前复权/相对大盘：' not in script
    assert 'id="preview-industry-trigger"' in script
    assert 'data-industry-valuation-peers' in script
    assert 'id="preview-concept-temperature-trigger"' in script
    assert 'id="stock-concept-temperature-dialog"' in script
    assert '/api/stock-concept-temperature?' in script
    assert '热点概念' in script and '二级行业' in script
    assert 'temperature_previous' in script and 'temperature_change' in script
    assert 'temperature_trend_label' in script
    assert 'stock-concept-temperature-table' in script
    assert 'stock-analysis-preview.js?v=20261123-financial-recovery-v1' in html


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


def test_financial_summary_discloses_recovery_or_deteriorating_score_basis():
    script = (WEB / 'stock-analysis-preview.js').read_text(encoding='utf-8')
    assert "annualScoreBasisLabel" in script
    assert "recovery_track: '恢复型'" in script
    assert "deteriorating_track: '恶化型'" in script
    assert "summaryCard('年报评分', annual.value, annualScoreBasisLabel" in script


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
