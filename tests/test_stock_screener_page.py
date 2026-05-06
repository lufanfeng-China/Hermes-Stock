import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"
STYLES_CSS = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")


class StockScreenerPageTests(unittest.TestCase):
    def test_stock_screener_page_contains_filter_workbench_results_and_kline(self) -> None:
        html = (WEB_ROOT / "stock-screener.html").read_text(encoding="utf-8")

        self.assertIn("股票筛选", html)
        self.assertIn('id="stock-screener-filter-form"', html)
        self.assertIn('id="stock-screener-results-tbody"', html)
        self.assertIn('id="stock-screener-pagination"', html)
        self.assertIn('id="stock-screener-kline-section"', html)
        self.assertIn('id="stock-screener-kline-svg"', html)
        self.assertIn('src="/stock-screener.js"', html)

        for label in (
            "全市场总分",
            "行业内总分",
            "全市场排名",
            "二级行业排名",
            "申万一级",
            "申万二级",
            "行业温度",
            "估值分类",
            "行业内估值位置",
            "区间标签",
            "个股RPS20",
            "个股RPS50",
            "个股RPS120",
            "个股RPS250",
            "二级行业RPS20",
            "现价",
        ):
            self.assertIn(label, html)

        for header in (
            "股票名称",
            "现价",
            "PE-TTM",
            "PS-TTM",
            "总市值",
            "全市场排名",
            "二级排名",
            "估值分类",
            "区间标签",
            "行业内估值位置",
            "行业温度",
            "行业维度",
            "行业内总分",
            "行业排名",
        ):
            self.assertIn(header, html)

    def test_stock_screener_valuation_band_filter_is_dropdown(self) -> None:
        html = (WEB_ROOT / "stock-screener.html").read_text(encoding="utf-8")

        self.assertIn('<select name="valuation_band">', html)
        self.assertNotIn('name="valuation_band" type="text"', html)
        for option in ("低估区间", "合理偏低", "合理", "合理偏高", "高估区间", "样本不足", "次新股"):
            self.assertIn(f'<option value="{option}">{option}</option>', html)

    def test_stock_screener_filter_workbench_is_collapsed_by_default_and_toggleable(self) -> None:
        html = (WEB_ROOT / "stock-screener.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "stock-screener.js").read_text(encoding="utf-8")

        self.assertIn('id="stock-screener-filter-toggle"', html)
        self.assertIn('aria-controls="stock-screener-filter-form"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('展开筛选', html)
        self.assertIn('id="stock-screener-filter-form"', html)
        self.assertIn('hidden', html.split('id="stock-screener-filter-form"', 1)[1].split('>', 1)[0])
        self.assertIn('toggleScreenerFilters', script)
        self.assertIn('stock-screener-filter-toggle', script)
        self.assertIn("aria-expanded", script)
        self.assertIn('收起筛选', script)
        self.assertIn('展开筛选', script)

    def test_stock_screener_has_extensible_strategy_button_area(self) -> None:
        html = (WEB_ROOT / "stock-screener.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "stock-screener.js").read_text(encoding="utf-8")

        self.assertIn('id="stock-screener-strategy-buttons"', html)
        self.assertIn('data-strategy="rps_standard_launch"', html)
        self.assertIn('RPS标准', html)
        self.assertNotIn('RPS标准启动', html)
        self.assertIn('data-strategy="rps_attack"', html)
        self.assertIn('RPS进攻', html)
        self.assertIn('STRATEGY_PRESETS', script)
        self.assertIn('rps_standard_launch', script)
        self.assertIn('rps_attack', script)
        self.assertIn('applyStrategyPreset', script)
        self.assertIn('renderScreenerLoadingState', script)
        self.assertIn('countEl.textContent = \'…\'', script)
        self.assertIn('collapseScreenerFiltersAfterStrategy', script)
        self.assertIn("form.hidden = true", script)
        self.assertIn("filterToggleEl.setAttribute('aria-expanded', 'false')", script)
        self.assertIn("filterToggleEl.textContent = '展开筛选'", script)
        self.assertIn('strategy', script)
        self.assertIn('stock-screener-strategy-buttons', script)

    def test_stock_screener_kline_copies_rps_pool_chart_shell(self) -> None:
        html = (WEB_ROOT / "stock-screener.html").read_text(encoding="utf-8")

        self.assertIn('id="stock-screener-kline-section" class="kline-section terminal-panel hidden"', html)
        self.assertIn('class="kline-header terminal-panel-header"', html)
        self.assertIn('class="kline-controls"', html)
        self.assertIn('id="stock-screener-preset-controls" class="zoom-controls"', html)
        self.assertIn('id="stock-screener-kline-range-label" class="kline-range-label"', html)
        self.assertIn('class="kline-chart-wrap"', html)
        self.assertIn('id="stock-screener-kline-svg" class="kline-svg"', html)
        for preset, label in (("20", "20D"), ("60", "60D"), ("120", "120D"), ("250", "250D"), ("-1", "ALL")):
            self.assertIn(f'data-preset="{preset}"', html)
            self.assertIn(label, html)
        self.assertNotIn('stock-screener-kline-controls', html)
        self.assertNotIn('stock-screener-kline-latest', html)
        self.assertNotIn('data-kline-preset', html)

    def test_stock_screener_script_uses_api_pagination_and_kline_chart(self) -> None:
        script = (WEB_ROOT / "stock-screener.js").read_text(encoding="utf-8")

        self.assertIn("/api/stock-screener", script)
        self.assertIn("/api/stock-kline", script)
        self.assertIn("/api/stock-rps-history", script)
        self.assertIn("KlineChart", script)
        self.assertIn("page_size", script)
        self.assertIn("50", script)
        self.assertIn("renderScreenerRows", script)
        self.assertIn("loadScreenerKline", script)
        self.assertIn("formatMarketCapYi", script)
        self.assertIn("formatPercentile", script)
        self.assertIn("pe_ttm", script)
        self.assertIn("ps_ttm", script)
        self.assertIn("total_market_cap", script)
        self.assertIn("market_total_rank", script)
        self.assertIn("industry_temperature_label", script)
        self.assertIn("primary_percentile", script)
        self.assertIn('createScreenerKlineChart', script)
        self.assertIn('bindScreenerChartPresetEvents', script)
        self.assertIn('stock-screener-preset-controls', script)
        self.assertIn('stock-screener-kline-range-label', script)
        self.assertIn('data-preset', script)
        self.assertIn('currentKlinePreset = 60', script)
        self.assertIn('limit=300', script)
        self.assertIn('classList.remove(\'hidden\')', script)
        self.assertIn('`${range.start} ~ ${range.end}`', script)
        self.assertNotIn('renderKlineLatestInfo', script)
        self.assertNotIn('stock-screener-kline-latest', script)
        self.assertNotIn('limit=5000', script)

    def test_stock_screener_styles_are_terminal_dashboard_aligned(self) -> None:
        self.assertIn(".stock-screener-filter-grid", STYLES_CSS)
        self.assertIn(".stock-screener-results-wrap", STYLES_CSS)
        self.assertIn(".stock-screener-row", STYLES_CSS)
        self.assertIn(".stock-screener-pagination", STYLES_CSS)
        self.assertIn("#stock-screener-kline-section.hidden", STYLES_CSS)
        self.assertIn(".kline-svg", STYLES_CSS)
        self.assertIn(".zoom-button", STYLES_CSS)
        self.assertNotIn(".stock-screener-kline-controls", STYLES_CSS)


if __name__ == "__main__":
    unittest.main()
