import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"
SERVER_SCRIPT = (PROJECT_ROOT / "scripts" / "serve_stock_dashboard.py").read_text(encoding="utf-8")


class ValuationPageTests(unittest.TestCase):
    def test_valuation_page_exists_with_terminal_shell(self) -> None:
        html = (WEB_ROOT / "valuation.html").read_text(encoding="utf-8")
        self.assertIn('class="app-shell', html)
        self.assertIn('class="topbar', html)
        self.assertIn("Valuation Terminal", html)
        self.assertIn("个股估值", html)
        self.assertIn('id="valuation-input"', html)
        self.assertIn('id="valuation-search-btn"', html)
        self.assertIn('id="valuation-status"', html)
        self.assertIn('id="valuation-summary"', html)
        self.assertIn('id="valuation-current-price"', html)
        self.assertIn('id="valuation-final-low"', html)
        self.assertIn('id="valuation-final-mid"', html)
        self.assertIn('id="valuation-final-high"', html)
        self.assertIn('id="valuation-output-level"', html)
        self.assertIn('id="valuation-dominant-view"', html)
        self.assertIn('id="valuation-template-id"', html)
        self.assertIn('id="valuation-methodology-note"', html)
        self.assertIn('id="valuation-risk-tags"', html)
        self.assertIn('id="valuation-failure-conditions"', html)
        self.assertIn('id="valuation-view-earnings"', html)
        self.assertIn('id="valuation-view-asset"', html)
        self.assertIn('id="valuation-view-revenue"', html)
        self.assertIn('id="valuation-dropdown"', html)
        self.assertIn('class="search-dropdown"', html)

    def test_valuation_page_reuses_stock_score_style_picker_hooks(self) -> None:
        html = (WEB_ROOT / "valuation.html").read_text(encoding="utf-8")
        self.assertIn('class="search-input-wrap"', html)
        self.assertIn('id="valuation-dropdown"', html)
        self.assertNotIn('id="stock-dropdown"', html)

    def test_valuation_script_fetches_api_and_renders_explicit_slots(self) -> None:
        script = (WEB_ROOT / "valuation.js").read_text(encoding="utf-8")
        self.assertIn("/api/valuation?", script)
        self.assertIn("valuation-input", script)
        self.assertIn("valuation-search-btn", script)
        self.assertIn("valuation-status", script)
        self.assertIn("valuation-current-price", script)
        self.assertIn("valuation-final-low", script)
        self.assertIn("valuation-final-mid", script)
        self.assertIn("valuation-final-high", script)
        self.assertIn("valuation-output-level", script)
        self.assertIn("valuation-dominant-view", script)
        self.assertIn("valuation-template-id", script)
        self.assertIn("valuation-risk-tags", script)
        self.assertIn("valuation-failure-conditions", script)
        self.assertIn("valuation-methodology-note", script)
        self.assertIn("valuation-view-earnings", script)
        self.assertIn("valuation-view-asset", script)
        self.assertIn("valuation-view-revenue", script)
        self.assertIn("renderViewPanel", script)
        self.assertIn("setStatus", script)
        self.assertIn("formatOutputLevel", script)
        self.assertIn("DOMContentLoaded", script)
        self.assertIn('/api/search/stocks?q=', script)
        self.assertIn('fetchStockSuggestions', script)
        self.assertIn('loadRecentStockSearches', script)
        self.assertIn('saveRecentStockSearch', script)
        self.assertIn('renderRecentStockSearches', script)
        self.assertIn('valuation-dropdown', script)
        self.assertIn('recent-search', script)
        self.assertIn('localStorage', script)
        self.assertIn('applySuggestion', script)
        self.assertIn('hideSuggestions', script)
        self.assertIn('normalizeMarket', script)
        self.assertIn('const directMatches = await fetchStockSuggestions(input);', script)
        self.assertIn('if ((!market || !symbol) && input) {', script)
        self.assertIn('directMatches.length === 1', script)

    def test_navigation_links_include_valuation_page(self) -> None:
        index_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        rps_html = (WEB_ROOT / "rps-pool.html").read_text(encoding="utf-8")
        stock_score_html = (WEB_ROOT / "stock-score.html").read_text(encoding="utf-8")
        valuation_html = (WEB_ROOT / "valuation.html").read_text(encoding="utf-8")

        self.assertIn('href="/valuation.html"', index_html)
        self.assertIn('href="/valuation.html"', rps_html)
        self.assertIn('href="/valuation.html"', stock_score_html)
        self.assertIn('href="/valuation.html" class="nav-link active"', valuation_html)

    def test_server_exposes_valuation_api_handler(self) -> None:
        self.assertIn('if parsed.path == "/api/valuation":', SERVER_SCRIPT)
        self.assertIn("self.handle_valuation(parsed.query)", SERVER_SCRIPT)
        self.assertIn("def handle_valuation(self, query: str) -> None:", SERVER_SCRIPT)
        self.assertIn("from app.valuation.service import build_valuation_result", SERVER_SCRIPT)


if __name__ == "__main__":
    unittest.main()
