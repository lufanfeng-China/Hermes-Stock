import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class StockAnalysisPageTests(unittest.TestCase):
    def test_financial_reversal_badge_is_conditionally_rendered_in_composite_panel(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")

        self.assertIn('id="financial-health-reversal-badge"', html)
        self.assertIn('financial-health-reversal-badge', html)
        self.assertIn('function renderFinancialReversalBadge', js)
        self.assertIn('payload.financial_reversal', js)
        self.assertIn('财报反转', html)

    def test_report_release_t_plus_one_return_is_rendered_from_api_evidence(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")

        self.assertIn('id="financial-health-release-return"', html)
        self.assertIn('财报发布日 T+1 开盘至今', html)
        self.assertIn('function renderReportReleasePricePerformance', js)
        self.assertIn('payload.report_release_price_performance', js)

    def test_report_release_return_opens_raw_price_trend_with_all_four_markers(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="report-release-price-trend-dialog"', html)
        self.assertIn('id="report-release-price-trend-svg"', html)
        self.assertIn('data-report-release-price-trend', html)
        self.assertIn('function showReportReleasePriceTrend', js)
        self.assertIn('report_release_price_trend', js)
        for marker in ('T+1 开盘价', '最高价', '最低价', '当前价'):
            self.assertIn(marker, js)

    def test_requested_seven_metric_rows_exist_in_order(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        expected = [
            ("营业收入", "revenue-chart"), ("营收增长率", "revenue-growth-chart"),
            ("归母净利润", "net-profit-chart"), ("扣非归母净利润", "ex-net-profit-chart"),
            ("毛利率", "gross-margin-chart"), ("净利率", "net-margin-chart"),
            ("扣非ROE", "roe-ex-chart"), ("资产负债率", "debt-ratio-chart"),
            ("经营现金流", "ocf-chart"), ("自由现金流", "free-cf-chart"),
            ("资本开支（CapEx）", "capex-chart"), ("商誉", "goodwill-chart"),
            ("应收账款", "accounts-receivable-chart"), ("库存", "inventory-chart"),
        ]
        self.assertEqual(html.count('<article class="analysis-metric-card"'), 14)
        positions = []
        for label, chart_id in expected:
            positions.append(html.index(f'>{label}<'))
            self.assertIn(f'id="{chart_id}"', html)
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('归母净利润增速', html)
        self.assertNotIn('净利润增速', html)
        self.assertIn('.analysis-bar.zero-axis.negative', html)
        self.assertIn('.analysis-bar.zero-value', html)
        self.assertIn('#70d6a8', html)

    def test_valuation_performance_linkage_co_displays_relative_valuation_health_quarterly_change_and_flags_without_advice(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="valuation-performance-linkage"', html)
        self.assertIn('估值—业绩联动', html)
        self.assertIn('function renderValuationPerformanceLinkage(valuation, health, monitor)', js)
        self.assertIn('/api/relative-valuation?', js)
        self.assertIn('行业内估值位置', js)
        self.assertIn('财务健康度', js)
        self.assertIn('季度变化', js)
        self.assertIn('红旗', js)
        self.assertIn('仅陈列同一时点可验证事实与共现', html)
        self.assertNotIn('买入建议', html)
        self.assertNotIn('卖出建议', html)

    def test_clickable_secondary_industry_opens_quarterly_valuation_history_from_2020(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="industry-valuation-history-dialog"', html)
        self.assertIn('id="industry-valuation-history-chart"', html)
        self.assertIn('id="industry-valuation-history-table"', html)
        self.assertIn('function showIndustryValuationHistory(valuation)', js)
        self.assertIn('data-industry-valuation-history', js)
        self.assertIn('industry_temperature_history', js)
        self.assertIn("row.trading_day >= '2020-01-01'", js)
        self.assertIn('加权 PE-TTM', js)
        self.assertIn('dialog.showModal()', js)

    def test_clickable_industry_valuation_position_opens_full_secondary_industry_peer_dialog(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="industry-valuation-peer-dialog"', html)
        self.assertIn('id="industry-valuation-peer-table"', html)
        self.assertIn('估值分位', html)
        self.assertIn('PE(动)', html)
        self.assertIn('function showIndustryValuationPeers()', js)
        self.assertIn('/api/industry-valuation-percentile?', js)
        self.assertIn('data-industry-valuation-peers', js)
        self.assertIn('valuation_percentile', js)
        self.assertIn('valuation_band', js)
        self.assertIn('点击列头可排序', js)
        self.assertIn('[data-industry-valuation-peers] { cursor:pointer;', html)
        self.assertIn('[data-industry-valuation-peers]:hover', html)
        self.assertIn('[data-industry-valuation-peers]:focus-visible', html)
        self.assertIn('[data-industry-health-peers]:hover', html)
        self.assertIn('[data-industry-health-peers]:focus-visible', html)

    def test_health_peers_keep_latest_available_reference_separate_but_sortable(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('data-health-peer-view="latest_available_quarterly"', html)
        self.assertIn('各股最近可用财报', html)
        self.assertIn("view === 'latest_available_quarterly'", js)
        self.assertIn("latest_available_quarterly", js)
        self.assertIn("value !== null && value !== undefined", js)
        self.assertIn('仅供参考；点击列头可排序，不构成同业排名', js)
        self.assertNotIn("if (state.industryHealthPeerView === 'latest_available_quarterly') return", js)

    def test_basic_market_module_is_above_financial_health_comparison_and_uses_rps_windows(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertLess(html.index('id="basic-market-section"'), html.index('id="financial-health-kpi"'))
        self.assertIn('基础行情', html)
        for label in ('RPS20', 'RPS50', 'RPS120', 'RPS250'):
            self.assertIn(label, js)
        self.assertIn('renderBasicMarket', js)
        self.assertIn('/api/stock-profile?', js)
        self.assertIn('profile?.profile || {}', js)

    def test_basic_market_replaces_ps_ttm_with_five_year_price_percentile(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('/api/stock-price-percentile?symbol=', js)
        self.assertIn("label: '股价五年分位'", js)
        self.assertIn('pricePercentile?.price_percentile', js)
        self.assertNotIn("['PS-TTM', text(valuation?.ps_ttm)", js)

    def test_basic_market_replaces_latest_revenue_yoy_with_pe_history_percentile(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn("label: 'PE 5年分位'", js)
        self.assertIn('peHistory?.history?.at(-1)?.pe_pct', js)
        self.assertNotIn("['最新营收同比', text(valuation?.revenue_yoy, '%')", js)

    def test_basic_market_renders_eight_operating_quality_metrics_in_uniform_grid(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        for label in (
            '营收同比（TTM）', '3年营收 CAGR', '毛利率（TTM）', '净利率（TTM）',
            '扣非 ROE（TTM）', '现金利润比（TTM）', 'FCF率（TTM）', '资产负债率（最新）',
        ):
            self.assertIn(f"label: '{label}'", js)
        self.assertIn(
            "label: '总市值（亿）', value: marketValue(valuation?.total_market_cap)",
            js,
        )
        self.assertIn("label: '流通市值（亿）', value: marketValue(valuation?.free_float_market_cap)", js)
        self.assertIn('grid-template-columns:repeat(9,minmax(0,1fr))', html)
        self.assertIn('.basic-market-card { min-width:0; height:68px;', html)

    def test_basic_market_uses_distinct_quality_valuation_and_momentum_color_semantics(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")

        self.assertIn('function operatingMetricStatus', js)
        self.assertIn('function valuationMetricStatus', js)
        self.assertIn('function rpsMetricStatus', js)
        self.assertIn('industryFinancialPosition', js)
        self.assertIn('basic-market-status', js)
        self.assertIn('aria-label=', js)
        for status in ('strong', 'neutral', 'watch', 'risk', 'unavailable'):
            self.assertIn(f'.basic-market-card.{status}', html)
        self.assertIn('.basic-market-status', html)

    def test_current_price_basic_market_card_opens_real_kline_dialog(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="stock-kline-dialog"', html)
        self.assertIn('id="stock-kline-svg"', html)
        self.assertIn('data-stock-kline-history', js)
        self.assertIn('function showStockKlineHistory', js)
        self.assertIn('/api/stock-kline?', js)
        self.assertIn('/api/stock-rps-history?', js)
        self.assertIn("import('./kline-chart.js", js)

    def test_niche_leader_badge_opens_auditable_detail_dialog(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="niche-leader-dialog"', html)
        self.assertIn('data-niche-leader-detail', js)
        self.assertIn('function renderNicheLeaderBadge', js)
        self.assertIn('function showNicheLeaderDetail', js)
        self.assertIn('细分龙头映射数据集', html)
        self.assertIn('认定依据', js)
        self.assertIn('niche_leader_detail', js)
        self.assertIn('niche_leader', js)

    def test_pe_ttm_basic_market_card_opens_history_dialog_with_real_api(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="stock-pe-history-dialog"', html)
        self.assertIn('data-stock-pe-history', js)
        self.assertIn('/api/stock-pe-history?', js)
        self.assertIn('个股 PE-TTM', html)
        self.assertIn('行业中位数', html)
        self.assertIn('当前实时 PE', html)

    def test_industry_financial_position_renders_alignment_coverage_and_peer_percentiles(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="industry-financial-position"', html)
        self.assertIn('function renderIndustryFinancialPosition(position)', js)
        self.assertIn('行业中位数', js)
        self.assertIn('分位', js)
        self.assertIn('覆盖率', js)
        self.assertIn('payload.industry_financial_position', js)
        self.assertIn('function formatIndustryPositionMetric(value, unit)', js)
        self.assertIn('formatIndustryPositionMetric(m.industry_median, m.unit)', js)

    def test_metric_lineage_drawer_discloses_current_value_basis_formula_inputs_and_non_ttm_reason(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="metric-lineage-dialog"', html)
        self.assertIn("data-metric-lineage", js)
        self.assertIn('const METRIC_LINEAGE =', js)
        self.assertIn('function showMetricLineage(metricKey)', js)
        self.assertIn('当前显示值', js)
        self.assertIn('计算公式', js)
        self.assertIn('使用报告期', js)
        self.assertIn('为何不适用 TTM', js)
        self.assertIn("dialog.showModal()", js)
        self.assertIn("data-metric-lineage", js)

    def test_latest_report_change_summary_surfaces_ranked_quarterly_findings_with_basis_and_chart_links(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="latest-report-change-summary"', html)
        self.assertIn('id="latest-report-change-period"', html)
        self.assertIn('最新财报变化', html)
        self.assertIn('function renderLatestReportChanges(monitor)', js)
        self.assertIn('LATEST_REPORT_CHANGE_CONFIG', js)
        self.assertIn("latest-report-change-item", js)
        self.assertIn("latest-report-change-basis", js)
        self.assertIn(".latest-report-change-alert { grid-column:1 / -1;", html)
        self.assertIn("href=\"#${config.chartId}\"", js)
        self.assertIn("renderLatestReportChanges(payload.quarterly_monitor)", js)
        self.assertIn("'TTM'", js)
        self.assertIn("'非TTM'", js)
        self.assertIn("暂无可用最新财报变化摘要", js)

    def test_comparison_section_precedes_raw_metric_charts(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="financial-health-kpi"', html)
        self.assertLess(html.index('id="financial-health-kpi"'), html.index('aria-label="五年经营指标"'))
        self.assertIn('年度与季度财报监测对比', html)
        self.assertIn('renderHealthComparisonTable(payload.health, payload.quarterly_monitor)', js)
        self.assertNotIn('id="health-dimensions"', html)
        self.assertNotIn('id="health-red-flag-panel"', html)

    def test_chart_configuration_has_all_requested_data_fields_and_units(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        for chart_id, field in (
            ('revenue-chart', 'revenue'), ('net-profit-chart', 'net_profit'),
            ('ex-net-profit-chart', 'ex_net_profit'), ('gross-margin-chart', 'gross_margin'),
            ('net-margin-chart', 'net_margin'), ('roe-ex-chart', 'roe_ex'),
            ('debt-ratio-chart', 'debt_ratio'), ('ocf-chart', 'ocf'),
            ('free-cf-chart', 'free_cf'), ('capex-chart', 'capex'),
            ('goodwill-chart', 'goodwill'), ('accounts-receivable-chart', 'accounts_receivable'),
            ('inventory-chart', 'inventory'),
        ):
            self.assertIn(f"['{chart_id}', '{field}'", js)
        self.assertIn("const evidenceReports = payload.reports.filter((row) => String(row?.period || '').endsWith('A'));", js)
        self.assertIn("const healthEvidenceReports = annualPeriods.size ?", js)
        self.assertIn("renderYoYGrowthBars('revenue-growth-chart', ttmReports, 'revenue', annualPeriods, payload.reports)", js)
        self.assertIn('const annualReports = annualPeriods ?', js)
        self.assertIn('financialRequestId !== state.financialRequestId', js)
        self.assertIn("const needsZeroAxis = variant === 'growth' || numeric.some((value) => value < 0);", js)
        self.assertIn('analysis-bar zero-axis ${variant} ${direction}', js)
        self.assertIn("const zeroClass = value === 0 ? ' zero-value' : '';", js)
        self.assertIn("display === 'percent'", js)

    def test_partial_health_evidence_is_not_discarded_and_unavailable_rules_keep_evidence(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn("title: item.title || item.code, reason: item.reason || '比较数据不可用', evidence: item.evidence", js)
        self.assertNotIn("health.status === 'insufficient_data'", js)
        self.assertIn('renderHealthEvidencePanels(health);', js)

    def test_not_applicable_and_insufficient_outputs_keep_dimensions_and_conclusions_visible(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertNotIn("dimensions.innerHTML = ''; derived.textContent = '该行业须使用专用财务指标和阈值。'", js)
        self.assertIn("notApplicableLabel", js)
        self.assertIn("not_applicable: '不适用'", js)
        self.assertIn('renderUnavailableDimensions(health.dimensions)', js)
        self.assertIn('renderUnavailableConclusions(health.conclusions)', js)

    def test_null_score_explains_insufficient_coverage_and_rule_coverage(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn("health.score === null", js)
        self.assertIn('综合评分未生成：评分覆盖权重不足 85 / 100', js)
        self.assertIn('已评估红旗规则', js)

    def test_raw_trend_charts_never_fall_back_to_interim_reports(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn("payload.reports.filter((row) => String(row?.period || '').endsWith('A'))", js)
        self.assertNotIn("annualPeriods.size ? payload.reports.filter((row) => annualPeriods.has(String(row.period))) : payload.reports", js)

    def test_evidence_uses_chinese_field_labels_and_amount_units(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('const HEALTH_FIELD_LABELS', js)
        self.assertIn('function healthEvidenceValue', js)
        self.assertIn("value / 1e8", js)
        self.assertIn('资产负债率趋势', js)
        self.assertIn('商誉五年变化', js)

    def test_financial_cache_has_capacity_bound_and_lru_refresh(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('MAX_FINANCIAL_CACHE_ENTRIES = 24', js)
        self.assertIn('function putFinancialCache(cacheKey, payload)', js)
        self.assertIn('state.financialCache.delete(cacheKey)', js)
        self.assertIn('state.financialCache.keys().next().value', js)

    def test_health_ui_has_comparison_loading_and_failure_states(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('renderHealthComparisonTable(null, null)', js)
        self.assertNotIn("renderQuarterlyMonitor(null)", js)
        self.assertNotIn("renderFinancialHealth(null, null, 'loading')", js)

    def test_comparison_score_and_coverage_are_rendered(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('总分（100）', html)
        self.assertIn('覆盖度（100）', html)
        self.assertIn('health.score_coverage_status', js)

    def test_composite_health_score_discloses_its_auditable_components_and_risk_overlay(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('financial-health-composite', html)
        self.assertIn('financial-health-composite-score', html)
        self.assertIn('financial-health-composite-detail', html)
        self.assertIn('financial-health-composite-risk', html)
        self.assertIn('function renderCompositeFinancialHealth(composite)', js)
        self.assertIn('payload.composite_financial_health', js)
        self.assertIn('五年基础', js)
        self.assertIn('当季脉冲', js)
        self.assertIn('risk_overlay', js)

    def test_p2_red_flag_date_readability_and_request_contracts(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('health-flag-detail-dialog', html)
        self.assertIn('showHealthFlagDetail', js)
        self.assertIn('financialAbortController?.abort()', js)
        self.assertIn('AbortController()', js)
        self.assertIn('FINANCIAL_CACHE_TTL_MS', js)
        self.assertIn('健康度证据截至 ${evidenceAsOf}', js)

    def test_score_cards_disclose_pretrend_adjustment_and_final_points(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('const formation = scoreFormationCopy(item, scoreItem);', js)
        self.assertIn("趋势调整 ${adjustment > 0 ? '+' : ''}${adjustment.toFixed(1)} 分", js)

    def test_six_kpi_cards_show_scoring_process_without_raw_metric_dump(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        dimensions_block = js.split("dimensions.innerHTML = (health.dimensions || []).map((item) => {", 1)[1].split("    const d = health.derived", 1)[0]
        self.assertIn('scoreFormationCopy(item, scoreItem)', dimensions_block)
        self.assertNotIn('healthEvidenceSummary(scoreEvidence[item.code])', dimensions_block)
        self.assertNotIn('指标：${Object.entries(evidence.metrics)', dimensions_block)

    def test_growth_quality_card_uses_plain_language_score_explanations(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('function scoreFormationCopy(item, scoreItem)', js)
        self.assertIn('营收与扣非利润五年仍保持增长', js)
        self.assertIn('扣非利润增速略落后于营收', js)
        self.assertIn('营收增速较高点回落，扣非利润近年承压', js)
        self.assertIn('scoreFormationCopy(item, scoreItem)', js)

    def test_raw_charts_append_latest_quarter_without_polluting_annual_health_evidence(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('function appendLatestQuarter(annualReports, allReports)', js)
        self.assertIn('pointInTimeReports = appendLatestQuarter(healthEvidenceReports, payload.reports)', js)
        self.assertIn('const latestTTMReport = buildLatestTTMReport(payload.reports, payload.quarterly_monitor);', js)
        self.assertIn("renderYoYGrowthBars('revenue-growth-chart', ttmReports, 'revenue', annualPeriods, payload.reports)", js)
        self.assertIn("String(row?.period || '').endsWith('A')", js)

    def test_annual_and_quarterly_monitoring_summary_comparison_table(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        for label in ('总分', '覆盖度', '核心增长质量', '盈利能力', '现金含金量', '营运资本', '再投资效率', '财务风险', '已触发红旗', '待调查事项'):
            self.assertIn(label, html)
        self.assertIn('总分（100）', html)
        self.assertIn('核心增长质量（20）', html)
        self.assertIn('function annualAssessmentLabel(health)', js)
        self.assertIn('function annualAssessmentBasis(health)', js)
        self.assertIn('id="health-question-period"', html)
        self.assertIn('id="health-derived-period"', html)
        label_renderer = js[js.index('function annualAssessmentLabel'):js.index('function annualAssessmentBasis')]
        self.assertIn('return `${years}年样本`;', label_renderer)
        self.assertNotIn('置信度', label_renderer)
        self.assertIn('不可与完整五年评分横比', js)
        self.assertIn('const annualPeriod = annualAssessmentLabel(health);', js)
        self.assertIn("data-flag-source=\"annual\"", js)
        self.assertIn('id="health-comparison-body"', html)
        self.assertIn('function renderHealthComparisonTable(health, monitor)', js)
        self.assertIn('renderHealthComparisonTable(payload.health, payload.quarterly_monitor)', js)

    def test_total_score_opens_overall_financial_conclusion_and_keeps_six_kpi_actions(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="health-overall-detail-dialog"', html)
        self.assertIn('function showHealthOverallDetail(source)', js)
        self.assertIn('data-overall-source', js)
        self.assertIn('总体概要', js)
        self.assertIn('好的部分', js)
        self.assertIn('需要关注的部分', js)
        self.assertIn('function buildAnnualOverallAnalysis(health)', js)
        self.assertIn('function buildQuarterlyOverallAnalysis(monitor)', js)
        self.assertIn('function annualConclusionDetail(item, derived)', js)
        self.assertIn('function quarterlyDimensionDetail(item, monitor)', js)
        self.assertIn('收入和扣非利润长期增长较快', js)
        self.assertIn('收入、扣非利润同比明显下滑', js)
        self.assertIn('现金流和杠杆有所改善', js)
        self.assertIn('应收账款与库存增长快于营收', js)
        self.assertIn('function scoreDetailButton(source, item)', js)
        self.assertIn('data-score-source', js)

    def test_comparison_kpi_scores_open_a_detail_dialog(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="health-score-detail-dialog"', html)
        self.assertIn('function scoreDetailButton(source, item)', js)
        self.assertIn('function showHealthScoreDetail(source, code)', js)
        self.assertIn("data-score-source", js)
        self.assertIn("health-comparison-body", js)

    def test_comparison_only_ui_and_clickable_flag_details(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertNotIn('id="quarterly-health-monitor"', html)
        self.assertNotIn('id="health-dimensions"', html)
        self.assertNotIn('id="health-red-flag-panel"', html)
        self.assertIn('id="health-question-grid"', html)
        self.assertIn('function renderHealthQuestions(health)', js)
        self.assertIn('showHealthFlagDetail', js)
        self.assertIn('comparison-flag-button', js)

    def test_health_questions_use_user_facing_six_prompts(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        prompts = (
            '公司过去 5 年有没有持续增长？',
            '利润增长是否快于收入增长？',
            '毛利率、净利率和 ROE 是否在改善？',
            '利润是否真正转化成了现金？',
            '应收和库存是否出现异常增长？',
            '公司增长是否依赖越来越高的资本投入和财务杠杆？',
        )
        for prompt in prompts:
            self.assertIn(prompt, js)
        self.assertIn('function healthQuestionPrompt(code, health)', js)
        self.assertIn('healthQuestionPrompt(item.code, health) || item.title', js)
        self.assertIn('function healthQuestionStatus(status)', js)
        self.assertIn('health-question-status ${escapeHtml(status.klass)}', js)
        self.assertIn('.health-question-card.improving', html)
        self.assertIn('.health-question-card.watch', html)
        self.assertIn('.health-question-card.stable', html)

    def test_five_year_derived_and_basic_metrics_are_retained(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="health-derived"', html)
        self.assertIn('id="health-series"', html)
        series_renderer = js[js.index('function renderHealthSeries'):js.index('function scoreFormationCopy')]
        for removed_metric in ('资产负债率', '商誉', '商誉 / 资产', '商誉 / 权益', '毛利率', '净利率'):
            self.assertNotIn(f"['{removed_metric}'", series_renderer)
        self.assertIn('年度派生指标', html)
        self.assertIn('id="health-derived-period"', html)
        self.assertIn('renderHealthMetrics(payload.health, payload.quarterly_monitor, payload.latest_report)', js)
        self.assertIn('营业收入', html)
        self.assertIn('自由现金流', html)

    def test_five_year_derived_series_render_as_signed_bar_charts(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        series_renderer = js[js.index('function renderHealthSeries'):js.index('function scoreFormationCopy')]
        self.assertIn('const HEALTH_SERIES_CHARTS = [', series_renderer)
        for label, key in (
            ('现金利润比', 'annual_cash_profit_ratio'), ('FCF Margin', 'fcf_margin'),
            ('应收增速差', 'receivable_growth_gap'), ('存货增速差', 'inventory_growth_gap'),
            ('CapEx 强度', 'capex_intensity'), ('扣非 ROE', 'roe_ex'),
        ):
            self.assertIn(f"['{label}', '{key}'", series_renderer)
        self.assertIn("renderBars(chartId, rows, values", series_renderer)
        self.assertIn('label: String(year)', series_renderer)
        self.assertIn('class="health-series-chart-grid"', series_renderer)
        self.assertIn('.health-series-chart-grid', css)
        self.assertIn('.health-series-chart-card', css)

    def test_derived_metric_charts_append_explicitly_labeled_latest_quarter(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        series_renderer = js[js.index('function renderHealthSeries'):js.index('function scoreFormationCopy')]
        self.assertIn('function latestQuarterSeriesPoint(quarterlyMonitor, latestReport)', js)
        self.assertIn('const latestQuarter = latestQuarterSeriesPoint(quarterlyMonitor, latestReport);', series_renderer)
        self.assertIn('const chartRows = latestQuarter ? [...seriesRows, latestQuarter] : seriesRows;', series_renderer)
        self.assertIn('renderHealthSeries(health, quarterlyMonitor, latestReport);', js)
        for key in ('annual_cash_profit_ratio', 'fcf_margin', 'receivable_growth_gap', 'inventory_growth_gap', 'capex_intensity', 'roe_ex'):
            self.assertIn(f'{key}:', js)
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        self.assertIn('id="health-derived-period"', html)
        self.assertIn('现金/FCF/CapEx/扣非 ROE 为 TTM', js)

    def test_interim_bars_use_ttm_for_flow_metrics_and_disclose_point_in_time_metrics(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        self.assertIn('function buildLatestTTMReport(reports, quarterlyMonitor)', js)
        self.assertIn("['revenue-chart', 'revenue', 'revenue', 'amount', 'ttm']", js)
        self.assertIn("['roe-ex-chart', 'roe_ex', 'ratio', 'percent', 'ttm']", js)
        self.assertIn("['accounts-receivable-chart', 'accounts_receivable', 'asset', 'amount', 'point']", js)
        self.assertIn("['inventory-chart', 'inventory', 'asset', 'amount', 'point']", js)
        self.assertIn("label: interimPeriodLabel(period, 'TTM')", js)
        self.assertIn("const HEALTH_TTM_SERIES_KEYS = new Set", js)
        self.assertIn("HEALTH_TTM_SERIES_KEYS.has(key) ? 'TTM' : '非TTM'", js)
        self.assertIn('增速差为非 TTM 期末同比差', js)

    def test_interim_chart_labels_use_short_ascii_ttm_suffix(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('function interimPeriodLabel(period, basis)', js)
        self.assertIn('return `${String(period).slice(2)}(${basis})`;', js)
        self.assertIn("label: interimPeriodLabel(period, 'TTM')", js)
        self.assertIn("label: interimPeriodLabel(latestQuarter.period, '非TTM')", js)
        self.assertIn("interimPeriodLabel(row.period, HEALTH_TTM_SERIES_KEYS.has(key) ? 'TTM' : '非TTM')", js)

    def test_annual_score_detail_uses_reader_friendly_metric_labels(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn("revenue_cagr: '营业收入复合增长率'", js)
        self.assertIn("ex_net_profit_cagr: '扣非归母净利润复合增长率'", js)
        self.assertIn("profit_premium: '利润增长溢价'", js)
        self.assertIn("gross_margin_change: '毛利率五年变化'", js)

    def test_quarterly_monitor_is_compared_only_in_the_table(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertNotIn('id="quarterly-health-monitor"', html)
        self.assertIn('payload.quarterly_monitor', js)
        self.assertIn('function compactQuarterPeriod(period)', js)
        self.assertIn('return `${normalized.slice(2)}-TTM`;', js)
        self.assertIn("const quarterPeriod = compactQuarterPeriod(monitor?.latest_period);", js)
        self.assertIn("cells('comparison-quarter', quarterPeriod, 'quarterly'", js)

    def test_metric_tooltips_use_only_native_title_without_dark_custom_flyout(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('title="${escapeHTML(content)}"', js)
        self.assertNotIn('function showHealthMetricTooltip(target)', js)
        self.assertNotIn("id = 'health-metric-tooltip-flyout'", js)
        self.assertNotIn('.health-metric-tooltip-flyout', css)

    def test_health_metric_values_use_user_requested_a_share_red_good_green_bad_coloring(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('function healthMetricTone(key, value)', js)
        self.assertIn("'metric-positive'", js)
        self.assertIn("'metric-negative'", js)
        self.assertIn('healthMetricValue(toneKey || tooltipKey, value, suffix)', js)
        self.assertIn("renderBars(chartId, rows, values", js)
        self.assertIn('.health-metric-value.metric-positive', css)
        self.assertIn('.health-metric-value.metric-negative', css)

    def test_five_year_series_goodwill_uses_yi(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('function healthSeriesValue(key, value, suffix)', js)
        self.assertIn("key === 'goodwill'", js)
        self.assertIn('numeric / 1e8', js)

    def test_kpi_and_five_year_series_metrics_expose_definition_tooltips(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('const HEALTH_METRIC_TOOLTIPS =', js)
        self.assertIn('function healthMetricLabel(key, label)', js)
        self.assertIn('healthMetricLabel(key, label)', js)
        self.assertIn('healthMetricLabel(tooltipKey, label)', js)
        for key in ('revenue_cagr', 'ex_net_profit_cagr', 'profit_growth_premium', 'gross_margin', 'net_margin', 'roe_ex', 'annual_cash_profit_ratio', 'fcf_margin', 'receivable_growth_gap', 'inventory_growth_gap', 'capex_intensity', 'debt_ratio', 'goodwill_equity_ratio'):
            self.assertIn(f"{key}: {{", js)
        self.assertIn('.health-metric-tooltip', css)
        self.assertIn('.health-metric-tooltip-trigger', css)

    def test_six_core_conclusions_use_concise_kpi_style_summaries(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('function conclusionSummary(item)', js)
        for code in ('growth', 'profit_premium', 'profitability', 'cash_conversion', 'working_capital', 'capital_leverage'):
            self.assertIn(f"case '{code}':", js)
        conclusion_block = js.split('const conclusionLabel =', 1)[1].split("  }\n\n  const METRIC_CHARTS", 1)[0]
        self.assertIn('conclusionSummary(item)', conclusion_block)
        self.assertNotIn('healthEvidenceSummary(item.evidence)', conclusion_block)

    def test_score_formation_renders_trend_adjustment_on_a_new_line(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn("formation.split('\\n').map(escapeHTML).join('<br>')", js)
        self.assertIn("\\n趋势调整", js)

    def test_all_six_kpi_cards_use_plain_language_score_explanations(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        for code in ('profitability', 'cash_quality', 'working_capital', 'reinvestment', 'financial_risk'):
            self.assertIn(f"case '{code}':", js)
        for phrase in ('利润率与扣非 ROE 的综合表现', '经营现金回收与自由现金流的表现', '应收与存货相对营收的变化', '资本投入、营收增长与自由现金流的联动', '负债、商誉与自由现金流的综合风险'):
            self.assertIn(phrase, js)
        self.assertNotIn('评分形成：调整前 ${base} 分；趋势调整', js)

    def test_investigation_panel_renders_triggered_rule_results_with_evidence(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('const investigationResults = health?.investigation_results || [];', js)
        self.assertIn("item.status === 'triggered'", js)
        self.assertIn('healthEvidenceList(triggeredInvestigations', js)
        self.assertNotIn("healthEvidenceList(health?.investigation_items || [], '暂无待调查事项。')", js)

    def test_investigation_panel_does_not_describe_unassessed_rules_as_no_items(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('const investigationCoverage = health?.investigation_coverage || {};', js)
        self.assertIn('const investigationUnavailable = investigationCoverage.unavailable || [];', js)
        self.assertIn('调查规则未评估', js)
        self.assertIn('investigationEmptyMessage', js)

    def test_investigation_coverage_is_disclosed_compactly(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('已评估调查规则：${investigationEvaluated} / ${investigationTotal}', js)
        self.assertIn('调查规则未评估：${investigationUnavailable.length} 项', js)

    def test_financial_report_materializes_requested_data_and_same_period_cashflow(self):
        source = (ROOT / "app" / "financial" / "reports.py").read_text(encoding="utf-8")
        for field in (
            'gross_margin', 'net_margin', 'roe_ex', 'debt_ratio', 'ocf', 'free_cf',
            'capex', 'goodwill', 'accounts_receivable', 'inventory', 'equity', 'total_assets',
        ):
            self.assertIn(f'"{field}"', source)
        self.assertIn('ocf - capex if ocf is not None and capex is not None else None', source)
        self.assertIn('销售毛利率(%)(非金融类指标)', source)
        self.assertIn('销售净利率(%)', source)

    def test_industry_peer_metric_dialog_is_generic_config_driven_and_uses_snapshot_metadata(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")

        self.assertIn('const PEER_METRIC_CONFIG =', js)
        for metric in ('revenue', 'revenue_growth', 'net_profit', 'ex_net_profit', 'gross_margin', 'net_margin', 'roe_ex', 'debt_ratio', 'ocf', 'free_cf', 'capex', 'goodwill', 'accounts_receivable', 'inventory', 'cash_profit_ratio', 'fcf_margin', 'capex_intensity', 'accounts_receivable_growth_gap', 'inventory_growth_gap'):
            self.assertIn(f"{metric}: {{", js)
        self.assertIn('id="industry-metric-peer-dialog"', html)
        self.assertIn('id="industry-metric-peer-table"', html)
        self.assertIn('async function showIndustryMetricPeers(metricCode, trigger = null)', js)
        self.assertIn('/api/industry-metric-peers?', js)
        self.assertIn('payload.industry_level_2', js)
        self.assertIn('metric.formula', js)
        self.assertIn('payload.snapshot_as_of', js)
        self.assertNotIn('industry-cash-profit-peer-dialog', html)

    def test_industry_peer_metric_triggers_cover_supported_raw_cards_and_use_keyboard_accessibility(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")

        for metric in ('revenue', 'revenue_growth', 'net_profit', 'ex_net_profit', 'gross_margin', 'net_margin', 'roe_ex', 'debt_ratio', 'ocf', 'free_cf', 'capex', 'goodwill', 'accounts_receivable', 'inventory'):
            self.assertIn(f'data-industry-metric="{metric}"', html)
        for metric in ('cash_profit_ratio', 'fcf_margin', 'capex_intensity', 'accounts_receivable_growth_gap', 'inventory_growth_gap'):
            self.assertIn(f"'{metric}'", js)
        self.assertIn("event.target.closest('[data-industry-metric]')", js)
        self.assertIn("event.key === 'Enter' || event.key === ' '", js)
        self.assertIn("industryMetricDialog?.addEventListener('click'", js)

    def test_industry_peer_metric_table_stably_sorts_current_basis_and_discloses_point_in_time_ttm(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")

        self.assertIn("industryMetricPeerSort: { key: 'current_value', direction: -1 }", js)
        self.assertIn('function stablePeerMetricSort', js)
        self.assertIn('current_value', js)
        self.assertIn('industry-metric-peer-current', js)
        self.assertIn('data-industry-metric-sort', js)
        self.assertIn('TTM 不适用：期末时点值', js)
        self.assertIn('ttm_supported', js)
        self.assertIn('stock-analysis.html?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}', js)

    def test_industry_peer_metric_normalizes_api_yuan_and_percentage_point_metadata_for_display(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")

        self.assertIn("function peerMetricDisplayUnit(unit) { return unit === '元' ? '亿元' : unit; }", js)
        self.assertIn("const displayUnit = peerMetricDisplayUnit(metric.unit || config.unit);", js)
        self.assertIn("peerMetricValue(value, displayUnit)", js)
        self.assertIn("metric.growth_unit === '百分点'", js)
        self.assertIn("return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)} 个百分点`;", js)
        self.assertIn("const changeLabel = metric.growth_unit === '百分点' ? '变化（百分点）'", js)
        self.assertIn("单位：${displayUnit}", js)

    def test_industry_peer_metric_sort_controls_are_button_accessible_and_closing_restores_trigger_focus(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")

        self.assertIn('function industryMetricSortHeader(key, label, sort)', js)
        self.assertIn('aria-sort="${sort.key === key ? (sort.direction === 1 ? \'ascending\' : \'descending\') : \'none\'}"', js)
        self.assertIn('type="button" class="industry-metric-peer-sort" data-industry-metric-sort="${key}"', js)
        self.assertIn('industryMetricPeerTrigger: null', js)
        self.assertIn('async function showIndustryMetricPeers(metricCode, trigger = null)', js)
        self.assertIn('state.industryMetricPeerTrigger = trigger || document.activeElement;', js)
        self.assertIn('showIndustryMetricPeers(trigger.dataset.industryMetric, trigger)', js)
        self.assertIn("industryMetricDialog?.addEventListener('close', () => { state.industryMetricPeerTrigger?.focus(); state.industryMetricPeerTrigger = null; });", js)
        self.assertIn('stock-analysis.js?v=20261018-health-peer-sort-bj-filter-v94', html)


if __name__ == '__main__':
    unittest.main()
