import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class StockAnalysisPageTests(unittest.TestCase):
    def test_first_metric_row_has_two_compact_annual_bar_cards(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        self.assertIn('class="analysis-metric-grid"', html)
        self.assertIn('id="revenue-chart"', html)
        self.assertIn('id="profit-chart"', html)
        self.assertIn('>营业收入<', html)
        self.assertIn('>归母净利润<', html)
        self.assertEqual(html.count('单位：亿元'), 2)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))', html)
        self.assertIn('height:154px', html)
        self.assertIn('#ff6b6b', html)
        self.assertIn('#9f2634', html)

    def test_chart_loader_requests_five_year_reports_and_uses_latest_report_per_year(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('&years=5', js)
        self.assertIn('const latestByYear = new Map()', js)
        self.assertIn("row?.report_date || ''", js)
        self.assertIn("period.endsWith('A') ? '' : period.slice(4)", js)
        self.assertIn("renderAnnualBars('revenue-chart', payload.reports, 'revenue', 'revenue')", js)
        self.assertIn("renderAnnualBars('profit-chart', payload.reports, 'net_profit', 'profit')", js)

    def test_financial_loader_supports_bounded_five_year_window(self):
        source = (ROOT / "app" / "financial" / "reports.py").read_text(encoding="utf-8")
        self.assertIn('years: int = 3', source)
        self.assertIn('if not 1 <= years <= 5', source)
        self.assertIn('latest_year - years + 1', source)
        self.assertIn('其中：营业收入', source)
        self.assertIn('营业收入"))', source)


if __name__ == '__main__':
    unittest.main()
