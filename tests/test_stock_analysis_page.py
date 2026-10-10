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

    def test_health_kpi_section_precedes_raw_metric_charts(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('id="financial-health-kpi"', html)
        self.assertLess(html.index('id="financial-health-kpi"'), html.index('aria-label="五年经营指标"'))
        for label in ('综合健康度', '财务红旗', '核心增长质量', '盈利能力', '现金含金量', '营运资本健康度', '再投资效率', '财务风险'):
            self.assertIn(label, html)
        self.assertIn('renderFinancialHealth(payload.health, payload.latest_report)', js)
        self.assertIn('five_year_cash_profit_ratio', js)
        self.assertIn('not_applicable', js)
        self.assertIn('annual_reports_not_contiguous', js)
        self.assertIn('triggeredRules', js)
        self.assertIn('item.status === \'triggered\'', js)
        self.assertIn('healthEvidenceSummary', js)
        for token in ('health-red-flag-panel', 'health-investigation-panel', 'health-unavailable-panel', 'health-series', 'rule_results', 'score_breakdown', '资本开支（CapEx）'):
            self.assertIn(token, html if token.startswith('health-') or token == '资本开支（CapEx）' else js)

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
        self.assertIn("renderYoYGrowthBars('revenue-growth-chart', evidenceReports, 'revenue', annualPeriods)", js)
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

    def test_health_ui_has_distinct_loading_and_failure_states(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn("renderFinancialHealth(null, null, 'loading')", js)
        self.assertIn("renderFinancialHealth(null, null, 'failed')", js)
        self.assertIn('正在加载财报与健康度评估结果', js)
        self.assertIn('健康度数据加载失败', js)
        self.assertNotIn("'全部红旗规则及评分维度均有可用数据。'", js)

    def test_partial_score_and_industry_calibration_disclosures_are_rendered(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('health-score-label', html)
        self.assertIn('当前未按行业分位数校准', html)
        self.assertIn("health.score_coverage_status === 'partial'", js)
        self.assertIn('部分覆盖评分', js)

    def test_p2_red_flag_date_readability_and_request_contracts(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('health-data-asof', html)
        self.assertIn('高优先级', js)
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
