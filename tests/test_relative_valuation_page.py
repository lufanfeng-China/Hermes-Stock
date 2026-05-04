import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


class RelativeValuationPageTests(unittest.TestCase):
    def test_relative_valuation_page_contains_lookup_summary_and_history_sections(self) -> None:
        html = (WEB_ROOT / "relative-valuation.html").read_text(encoding="utf-8")

        self.assertIn("RELATIVE VALUATION", html)
        self.assertIn("id=\"relative-valuation-input\"", html)
        self.assertIn("id=\"relative-valuation-search-btn\"", html)
        self.assertIn("id=\"relative-valuation-dropdown\"", html)
        self.assertIn("search-input-wrap", html)
        self.assertIn("id=\"relative-valuation-status\"", html)
        self.assertIn("id=\"relative-valuation-summary\"", html)
        self.assertIn("id=\"relative-valuation-temperature-history\"", html)
        self.assertIn("id=\"relative-valuation-risk-flags\"", html)
        self.assertIn("行业内估值位置", html)
        self.assertIn("id=\"rv-primary-metric-label\"", html)
        self.assertIn("A类：正常盈利，当前按 PE-TTM 排位", html)
        self.assertIn("B类：微盈利或 PE 失真，改按 PS-TTM 排位", html)
        self.assertIn("C类：亏损但仍有经营，主要按 PS-TTM 与经营质量辅助看", html)
        self.assertIn("D类：无营收概念或清算风险，原则上不做估值分位", html)

    def test_relative_valuation_script_fetches_api_and_renders_history(self) -> None:
        script = (WEB_ROOT / "relative-valuation.js").read_text(encoding="utf-8")

        self.assertIn('/api/relative-valuation?market=', script)
        self.assertIn('/api/search/stocks?q=', script)
        self.assertIn('fetchRelativeValuation', script)
        self.assertIn('fetchStockSuggestions', script)
        self.assertIn('renderRelativeValuation', script)
        self.assertIn('renderTemperatureHistory', script)
        self.assertIn('renderRecentStockSearches', script)
        self.assertIn('saveRecentStockSearch', script)
        self.assertIn('relative-valuation-temperature-history', script)
        self.assertIn('relative-valuation-search-btn', script)
        self.assertIn('relative-valuation-dropdown', script)
        self.assertIn('RELATIVE_VALUATION_RECENT_SEARCHES_STORAGE_KEY', script)
        self.assertIn('relativeValuationState', script)
        self.assertIn('按 PE-TTM 排位', script)
        self.assertIn('按 PS-TTM 排位', script)
        self.assertIn('formatPrimaryMetricLabel', script)
        self.assertIn('formatClassificationDisplay', script)
        self.assertIn('formatPrimaryPercentileEmptyReason', script)
        self.assertIn('样本不足，暂不输出行业内估值位置', script)
        self.assertIn('次新股，暂不输出行业内估值位置', script)
        self.assertIn('D类高风险例外，原则上不做估值分位', script)
        self.assertIn('A类 正常盈利', script)
        self.assertIn('B类 微盈利畸高', script)
        self.assertIn('C类 亏损经营', script)
        self.assertIn('D类 高风险例外', script)
        self.assertIn('addEventListener(\'focus\'', script)
        self.assertIn('addEventListener(\'click\'', script)

    def test_home_and_stock_score_pages_link_to_relative_valuation_page(self) -> None:
        home_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        stock_score_html = (WEB_ROOT / "stock-score.html").read_text(encoding="utf-8")

        self.assertIn('/relative-valuation.html', home_html)
        self.assertIn('/relative-valuation.html', stock_score_html)
