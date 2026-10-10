import unittest

from app.financial.health import build_financial_health


def annual(year, **metrics):
    return {
        "year": str(year),
        "period": f"{year}A",
        "report_date": f"{year}1231",
        "metrics": metrics,
    }


class FinancialHealthTests(unittest.TestCase):
    def test_uses_five_complete_annual_reports_and_ignores_current_interim_report(self):
        reports = [
            annual(2021, revenue=100, ex_net_profit=10, ocf=12, free_cf=8, gross_margin=30, net_margin=10, roe_ex=12, debt_ratio=40, accounts_receivable=10, inventory=15, capex=4, goodwill=0, equity=60, total_assets=100),
            annual(2022, revenue=120, ex_net_profit=13, ocf=15, free_cf=10, gross_margin=31, net_margin=11, roe_ex=13, debt_ratio=39, accounts_receivable=11, inventory=16, capex=5, goodwill=0, equity=65, total_assets=110),
            annual(2023, revenue=140, ex_net_profit=16, ocf=18, free_cf=12, gross_margin=32, net_margin=12, roe_ex=14, debt_ratio=38, accounts_receivable=12, inventory=17, capex=6, goodwill=0, equity=70, total_assets=120),
            annual(2024, revenue=170, ex_net_profit=21, ocf=25, free_cf=17, gross_margin=34, net_margin=14, roe_ex=16, debt_ratio=37, accounts_receivable=14, inventory=18, capex=8, goodwill=0, equity=76, total_assets=130),
            annual(2025, revenue=200, ex_net_profit=27, ocf=33, free_cf=23, gross_margin=36, net_margin=16, roe_ex=18, debt_ratio=36, accounts_receivable=15, inventory=19, capex=10, goodwill=0, equity=84, total_assets=145),
            {"year": "2026", "period": "2026Q2", "report_date": "20260630", "metrics": {"revenue": 90}},
        ]

        health = build_financial_health(reports)

        self.assertEqual(health["periods"], ["2021A", "2022A", "2023A", "2024A", "2025A"])
        self.assertAlmostEqual(health["derived"]["revenue_cagr"], 18.9207, places=3)
        self.assertAlmostEqual(health["derived"]["ex_net_profit_cagr"], 28.186, places=3)
        self.assertAlmostEqual(health["derived"]["profit_growth_premium"], 9.265, places=3)
        self.assertAlmostEqual(health["derived"]["five_year_cash_profit_ratio"], 1.1839, places=3)
        self.assertEqual(len(health["dimensions"]), 6)
        self.assertLessEqual(health["score"], 100)
        self.assertGreaterEqual(health["score"], 0)
        self.assertEqual(health["red_flags"], [])

    def test_unavailable_rules_preserve_auditable_evidence_contract(self):
        health = build_financial_health([annual(2022), annual(2023)], industry_level_1='银行')
        self.assertEqual(health['status'], 'not_applicable')
        self.assertEqual(len(health['rule_results']), 10)
        for rule in health['rule_results']:
            self.assertEqual(rule['status'], 'unavailable')
            self.assertIn('evidence', rule)
            self.assertEqual(rule['evidence']['periods'], health['periods'])
            self.assertEqual(rule['evidence']['reason'], 'not_applicable')

    def test_conclusions_expose_reproducible_evidence(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=12, free_cf=6, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        conclusion = build_financial_health(reports)['conclusions'][0]
        self.assertIn('evidence', conclusion)
        self.assertIn('metrics', conclusion['evidence'])
        self.assertIn('criteria', conclusion['evidence'])
        self.assertIn('periods', conclusion['evidence'])

    def test_score_breakdown_exposes_reproducible_dimension_evidence(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=12, free_cf=6, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        dimension = build_financial_health(reports)['score_breakdown'][0]
        self.assertIn('evidence', dimension)
        self.assertIn('metrics', dimension['evidence'])
        self.assertIn('thresholds', dimension['evidence'])

    def test_rule_results_expose_reproducible_evidence(self):
        reports = [annual(2021 + i, revenue=100 + i * 20, ex_net_profit=10 + i * 2, ocf=20 - i * 2, free_cf=10, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10 + i * 20, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        rule = next(item for item in build_financial_health(reports)['rule_results'] if item['code'] == 'receivables_growth_gap')
        self.assertIn('evidence', rule)
        self.assertTrue(all({'field', 'period', 'value'} <= set(input_) for input_ in rule['evidence']['inputs']))
        self.assertIn('threshold', rule['evidence'])
        self.assertIn('actual', rule['evidence'])
        self.assertIn('periods', rule['evidence'])

    def test_working_capital_growth_gaps_align_to_the_current_fiscal_year(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10 * (i + 1), inventory=10 * (i + 1), capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        series = build_financial_health(reports)['series']
        self.assertEqual(series['years'], ['2021A', '2022A', '2023A', '2024A', '2025A'])
        self.assertEqual(series['receivable_growth_gap'][0], None)
        self.assertEqual(series['inventory_growth_gap'][0], None)
        self.assertAlmostEqual(series['receivable_growth_gap'][1], 100.0)
        self.assertAlmostEqual(series['receivable_growth_gap'][-1], 25.0)
        self.assertAlmostEqual(series['inventory_growth_gap'][-1], 25.0)

    def test_exposes_missing_five_year_margin_and_goodwill_evidence_series(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30 + i, net_margin=10 + i, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1 + i, equity=60, total_assets=100 + i * 10) for i in range(5)]
        series = build_financial_health(reports)['series']
        for code in ('gross_margin', 'net_margin', 'goodwill_assets_ratio', 'goodwill'):
            self.assertIn(code, series)
            self.assertEqual(len(series[code]), 5)

    def test_early_exit_returns_six_unavailable_dimensions_and_conclusions(self):
        health = build_financial_health([annual(2024), annual(2025)], industry_level_1='银行')
        self.assertEqual(len(health['dimensions']), 6)
        self.assertTrue(all(item['available'] is False and item['status'] == 'unavailable' for item in health['dimensions']))
        self.assertEqual(len(health['conclusions']), 6)
        self.assertTrue(all(item['status'] == 'not_applicable' for item in health['conclusions']))

    def test_missing_roe_makes_profitability_conclusion_insufficient(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=None, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        conclusion = next(item for item in health['conclusions'] if item['code'] == 'profitability')
        self.assertEqual(conclusion['status'], 'insufficient')
        self.assertEqual(conclusion['evidence']['metrics']['roe_ex_trend'], 'unknown')

    def test_flat_margins_do_not_claim_profitability_is_improving(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10 + i, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        conclusion = next(item for item in build_financial_health(reports)['conclusions'] if item['code'] == 'profitability')
        self.assertEqual(conclusion['status'], 'stable')

    def test_leverage_and_deteriorating_fcf_creates_investigation_without_capex_growth(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10, ocf=20 - i, free_cf=20 - i * 6, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40 + i * 3, accounts_receivable=10, inventory=10, capex=5 + i * .5, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        codes = [item['code'] for item in health['investigation_items']]
        conclusion = next(item for item in health['conclusions'] if item['code'] == 'capital_leverage')
        self.assertIn('leverage_fcf_deterioration_risk', codes)
        self.assertEqual(conclusion['status'], 'watch')

    def test_leverage_capex_cashflow_investigation_does_not_require_goodwill_growth(self):
        reports = [annual(2021 + i, revenue=100 + i, ex_net_profit=10, ocf=20 - i * 3, free_cf=15 - i * 4, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=35 + i * 4, accounts_receivable=10, inventory=10, capex=3 + i * 3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        self.assertIn('leverage_capex_cashflow_risk', [item['code'] for item in health['investigation_items']])

    def test_leverage_goodwill_and_cashflow_combination_creates_investigation(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=20 - i * 3, free_cf=10 - i * 3, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40 + i * 5, accounts_receivable=10, inventory=10, capex=3, goodwill=1 + i * 2, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        self.assertIn('leverage_goodwill_cashflow_risk', [item['code'] for item in health['investigation_items']])

    def test_capex_growth_without_revenue_and_fcf_realization_creates_investigation(self):
        reports = [annual(2021 + i, revenue=100 + i, ex_net_profit=10, ocf=15, free_cf=10 - i * 3, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3 + i * 4, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        self.assertIn('capex_realization_risk', [item['code'] for item in health['investigation_items']])

    def test_multi_year_goodwill_growth_without_profit_realization_creates_investigation(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=15, free_cf=8, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=100 * (1.19 ** i), equity=200, total_assets=300) for i in range(5)]
        health = build_financial_health(reports)
        self.assertIn('goodwill_trend_realization_risk', [item['code'] for item in health['investigation_items']])

    def test_goodwill_growth_without_cash_realization_creates_investigation(self):
        reports = [annual(2021 + i, revenue=100 + i * 5, ex_net_profit=10 + i, ocf=20 - i * 3, free_cf=10 - i * 3, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1 + i * 2, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        self.assertIn('goodwill_cash_realization_risk', [item['code'] for item in health['investigation_items']])

    def test_earnings_quality_combination_creates_investigation(self):
        reports = [annual(2021 + i, revenue=100 + i * 20, ex_net_profit=10 + i * 3, ocf=20 - i * 3, free_cf=10 - i * 3, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10 + i * 20, inventory=10 + i * 20, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        self.assertIn('earnings_quality_combination', [item['code'] for item in health['investigation_items']])

    def test_growth_conclusion_requires_consistent_growth_path_for_improving(self):
        revenues = [100, 160, 80, 170, 200]
        reports = [annual(2021 + i, revenue=revenue, ex_net_profit=10 + i, ocf=12, free_cf=8, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i, revenue in enumerate(revenues)]
        health = build_financial_health(reports)
        conclusion = next(item for item in health['conclusions'] if item['code'] == 'growth')
        self.assertNotEqual(conclusion['status'], 'improving')

    def test_zero_to_loss_has_explicit_path_and_investigation(self):
        profits = [0, -1, -2, -3, -4]
        reports = [annual(2021 + i, revenue=100, ex_net_profit=profit, ocf=5, free_cf=1, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i, profit in enumerate(profits)]
        health = build_financial_health(reports)
        self.assertEqual(health['derived']['ex_net_profit_path'], 'break_even_to_loss')
        self.assertIn('ex_net_profit_break_even_to_loss', [item['code'] for item in health['investigation_items']])

    def test_zero_base_profit_red_flags_are_evaluated_when_absolute_comparison_is_available(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=value, ocf=20 if i < 4 else 10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=goodwill, equity=60, total_assets=100) for i, (value, goodwill) in enumerate([(5, 1), (5, 1), (5, 1), (0, 1), (3, 2)])]
        health = build_financial_health(reports)
        rules = {item['code']: item for item in health['rule_results']}
        self.assertEqual(rules['ex_profit_up_ocf_down']['status'], 'triggered')
        self.assertEqual(rules['goodwill_up_profit_not']['status'], 'not_triggered')
        self.assertNotIn('ex_profit_up_ocf_down', health['red_flag_coverage']['unavailable'])

    def test_missing_profitability_or_cash_inputs_make_conclusions_insufficient(self):
        reports = [annual(2021 + i, revenue=100 + i, ex_net_profit=10, ocf=None, free_cf=5, gross_margin=None, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        conclusions = {item['code']: item for item in build_financial_health(reports)['conclusions']}
        self.assertEqual(conclusions['profitability']['status'], 'insufficient')
        self.assertEqual(conclusions['cash_conversion']['status'], 'insufficient')

    def test_explicit_unknown_industry_is_not_scored_as_general_industry(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports, industry_level_1=None)
        self.assertEqual(health['status'], 'not_applicable')
        self.assertEqual(health['reason'], 'industry_classification_unavailable')

    def test_marks_explicit_insurance_and_securities_as_not_applicable(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100) for i in range(5)]
        for industry in ('保险', '证券'):
            self.assertEqual(build_financial_health(reports, industry_level_1=industry)['status'], 'not_applicable')

    def test_cash_conclusion_does_not_call_volatile_declining_cash_trend_improving(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=value, free_cf=value - 5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i, value in enumerate([18, 14, 12, 10, 7])]
        health = build_financial_health(reports)
        conclusion = next(item for item in health['conclusions'] if item['code'] == 'cash_conversion')
        self.assertNotEqual(conclusion['status'], 'improving')

    def test_debt_red_flag_requires_material_cumulative_rise(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40 + i * .1, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        self.assertNotIn('debt_ratio_rising', [item['code'] for item in health['red_flags']])

    def test_deteriorating_cash_reinvestment_and_risk_trends_reduce_dimension_scores(self):
        stable = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=15 + i, free_cf=10 + i, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=60, total_assets=100) for i in range(5)]
        worsening = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=20 - i * 3, free_cf=15 - i * 5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=35 + i * 4, accounts_receivable=10 + i * 5, inventory=10 + i * 5, capex=3 + i * 3, goodwill=i * 3, equity=60, total_assets=100) for i in range(5)]
        stable_health = build_financial_health(stable)
        worsening_health = build_financial_health(worsening)
        stable_scores = {item['code']: item['score'] for item in stable_health['dimensions']}
        worsening_scores = {item['code']: item['score'] for item in worsening_health['dimensions']}
        self.assertLess(worsening_scores['cash_quality'], stable_scores['cash_quality'])
        self.assertLess(worsening_scores['reinvestment'], stable_scores['reinvestment'])
        self.assertLess(worsening_scores['financial_risk'], stable_scores['financial_risk'])

    def test_score_marks_partial_coverage_when_one_dimension_is_unavailable(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=12, free_cf=6, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=None, inventory=None, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        self.assertEqual(health['coverage_weight'], 85)
        self.assertIsNotNone(health['score'])
        self.assertEqual(health['score_coverage_status'], 'partial')

    def test_low_dimension_coverage_withholds_composite_score(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=None, ocf=10, free_cf=5, gross_margin=30, net_margin=None, roe_ex=None, debt_ratio=None, accounts_receivable=None, inventory=None, capex=None, goodwill=None, equity=None, total_assets=None) for i in range(5)]
        health = build_financial_health(reports)
        self.assertLess(health['coverage_weight'], 85)
        self.assertIsNone(health['score'])
        self.assertEqual(health['reason'], 'score_coverage_insufficient')

    def test_returns_auditable_score_and_rule_contract(self):
        reports = [annual(2021 + i, revenue=100 + i * 20, ex_net_profit=10 + i * 2, ocf=12 + i * 2, free_cf=8 + i, gross_margin=30 + i, net_margin=10 + i, roe_ex=12 + i, debt_ratio=50 - i, accounts_receivable=10 + i, inventory=10 + i, capex=3 + i, goodwill=0, equity=60 + i, total_assets=100 + i * 10) for i in range(5)]
        health = build_financial_health(reports)
        self.assertEqual(health['score_version'], 'financial-health-v2')
        self.assertEqual(len(health['rule_results']), 10)
        self.assertTrue(all(item['status'] in {'triggered', 'not_triggered', 'unavailable'} for item in health['rule_results']))
        self.assertGreater(len(health['score_breakdown']), 0)
        self.assertTrue(all('trend_adjustment' in item for item in health['score_breakdown']))

    def test_loss_narrowing_does_not_trigger_profit_decline_red_flag(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=value, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=5, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100) for i, value in enumerate([-80, -70, -60, -50, -40])]
        health = build_financial_health(reports)
        self.assertEqual(health['derived']['ex_net_profit_path'], 'loss_narrowing')
        self.assertNotIn('revenue_up_ex_profit_down', [item['code'] for item in health['red_flags']])

    def test_zero_comparison_base_marks_red_flag_rule_unavailable(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=5, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100) for i in range(5)]
        reports[-2]['metrics']['revenue'] = 0
        health = build_financial_health(reports)
        self.assertIn('revenue_up_ex_profit_down', health['red_flag_coverage']['unavailable'])

    def test_missing_capex_or_debt_makes_capital_leverage_conclusion_insufficient(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=12, free_cf=5, gross_margin=30, net_margin=10, roe_ex=5, debt_ratio=None, accounts_receivable=10, inventory=10, capex=None, goodwill=0, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        conclusion = next(item for item in health['conclusions'] if item['code'] == 'capital_leverage')
        self.assertEqual(conclusion['status'], 'insufficient')

    def test_builds_six_framework_conclusions(self):
        reports = [annual(2021 + i, revenue=100 + i * 20, ex_net_profit=10 + i * 3, ocf=15 + i * 4, free_cf=8 + i * 2, gross_margin=30 + i, net_margin=10 + i, roe_ex=12 + i, debt_ratio=50 - i, accounts_receivable=10 + i, inventory=12 + i, capex=4 + i, goodwill=0, equity=60 + i, total_assets=100 + i * 10) for i in range(5)]
        health = build_financial_health(reports)
        self.assertEqual([item['code'] for item in health['conclusions']], ['growth', 'profit_premium', 'profitability', 'cash_conversion', 'working_capital', 'capital_leverage'])
        self.assertTrue(all(item['status'] in {'improving', 'stable', 'watch', 'insufficient'} for item in health['conclusions']))

    def test_conclusion_evidence_includes_five_year_raw_inputs(self):
        health = build_financial_health([annual(2021 + i) for i in range(5)])
        conclusion = next(item for item in health['conclusions'] if item['code'] == 'cash_conversion')
        self.assertEqual(conclusion['evidence']['periods'], ['2021A', '2022A', '2023A', '2024A', '2025A'])
        self.assertTrue(any(item['field'] == 'ocf' and item['period'] == '2021A' for item in conclusion['evidence']['inputs']))

    def test_investigation_rules_mark_missing_inputs_unavailable_with_coverage(self):
        reports = [annual(2021 + i, revenue=100 + i * 20, ex_net_profit=10 + i, ocf=None, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        result = next(item for item in health['investigation_results'] if item['code'] == 'earnings_quality_combination')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'required_metric_unavailable')
        self.assertIn('earnings_quality_combination', health['investigation_coverage']['unavailable'])

    def test_financial_risk_score_includes_debt_goodwill_and_fcf_five_year_trend_subscores(self):
        reports = [annual(2021 + i, revenue=100, ex_net_profit=10, ocf=20, free_cf=5 + i * 2, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=70 - i * 8, accounts_receivable=10, inventory=10, capex=3, goodwill=20 - i * 3, equity=60, total_assets=100) for i in range(5)]
        score = next(item for item in build_financial_health(reports)['score_breakdown'] if item['code'] == 'financial_risk')
        self.assertEqual(score['evidence']['subscores']['debt_trend'], 2)
        self.assertEqual(score['evidence']['subscores']['goodwill_trend'], 1)
        self.assertEqual(score['evidence']['subscores']['fcf_trend'], 1)
        self.assertEqual(score['trend_adjustment'], 0)

    def test_triggered_investigation_has_auditable_rule_result_and_evidence(self):
        reports = [annual(2021 + i, revenue=100 + i * 20, ex_net_profit=10 + i * 3, ocf=20 - i * 3, free_cf=10 - i * 3, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10 + i * 20, inventory=10 + i * 20, capex=3, goodwill=1, equity=60, total_assets=100) for i in range(5)]
        health = build_financial_health(reports)
        result = next(item for item in health['investigation_results'] if item['code'] == 'earnings_quality_combination')
        self.assertEqual(result['status'], 'triggered')
        self.assertEqual(result['evidence']['periods'], ['2024A', '2025A'])
        self.assertTrue(result['evidence']['inputs'])
        self.assertIn('threshold', result['evidence'])

    def test_capital_intensive_growth_with_rising_fcf_is_not_penalized_by_absolute_capex_level(self):
        reports = [annual(2021 + i, revenue=100 * (1.3 ** i), ex_net_profit=10 * (1.3 ** i), ocf=20 * (1.35 ** i), free_cf=10 * (1.4 ** i), gross_margin=30, net_margin=10, roe_ex=12, debt_ratio=40, accounts_receivable=10, inventory=10, capex=30 * (1.3 ** i), goodwill=0, equity=60, total_assets=100) for i in range(5)]
        score = next(item for item in build_financial_health(reports)['score_breakdown'] if item['code'] == 'reinvestment')
        self.assertEqual(score['evidence']['subscores']['capex_chain'], 5)
        self.assertGreaterEqual(score['points'], 9)

    def test_unavailable_dimension_has_uniform_status_and_missing_fields_reason(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=15, free_cf=10, gross_margin=30, net_margin=10, roe_ex=12, debt_ratio=None, accounts_receivable=10, inventory=10, capex=3, goodwill=None, equity=None, total_assets=None) for i in range(5)]
        dimension = next(item for item in build_financial_health(reports)['dimensions'] if item['code'] == 'financial_risk')
        self.assertEqual(dimension['status'], 'unavailable')
        self.assertEqual(dimension['reason'], 'required_metric_unavailable')
        self.assertIn('debt_ratio', dimension['missing_fields'])

    def test_missing_financial_risk_withholds_composite_score_even_at_85_coverage(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=10 + i, ocf=15 + i, free_cf=10 + i, gross_margin=30 + i, net_margin=10 + i, roe_ex=12 + i, debt_ratio=None, accounts_receivable=10, inventory=10, capex=3, goodwill=None, equity=None, total_assets=None) for i in range(5)]
        health = build_financial_health(reports)
        self.assertEqual(health['coverage_weight'], 85)
        self.assertIsNone(health['score'])
        self.assertEqual(health['reason'], 'financial_risk_unavailable')

    def test_exposes_full_derived_kpi_contract_and_red_flag_coverage(self):
        reports = [annual(2021 + i, revenue=100 + i * 20, ex_net_profit=10 + i * 2, ocf=12 + i * 3, free_cf=8 + i, gross_margin=30 + i, net_margin=10 + i, roe_ex=12 + i, debt_ratio=50 - i, accounts_receivable=10 + i, inventory=15 + i, capex=4 + i, goodwill=i, equity=60 + i * 2, total_assets=100 + i * 10) for i in range(5)]
        health = build_financial_health(reports)
        expected = {'revenue_cagr', 'ex_net_profit_cagr', 'profit_growth_premium', 'gross_margin_change', 'net_margin_change', 'roe_ex_average', 'roe_ex_trend', 'annual_cash_profit_ratio', 'five_year_cash_profit_ratio', 'fcf_margin', 'receivable_growth_gap', 'inventory_growth_gap', 'capex_intensity', 'debt_ratio_trend', 'goodwill_trend'}
        self.assertTrue(expected.issubset(health['derived']))
        self.assertEqual(len(health['series']['years']), 5)
        self.assertEqual(len(health['series']['annual_cash_profit_ratio']), 5)
        self.assertEqual(health['red_flag_coverage']['total'], 10)
        self.assertEqual(health['red_flag_coverage']['evaluated'], 10)

    def test_loss_turnaround_is_explained_instead_of_being_data_missing(self):
        reports = [annual(2021 + i, revenue=100 + i * 10, ex_net_profit=value, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100) for i, value in enumerate((-20, -12, -4, 3, 8))]
        health = build_financial_health(reports)
        self.assertEqual(health['derived']['ex_net_profit_path'], 'turnaround')
        self.assertIsNone(health['derived']['ex_net_profit_cagr'])
        self.assertTrue(any(item['code'] == 'ex_net_profit_turnaround' for item in health['investigation_items']))

    def test_risk_trend_marks_deleveraging_as_improvement(self):
        reports = [annual(2021 + index, revenue=100 + index * 10, ex_net_profit=10 + index, ocf=12 + index, free_cf=5 + index, gross_margin=30, net_margin=10, roe_ex=12, debt_ratio=60 - index * 5, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=50, total_assets=100) for index in range(5)]
        health = build_financial_health(reports)
        risk = next(item for item in health["dimensions"] if item["code"] == "financial_risk")
        self.assertEqual(risk["trend"], "up")

    def test_flags_capex_increase_with_revenue_growth_deceleration(self):
        reports = [
            annual(2021, revenue=100, ex_net_profit=20, ocf=20, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=1, goodwill=0, equity=60, total_assets=100),
            annual(2022, revenue=130, ex_net_profit=21, ocf=21, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=2, goodwill=0, equity=60, total_assets=100),
            annual(2023, revenue=150, ex_net_profit=22, ocf=22, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=3, goodwill=0, equity=60, total_assets=100),
            annual(2024, revenue=165, ex_net_profit=23, ocf=23, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=4, goodwill=0, equity=60, total_assets=100),
            annual(2025, revenue=170, ex_net_profit=24, ocf=24, free_cf=19, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=60, total_assets=100),
        ]
        health = build_financial_health(reports)
        self.assertIn("capex_up_revenue_growth_down", {flag["code"] for flag in health["red_flags"]})

    def test_rejects_non_contiguous_annual_periods(self):
        reports = [annual(year, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=60, total_assets=100) for year in (2018, 2019, 2021, 2023, 2025)]
        health = build_financial_health(reports)
        self.assertEqual(health["status"], "insufficient_data")
        self.assertEqual(health["reason"], "annual_reports_not_contiguous")

    def test_marks_special_industry_as_not_applicable(self):
        reports = [annual(2021 + index, revenue=100, ex_net_profit=10, ocf=10, free_cf=5, gross_margin=30, net_margin=10, roe_ex=10, debt_ratio=40, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=60, total_assets=100) for index in range(5)]
        health = build_financial_health(reports, industry_level_1="银行", industry_level_2="全国性银行")
        self.assertEqual(health["status"], "not_applicable")
        self.assertIsNone(health["score"])
        self.assertIn("银行", health["reason"])

    def test_reports_red_flags_without_allowing_score_to_hide_them(self):
        reports = [
            annual(2021, revenue=100, ex_net_profit=20, ocf=25, free_cf=5, gross_margin=40, net_margin=20, roe_ex=20, debt_ratio=30, accounts_receivable=10, inventory=10, capex=5, goodwill=0, equity=70, total_assets=100),
            annual(2022, revenue=110, ex_net_profit=19, ocf=20, free_cf=-1, gross_margin=39, net_margin=18, roe_ex=18, debt_ratio=35, accounts_receivable=14, inventory=14, capex=6, goodwill=1, equity=72, total_assets=110),
            annual(2023, revenue=120, ex_net_profit=18, ocf=15, free_cf=-2, gross_margin=38, net_margin=16, roe_ex=16, debt_ratio=41, accounts_receivable=20, inventory=20, capex=8, goodwill=3, equity=74, total_assets=125),
            annual(2024, revenue=130, ex_net_profit=17, ocf=12, free_cf=-3, gross_margin=37, net_margin=14, roe_ex=14, debt_ratio=48, accounts_receivable=28, inventory=29, capex=11, goodwill=6, equity=76, total_assets=145),
            annual(2025, revenue=140, ex_net_profit=16, ocf=10, free_cf=-4, gross_margin=36, net_margin=12, roe_ex=12, debt_ratio=56, accounts_receivable=39, inventory=42, capex=15, goodwill=10, equity=78, total_assets=175),
        ]

        health = build_financial_health(reports)

        codes = {flag["code"] for flag in health["red_flags"]}
        self.assertTrue({"revenue_up_ex_profit_down", "receivables_growth_gap", "inventory_growth_gap", "gross_margin_two_year_decline", "roe_ex_decline", "debt_ratio_rising", "fcf_two_year_negative", "goodwill_up_profit_not"}.issubset(codes))
        self.assertGreaterEqual(health["red_flag_count"], 8)
        self.assertIn("status", health)


if __name__ == "__main__":
    unittest.main()
