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
        for removed in ("年度派生财报指标", "特定日期内涨跌幅", "N日换手率", "PS-TTM", "PB / 1/5/20日涨跌幅"):
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
            "trend_daily", "trend_weekly", "trend_monthly", "macd_cross", "golden_cross",
        ):
            self.assertIn(f'name="{name}"', html)
    def test_financial_reversal_preset_is_a_top_of_sidebar_real_filter_control(self):
        html = PAGE.read_text(encoding="utf-8")
        script = (ROOT / "web" / "stock-filter.js").read_text(encoding="utf-8")

        self.assertIn('class="preset-block"', html)
        self.assertIn('data-preset="financial_reversal"', html)
        self.assertIn('name="preset"', html)
        self.assertLess(html.index('class="preset-block"'), html.index('data-filter-group="rps"'))
        self.assertIn('presetInput', script)


if __name__ == "__main__":
    unittest.main()
