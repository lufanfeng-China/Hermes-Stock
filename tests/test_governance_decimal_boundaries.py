"""Synthetic decimal evidence only; package and discovery-compatible regressions."""
import copy
import json
import unittest

from app.financial.governance_risk import build_governance_risk
try:
    from .test_governance_risk import evidence, ratio, rule, AS_OF
except ImportError:
    from test_governance_risk import evidence, ratio, rule, AS_OF


def overdue_evidence(sales=5.65, overdue=1.13, revenue=11.3):
    data = evidence()
    data['related_sales']['ratio'].update(numerator=sales, denominator=revenue)
    rec = ratio('related_sales')
    rec.update(numerator=overdue, denominator=revenue, metric='related_trade_receivables_overdue_gt_180',
               numerator_basis='related_trade_receivables_overdue_gt_180',
               days_basis='overdue', days_operator='>', days_threshold=180)
    data['related_sales']['rules']['related_overdue'] = rule(
        True, receivables=rec, status='unresolved')
    return data


class GovernanceDecimalBoundariesTests(unittest.TestCase):
    def test_decimal_ratio_thresholds_and_descriptive_flags(self):
        for code, n, d, level, deduction, flag in [
            ('related_sales', 1.13, 11.3, 'watch', 5, None),
            ('related_sales', 2.01, 6.7, 'high', 10, None),
            ('major_shareholder_pledge', 2.01, 6.7, 'watch', 5, None),
            ('major_shareholder_pledge', 4.52, 5.65, 'high', 10, 'highly_pledged'),
        ]:
            with self.subTest(code=code, numerator=n, denominator=d):
                data = evidence()
                data[code]['ratio'].update(numerator=n, denominator=d)
                before = copy.deepcopy(data)
                result = build_governance_risk(80, data, AS_OF)
                item = next(i for i in result['items'] if i['code'] == code)
                self.assertEqual(item['level'], level)
                self.assertEqual(item['deduction'], deduction)
                self.assertEqual(result['original_score'], 80)
                self.assertEqual(result['adjusted_score'], 80 - deduction)
                self.assertTrue(result['complete'])
                if flag:
                    self.assertTrue(item[flag])
                self.assertIsInstance(item['ratio_pct'], float)
                json.dumps(result, allow_nan=False)
                self.assertEqual(data, before)

    def test_exact_decimal_overdue_joint_boundary_is_critical(self):
        result = build_governance_risk(80, overdue_evidence(), AS_OF)
        item = result['items'][1]
        self.assertEqual(item['level'], 'critical')
        self.assertEqual(item['deduction'], 20)
        self.assertTrue(item['high_dependence'])
        self.assertTrue(item['rule_results'][0]['triggered'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['adjusted_score'], 60)
        json.dumps(result, allow_nan=False)

    def test_nontriggering_overdue_retains_full_auditable_details_and_ui(self):
        try:
            from . import test_governance_risk_ui as ui_contract
        except ImportError:
            import test_governance_risk_ui as ui_contract
        for sales, overdue in [(50, 9.999), (49.999, 10)]:
            with self.subTest(sales=sales, overdue=overdue):
                data = overdue_evidence(sales, overdue, 100)
                event = data['related_sales']['rules']['related_overdue']
                result = build_governance_risk(80, data, AS_OF)
                item = result['items'][1]
                check = item['rule_results'][0]
                self.assertTrue(check['evaluated'])
                self.assertFalse(check['triggered'])
                self.assertEqual(item['level'], 'high')
                self.assertEqual(result['adjusted_score'], 70)
                self.assertIn('details', check)
                self.assertEqual(check['details']['receivables'], event['receivables'])
                for key in ('as_of', 'subject', 'scope', 'status'):
                    self.assertEqual(check['details'][key], event[key])
                ui_contract.GovernanceRiskUIContract().run_ui(
                    'const payload=' + json.dumps(result, ensure_ascii=False, allow_nan=False) + ''';
renderGovernanceRisk(payload);
el('governance-risk-items').children[1].listeners.click();
const text=el('governance-evidence-content').textContent;
for (const expected of ['receivables', 'numerator', 'denominator', '100', '2025-12-31',
                         '2026-10-26', 'overdue', '180']) assert.ok(text.includes(expected), expected);
''')

    def test_document_response_labels_match_frozen_policy(self):
        from pathlib import Path
        document = (Path(__file__).resolve().parents[1] / 'docs/governance-risk.md').read_text()
        self.assertIn('`正常/注意/高关注/极高风险/未评估`', document)
        self.assertNotIn('`正常/关注/高风险/重大风险/未评估`', document)

    def test_extreme_finite_inputs_and_strict_boundary_sides_remain_safe(self):
        for n, d, level in [(5e-324, 5e-324, 'high'), (5e-324, 1e308, 'normal'),
                            (1e308, 1e308, 'high'), (1.1299999999999997, 11.3, 'normal'),
                            (1.1300000000000001, 11.3, 'watch'),
                            (10 ** 307 - 1, 10 ** 308, 'normal'),
                            (10 ** 307, 10 ** 308, 'watch')]:
            with self.subTest(numerator=n, denominator=d):
                data = evidence()
                data['related_sales']['ratio'].update(numerator=n, denominator=d)
                result = build_governance_risk(80, data, AS_OF)
                self.assertEqual(result['items'][1]['level'], level)
                json.dumps(result, allow_nan=False)
        # Unbounded overdue/revenue must not overflow during a red-rule comparison.
        result = build_governance_risk(80, overdue_evidence(5e-324, 1e308, 5e-324), AS_OF)
        self.assertEqual(result['items'][1]['level'], 'critical')
        json.dumps(result, allow_nan=False)

    def test_exact_boundary_does_not_clear_red_without_valid_resolution(self):
        for status in (None, 'resolved'):
            data = overdue_evidence()
            data['related_sales']['rules']['related_overdue']['status'] = status
            result = build_governance_risk(80, data, AS_OF)
            self.assertEqual(result['items'][1]['level'], 'critical')
            self.assertEqual(result['items'][1]['deduction'], 20)
            self.assertFalse(result['complete'])
            self.assertIsNone(result['adjusted_score'])
            self.assertEqual(result['original_score'], 80)
            json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
