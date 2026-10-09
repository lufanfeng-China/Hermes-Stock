import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class StockAnalysisPageTests(unittest.TestCase):
    def test_two_rows_have_revenue_growth_and_profit_growth_cards(self):
        html = (ROOT / "web" / "stock-analysis.html").read_text(encoding="utf-8")
        self.assertIn('class="analysis-metric-grid"', html)
        self.assertEqual(html.count('<article class="analysis-metric-card">'), 6)
        for chart_id in ('revenue-chart', 'revenue-growth-chart', 'profit-chart', 'net-profit-growth-chart', 'total-profit-chart', 'total-profit-growth-chart'):
            self.assertIn(f'id="{chart_id}"', html)
        for label in ('营业收入', '营收增速', '归母净利润', '归母净利润增速', '净利润', '净利润增速'):
            self.assertIn(f'>{label}<', html)
        self.assertEqual(html.count('单位：亿元'), 3)
        self.assertEqual(html.count('单位：%'), 3)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))', html)
        self.assertIn('height:154px', html)
        self.assertIn('#ff6b6b', html)
        self.assertIn('#9f2634', html)
        self.assertIn('.analysis-zero-axis', html)
        self.assertIn('#70d6a8', html)
        self.assertIn('.analysis-bar.growth.negative', html)

    def test_chart_loader_uses_extra_prior_year_for_same_period_yoy(self):
        js = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertIn('&years=6', js)
        self.assertIn('const latestByYear = new Map()', js)
        self.assertIn("byPeriod.get(`${year - 1}${period.slice(4)}`)", js)
        self.assertIn("renderYoYGrowthBars('revenue-growth-chart', payload.reports, 'revenue')", js)
        self.assertIn("renderYoYGrowthBars('net-profit-growth-chart', payload.reports, 'net_profit')", js)
        self.assertNotIn('ex-profit-growth-chart', js)
        self.assertIn("renderAnnualBars('total-profit-chart', payload.reports, 'profit', 'profit')", js)
        self.assertIn("renderYoYGrowthBars('total-profit-growth-chart', payload.reports, 'profit')", js)
        self.assertIn("const direction = value < 0 ? 'negative' : 'positive'", js)
        self.assertIn('analysis-zero-axis', js)

    def test_financial_loader_supports_six_year_lookback_for_five_year_yoy(self):
        source = (ROOT / "app" / "financial" / "reports.py").read_text(encoding="utf-8")
        self.assertIn('years: int = 3', source)
        self.assertIn('if not 1 <= years <= 6', source)
        self.assertIn('latest_year - years + 1', source)
        self.assertIn('其中：营业收入', source)
        self.assertIn('"profit": search_index._pick(getter("净利润"))', source)
        self.assertIn('营业收入"))', source)


if __name__ == '__main__':
    unittest.main()
