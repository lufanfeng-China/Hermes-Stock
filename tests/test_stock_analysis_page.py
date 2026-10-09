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
            ("固定资产投资", "capex-chart"), ("商誉", "goodwill-chart"),
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
        self.assertIn('renderFinancialHealth(payload.health)', js)
        self.assertIn('five_year_cash_profit_ratio', js)
        self.assertIn('red_flags', js)

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
        self.assertIn("renderYoYGrowthBars('revenue-growth-chart', payload.reports, 'revenue')", js)
        self.assertIn("const needsZeroAxis = variant === 'growth' || numeric.some((value) => value < 0);", js)
        self.assertIn('analysis-bar zero-axis ${variant} ${direction}', js)
        self.assertIn("const zeroClass = value === 0 ? ' zero-value' : '';", js)
        self.assertIn("display === 'percent'", js)

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
