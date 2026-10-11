import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class StockAnalysisPageTests(unittest.TestCase):
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
        self.assertEqual(html.count('<article class="analysis-metric-card">'), 14)
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
        self.assertIn("renderYoYGrowthBars('revenue-growth-chart', chartReports, 'revenue', annualPeriods, payload.reports)", js)
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
        self.assertIn('chartReports = appendLatestQuarter(healthEvidenceReports, payload.reports)', js)
        self.assertIn("renderYoYGrowthBars('revenue-growth-chart', chartReports, 'revenue', annualPeriods, payload.reports)", js)
        self.assertIn("String(row?.period || '').endsWith('A')", js)

    def test_annual_and_quarterly_monitoring_summary_comparison_table(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        for label in ('总分', '覆盖度', '核心增长质量', '盈利能力', '现金含金量', '营运资本', '再投资效率', '财务风险', '已触发红旗', '待调查事项'):
            self.assertIn(label, html)
        self.assertIn('总分（100）', html)
        self.assertIn('核心增长质量（20）', html)
        self.assertIn("const annualPeriod = '五年年报';", js)
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
        self.assertIn('annual: data.health.conclusions', js)
        self.assertIn('quarterly: data.monitor.alerts', js)
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
        self.assertIn('HEALTH_QUESTION_PROMPTS[item.code] || item.title', js)

    def test_five_year_derived_and_basic_metrics_are_retained(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="health-derived"', html)
        self.assertIn('id="health-series"', html)
        self.assertIn('五年派生指标', html)
        self.assertIn('renderHealthMetrics(payload.health)', js)
        self.assertIn('营业收入', html)
        self.assertIn('自由现金流', html)

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
        self.assertIn("最新季报：${quarterPeriod}", js)

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
        self.assertIn('healthMetricValue(key, series[key]?.[index], suffix)', js)
        self.assertIn('.health-metric-value.metric-positive', css)
        self.assertIn('.health-metric-value.metric-negative', css)

    def test_five_year_series_goodwill_uses_yi(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('function healthSeriesValue(key, value, suffix)', js)
        self.assertIn("key === 'goodwill'", js)
        self.assertIn('healthMetricValue(key, series[key]?.[index], suffix)', js)

    def test_kpi_and_five_year_series_metrics_expose_definition_tooltips(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('const HEALTH_METRIC_TOOLTIPS =', js)
        self.assertIn('function healthMetricLabel(key, label)', js)
        self.assertIn('healthMetricLabel(tooltipKey || key, label)', js)
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


if __name__ == '__main__':
    unittest.main()
