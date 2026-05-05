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

    def test_stock_screener_kline_has_fast_range_controls_and_status_slots(self) -> None:
        html = (WEB_ROOT / "stock-screener.html").read_text(encoding="utf-8")

        self.assertIn('id="stock-screener-kline-controls"', html)
        self.assertIn('id="stock-screener-kline-range"', html)
        self.assertIn('id="stock-screener-kline-latest"', html)
        for preset, label in (("30", "30天"), ("60", "60天"), ("250", "250天"), ("-1", "ALL")):
            self.assertIn(f'data-kline-preset="{preset}"', html)
            self.assertIn(label, html)

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
        self.assertIn('stock-screener-kline-range', script)
        self.assertIn('stock-screener-kline-latest', script)
        self.assertIn('data-kline-preset', script)
        self.assertIn('renderKlineRange', script)
        self.assertIn('renderKlineLatestInfo', script)
        self.assertIn('setPreset', script)
        self.assertIn('limit=5000', script)

    def test_stock_screener_styles_are_terminal_dashboard_aligned(self) -> None:
        self.assertIn(".stock-screener-filter-grid", STYLES_CSS)
        self.assertIn(".stock-screener-results-wrap", STYLES_CSS)
        self.assertIn(".stock-screener-row", STYLES_CSS)
        self.assertIn(".stock-screener-pagination", STYLES_CSS)
        self.assertIn(".stock-screener-kline-svg", STYLES_CSS)


if __name__ == "__main__":
    unittest.main()
