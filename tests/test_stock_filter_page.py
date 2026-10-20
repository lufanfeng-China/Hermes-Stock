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
        self.assertEqual(len(re.findall(r"<fieldset[^>]+data-filter-group=", html)), 5)
        for label in ("RPS 强度", "基础行情", "财务健康", "趋势过滤", "MACD / 均线金叉"):
            self.assertIn(label, html)
        for removed in ("年度派生财报指标", "特定日期内涨跌幅", "N日换手率", "PB / 1/5/20日涨跌幅"):
            self.assertNotIn(removed, html)

    def test_requested_filters_have_real_form_contracts(self):
        html = PAGE.read_text(encoding="utf-8")

        for name in (
            "rps_20_min", "rps_50_min", "rps_120_min", "rps_250_min", "rps_total_min",
            "price_min", "total_market_cap_min", "free_float_market_cap_min", "pe_ttm_min",
            "annual_total_min", "quarterly_total_min", "composite_total_min",
            "annual_growth_quality_min", "annual_profitability_min", "annual_cash_quality_min",
            "annual_working_capital_min", "annual_reinvestment_min", "annual_financial_risk_min",
            "quarterly_growth_min", "quarterly_profitability_min", "quarterly_cash_min",
            "quarterly_working_capital_min", "quarterly_reinvestment_min", "quarterly_financial_risk_min",
            "niche_leader", "trend_daily", "trend_weekly", "trend_monthly", "macd_cross", "golden_cross",
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

    def test_number_range_inputs_hide_native_spinner_controls(self):
        html = PAGE.read_text(encoding="utf-8")

        self.assertIn('.filter-group input[type="number"] { appearance:textfield;', html)
        self.assertIn('input[type="number"]::-webkit-inner-spin-button', html)
        self.assertIn('-webkit-appearance:none;', html)

    def test_all_five_filter_groups_are_collapsed_by_default_and_toggleable(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertEqual(len(re.findall(r'<fieldset class="filter-group is-collapsed" data-filter-group=', html)), 5)
        self.assertEqual(html.count('class="filter-group-toggle"'), 5)
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

    def test_preset_selection_preserves_historical_signal_date_and_does_not_disable_blowup_button(self):
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertIn("var preservedSignalDate = asOfDate.value", script)
        self.assertIn("asOfDate.value = preservedSignalDate", script)
        self.assertNotIn("option.disabled = historical", script)

    def test_result_table_displays_report_release_return_and_quarterly_red_flag_count_from_api_rows(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")
        self.assertIn("财报涨跌", html)
        self.assertIn("触发红旗数量（当季）", html)
        self.assertIn("report_release_return_pct", script)
        self.assertIn("quarterly_triggered_red_flag_count", script)


if __name__ == "__main__":
    unittest.main()
