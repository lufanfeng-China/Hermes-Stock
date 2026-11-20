import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "stock-filter.html"


class StockFilterPageTest(unittest.TestCase):
    def test_page_has_only_the_requested_filter_groups_in_dark_two_column_workbench(self):
        html = PAGE.read_text(encoding="utf-8")

        self.assertIn('class="stock-filter-workbench"', html)
        self.assertIn('class="filter-sidebar"', html)
        self.assertIn('class="filter-results-panel"', html)
        self.assertEqual(len(re.findall(r"<fieldset[^>]+data-filter-group=", html)), 9)
        for label in ("股票范围", "RPS 强度", "基础行情", "财务健康", "趋势过滤", "MACD / 均线金叉", "相对大盘强弱", "威科夫量价事件", "波峰波谷"):
            self.assertIn(label, html)
        for removed in ("年度派生财报指标", "特定日期内涨跌幅", "N日换手率", "PB / 1/5/20日涨跌幅"):
            self.assertNotIn(removed, html)

    def test_requested_filters_have_real_form_contracts(self):
        html = PAGE.read_text(encoding="utf-8")

        for name in (
            "rps_20_min", "rps_50_min", "rps_120_min", "rps_250_min", "rps_total_min",
            "price_min", "return_n_days", "return_n_pct_min", "return_n_pct_max",
            "change_days_n", "up_days_min", "up_days_max", "down_days_min", "down_days_max",
            "total_market_cap_min", "free_float_market_cap_min", "pe_ttm_min",
            "annual_total_min", "quarterly_total_min", "composite_total_min",
            "annual_growth_quality_min", "annual_profitability_min", "annual_cash_quality_min",
            "annual_working_capital_min", "annual_reinvestment_min", "annual_financial_risk_min",
            "quarterly_growth_min", "quarterly_profitability_min", "quarterly_cash_min",
            "quarterly_working_capital_min", "quarterly_reinvestment_min", "quarterly_financial_risk_min",
            "niche_leader", "trend_daily", "trend_weekly", "trend_monthly", "macd_cross", "golden_cross",
            "mrs_score_min", "excess_return_5_pp_min", "excess_return_20_pp_min", "down_market_win_rate_20_min",
        ):
            self.assertIn(f'name="{name}"', html)
    def test_trend_controls_expose_every_backend_supported_status(self):
        html = PAGE.read_text(encoding="utf-8")

        daily = re.search(r'<select name="trend_daily"[^>]*>(.*?)</select>', html, re.S)
        weekly = re.search(r'<select name="trend_weekly"[^>]*>(.*?)</select>', html, re.S)
        monthly = re.search(r'<select name="trend_monthly"[^>]*>(.*?)</select>', html, re.S)
        self.assertIsNotNone(daily)
        self.assertIsNotNone(weekly)
        self.assertIsNotNone(monthly)
        daily_text = daily.group(1) if daily else ""
        weekly_text = weekly.group(1) if weekly else ""
        monthly_text = monthly.group(1) if monthly else ""
        for value in ("strong_bullish", "bullish", "recovering", "neutral", "bearish", "strong_bearish"):
            self.assertIn(f'value="{value}"', daily_text)
        for control in (weekly_text, monthly_text):
            for value in ("strong_bullish", "bullish", "neutral", "bearish"):
                self.assertIn(f'value="{value}"', control)

    def test_wyckoff_and_swing_ui_offer_only_bullish_direction_choices(self):
        from app.swing_presentation import STARS_BY_STATE
        html = PAGE.read_text(encoding="utf-8")
        fields = {}
        for name in ("wyckoff_type", "swing_state", "swing_tendency", "swing_star"):
            match = re.search(r'<select name="' + name + r'"[^>]*>(.*?)</select>', html, re.S)
            if match is None:
                self.fail(f"缺少 {name} 选项控件")
            fields[name] = re.findall(r'<option value="([^"]+)"', match.group(1))
        self.assertEqual(fields["wyckoff_type"], ["Spring", "SOS", "LPS"])
        self.assertEqual(set(fields["swing_state"]),
                         {state for state, (tone, _) in STARS_BY_STATE.items() if tone == "bull"})
        self.assertEqual(fields["swing_tendency"], ["bull"])
        self.assertEqual(fields["swing_star"], ["bull:1", "bull:2", "bull:3"])
        self.assertIn('name="wyckoff_status"', html)
        self.assertIn('name="wyckoff_since"', html)
        self.assertIn('name="swing_entry_only"', html)
        self.assertIn('name="swing_entry_days"', html)

    def test_swing_structure_result_opens_same_day_audited_chart_dialog(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        analysis = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        self.assertIn('id="swing-chart-dialog"', html)
        self.assertIn('id="swing-chart-svg"', html)
        self.assertIn('src="/swing-chart.js?', html)
        self.assertIn('src="/swing-chart.js?', analysis)
        self.assertIn('data-swing-chart', script)
        self.assertIn('as_of_date', script)
        self.assertIn('/api/swing-structure?', script)
        self.assertIn('SwingChart.render', script)
        self.assertIn("snapshot.rule_version ? ' data-rule", script)
        self.assertIn('SwingChart.render', (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8"))

    def test_current_swing_dialog_uses_live_stock_not_stale_table_snapshot(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn("data-historical=", script)
        self.assertIn("if (trigger.dataset.historical === '1') query.set('as_of_date', trigger.dataset.date)", script)
        self.assertIn("data.source_type !== 'live_qfq'", script)
        self.assertIn('表格结构截至', script)
        self.assertIn('单股当前前复权截至', script)

    def test_price_result_opens_same_day_qfq_volume_macd_rps_dialog(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        for token in ('id="price-trend-dialog"', 'id="price-trend-svg"', 'id="price-trend-macd"',
                      '/price-trend-chart.js?', '成交量', 'MACD', 'RPS'):
            self.assertIn(token, html)
        for token in ('data-price-trend', '/api/stock-qfq-trend?', '/api/stock-rps-history?',
                      'PriceTrendChart.chartEvidence', 'PriceTrendChart.renderMacd', 'KlineChart'):
            self.assertIn(token, script)

    def test_number_range_inputs_hide_native_spinner_controls(self):
        html = PAGE.read_text(encoding="utf-8")

        self.assertIn('.filter-group input[type="number"] { appearance:textfield;', html)
        self.assertIn('input[type="number"]::-webkit-inner-spin-button', html)
        self.assertIn('-webkit-appearance:none;', html)

    def test_results_keep_swing_structure_accessible_by_horizontal_scroll(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn('grid-template-columns:280px minmax(0,1fr)', html)
        self.assertIn('grid-template-columns:250px minmax(0,1fr)', html)
        self.assertIn('.result-wrap { overflow:auto; }', html)
        self.assertIn('.filter-table th:last-child, .filter-table td.swing-cell { min-width:250px;', html)
        self.assertIn('min-width:250px;', html)
        self.assertNotIn('.filter-table td.swing-cell { position:sticky;', html)
        self.assertIn('.stock-filter-workbench { grid-template-columns:1fr; }', html)

    def test_retired_wyckoff_result_column_does_not_style_earnings_yield(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertNotIn('.filter-table th:nth-last-child(2), .filter-table td:nth-last-child(2) { min-width:160px;', html)
        self.assertNotIn('position:sticky; right:250px;', html)
        self.assertIn('.result-wrap { overflow:auto; }', html)

    def test_filter_groups_collapse_empty_except_the_scope_group(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        # 9 组：01 股票范围默认展开（入口条件），其余折叠
        self.assertEqual(html.count('class="filter-group-toggle"'), 9)
        self.assertEqual(len(re.findall(r'<fieldset class="filter-group is-collapsed" data-filter-group=', html)), 8)
        self.assertIn('<fieldset class="filter-group" data-filter-group="scope">', html)
        self.assertIn("filter-group-toggle", script)
        self.assertIn("classList.toggle('is-collapsed'", script)

    def test_financial_reversal_preset_is_a_top_of_sidebar_real_filter_control(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertIn('class="preset-block"', html)
        self.assertIn('data-preset="financial_reversal"', html)
        self.assertIn('name="preset"', html)
        self.assertLess(html.index('class="preset-block"'), html.index('data-filter-group="rps"'))
        self.assertIn('presetInput', script)

    def test_blowup_break_preset_is_a_real_top_of_sidebar_filter_control(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertIn('data-preset="blowup_break"', html)
        self.assertIn("爆量突破", html)
        self.assertIn("presetInput", script)

    def test_historical_signal_date_control_has_a_real_form_contract(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertIn('name="as_of_date"', html)
        self.assertIn('历史基本面选股', html)
        self.assertIn("as_of_date", script)
        self.assertIn("is_historical", script)

    def test_historical_snapshot_building_retries_without_rendering_a_terminal_error(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertIn("historical_snapshot_building", script)
        self.assertIn("scheduleHistoricalSnapshotRetry", script)
        self.assertIn("正在生成历史快照", script)

    def test_historical_snapshot_progress_renders_a_percentage_bar(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertIn("error.progress", script)
        self.assertIn("<progress", script)
        self.assertIn("progress.percent", script)

    def test_preset_selection_preserves_historical_signal_date_and_manual_filters(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        block = script.split("  presetOptions.forEach(function (option) {", 2)[-1].split("  function updateHistoricalMode()", 1)[0]
        self.assertIn("togglePreset(option.dataset.preset)", block)
        self.assertNotIn("form.reset()", block)
        self.assertNotIn("asOfDate.value =", block)
        self.assertNotIn("option.disabled = historical", script)

    def test_scope_group_has_industry_and_concept_dialog_selectors(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        for token in ('id="industry-scope-open"', 'id="concept-scope-open"',
                      'id="industry-scope-dialog"', 'id="concept-scope-dialog"',
                      'name="industry_l2_codes"', 'name="industry_temperature_levels"',
                      'id="industry-temperature-options"', 'name="concept_codes"',
                      'name="concept_temperature_levels"', 'id="scope-selection-summary"'):
            self.assertIn(token, html)
        self.assertIn("/api/stock-filter/scopes", script)
        self.assertIn("renderScopeSummary", script)
        self.assertIn("concept_temperature_window", script)
        self.assertIn("industry_temperature_window", script)
        self.assertIn("draftIndustryTemperatureLevels", script)

    def test_scope_selection_is_not_reset_when_a_preset_is_toggled(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        block = script.split("  presetOptions.forEach(function (option) {", 2)[-1].split("  function updateHistoricalMode()", 1)[0]
        self.assertNotIn("clearScopeSelection", block)
        self.assertNotIn("industry_l2_codes.value =", block)
        self.assertNotIn("concept_codes.value =", block)

    def test_custom_scope_status_does_not_mislabel_the_reduced_pool_as_full_market(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn("hasCustomScope", script)
        self.assertIn("行业/概念范围", script)

    def test_historical_mode_disables_current_concept_scope_without_silent_fallback(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn("当前概念及概念温度不支持历史日期", script)
        self.assertIn("conceptScopeOpen.disabled = historical", script)

    def test_historical_mode_clears_current_industry_temperature_but_keeps_explicit_industries(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn("selectedIndustryTemperatureLevels.clear()", script)
        self.assertIn("当前行业温度不支持历史日期", script)

    def test_result_table_displays_report_release_return_without_the_red_flag_count(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn("财报涨跌", html)
        self.assertIn("report_release_return_pct", script)
        # 红旗数量列已按需求从结果清单移除；数据仍由接口返回，只是不再展示
        self.assertNotIn("触发红旗数量（当季）", html)
        self.assertNotIn("redFlagCell", script)
        self.assertIn('colspan="12"', script)  # 删除结果展示列后，空状态须占满全表
        self.assertNotIn('colspan="11"', script)
        self.assertNotIn('colspan="10"', script)

    def test_rps_total_is_not_a_result_column_but_remains_a_filter_and_sort(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        header = html.split('<table class="filter-table"><thead><tr>', 1)[1].split('</tr></thead>', 1)[0]
        self.assertNotIn('RPS Total', header)
        self.assertEqual(header.count('<th'), 12)
        self.assertIn('选择', header)
        self.assertIn('<th>相对大盘强弱</th>', header)
        self.assertNotIn('威科夫事件', header)
        self.assertIn('<th>波峰波谷结构</th>', header)
        self.assertNotIn('rpsCell(row)', script)
        self.assertIn('name="rps_total_min"', html)
        self.assertIn('<option value="rps_total">RPS Total（降序）</option>', html)

    def test_watchlist_batch_add_has_row_checkboxes_and_existing_post_contract(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn('id="add-to-watchlist"', html)
        self.assertIn('id="watchlist-feedback"', html)
        self.assertIn('data-stock-select', script)
        self.assertIn("new Map()", script)
        self.assertIn("fetch('/api/watchlist/add'", script)
        self.assertIn("JSON.stringify({stocks: stocks})", script)
        self.assertIn("run(1);", script)
        self.assertIn("selectedStocks.clear()", script)

    def test_valuation_sort_options_send_ascending_order(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn('<option value="pe_ttm" data-order="asc">PE-TTM（升序）</option>', html)
        self.assertIn('<option value="pe_percentile_5y" data-order="asc">PE五年分位（升序）</option>', html)
        self.assertIn('<option value="price_percentile_5y" data-order="asc">股价5年分位（升序）</option>', html)
        self.assertIn("query.set('order', sort.selectedOptions[0].dataset.order || 'desc');", script)


if __name__ == "__main__":
    unittest.main()
