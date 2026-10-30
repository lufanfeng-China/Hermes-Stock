import unittest

from app.financial.quarterly_monitor import build_quarterly_financial_monitor
from app.undervaluation.quarterly_momentum import evaluate_quarterly_momentum


def monitor_for(previous, current, **overrides):
    def row(period, profit, revenue):
        metrics = dict(revenue=revenue, ex_net_profit=profit, ocf=20, capex=10,
                       gross_margin=20, net_margin=10)
        if period == '2026Q3':
            metrics.update(overrides)
        return dict(period=period, report_date=period[:4] + ('1231' if period.endswith('A') else '0930'), metrics=metrics)
    return build_quarterly_financial_monitor([
        row('2025Q3', previous, 100), row('2025A', 30, 150),
        row('2026Q3', current, 120)], '电子')


class ProfitDirectionTests(unittest.TestCase):
    def test_loss_widening_is_negative_in_monitor_and_momentum(self):
        monitor = monitor_for(-10, -20)
        self.assertEqual(-100, monitor['yoy']['ex_net_profit'])
        comparison = monitor['profit_comparisons']['ex_net_profit']
        self.assertEqual('deteriorating', comparison['direction'])
        self.assertEqual('亏损扩大', comparison['label'])
        result = evaluate_quarterly_momentum(monitor)
        self.assertEqual('NOT_IMPROVING', result['status'])
        self.assertIs(comparison, result['evidence']['profit_change'])
        self.assertEqual('watch', monitor['dimensions'][0]['status'])
        self.assertIn('revenue_up_profit_down', [a['code'] for a in monitor['alerts']])

    def test_states_zero_boundaries_and_small_base(self):
        cases = [(10, 20, '增盈', 'improving'), (20, 10, '盈利下滑', 'deteriorating'),
                 (-20, -10, '减亏', 'improving'), (-10, -20, '亏损扩大', 'deteriorating'),
                 (-10, 10, '扭亏', 'improving'), (10, -10, '盈转亏', 'deteriorating'),
                 (10, 10, '持平', 'flat'), (-10, 0, '减亏', 'improving'),
                 (0, 10, '增盈', 'improving'), (10, 0, '盈利下滑', 'deteriorating'),
                 (0, -10, '亏损扩大', 'deteriorating'), (0, 0, '持平', 'flat'),
                 (-1e-12, -2e-12, '亏损扩大', 'deteriorating')]
        for previous, current, label, direction in cases:
            with self.subTest(previous=previous, current=current):
                monitor = monitor_for(previous, current)
                change = monitor['profit_comparisons']['ex_net_profit']
                self.assertEqual(label, change['label'])
                self.assertEqual(direction, change['direction'])
                self.assertEqual(current - previous, change['delta'])
                self.assertEqual('2026Q3', change['current_period'])
                self.assertEqual('2025Q3', change['previous_period'])
                if previous == 0:
                    self.assertIsNone(change['yoy_pct'])
                else:
                    self.assertAlmostEqual((current - previous) / abs(previous) * 100, change['yoy_pct'])
                self.assertEqual('IMPROVING' if direction == 'improving' else 'NOT_IMPROVING',
                                 evaluate_quarterly_momentum(monitor)['status'])

    def test_missing_or_nonfinite_is_unavailable_without_period_fallback(self):
        for value in (None, float('nan'), float('inf'), -float('inf')):
            for previous, current in ((value, 10), (10, value)):
                monitor = monitor_for(previous, current)
                self.assertEqual('2026Q3', monitor['latest_period'])
                self.assertEqual('unavailable', monitor['profit_comparisons']['ex_net_profit']['direction'])
                self.assertEqual('unavailable', monitor['dimensions'][0]['status'])
                self.assertEqual('UNAVAILABLE', evaluate_quarterly_momentum(monitor)['status'])

    def test_required_evidence_and_other_gates(self):
        for overrides in ({'revenue': None}, {'revenue': float('inf')}, {'gross_margin': None}):
            self.assertEqual('UNAVAILABLE', evaluate_quarterly_momentum(monitor_for(-20, -10, **overrides))['status'])
        for overrides in ({'revenue': 90}, {'gross_margin': 10}):
            self.assertEqual('NOT_IMPROVING', evaluate_quarterly_momentum(monitor_for(-20, -10, **overrides))['status'])
        legacy = {'status': 'available', 'yoy': {'revenue': 10, 'ex_net_profit': 20},
                  'dimensions': [{'code': 'profitability', 'available': True, 'status': 'stable'}]}
        self.assertEqual('UNAVAILABLE', evaluate_quarterly_momentum(legacy)['status'])

    def test_zero_base_alerts_use_direction_not_missing_percentage(self):
        improving = monitor_for(0, 10, ocf=10)
        self.assertIn('profit_up_ocf_down', [a['code'] for a in improving['alerts']])
        worsening = monitor_for(0, -10)
        self.assertIn('revenue_up_profit_down', [a['code'] for a in worsening['alerts']])

    def test_other_growth_formulas_are_unchanged(self):
        monitor = monitor_for(10, 20)
        self.assertAlmostEqual(20, monitor['yoy']['revenue'])
        self.assertEqual(0, monitor['yoy']['ocf'])
        self.assertEqual(0, monitor['yoy']['capex'])


if __name__ == '__main__':
    unittest.main()
