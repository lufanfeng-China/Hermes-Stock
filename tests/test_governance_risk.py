"""Synthetic evidence only; no production fixtures or external requests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from app.financial.governance_risk import build_governance_risk, load_governance_evidence

AS_OF = '2026-10-26'


def source():
    return {'url': 'https://example.invalid/synthetic', 'title': '合成测试公告', 'date': '2026-04-20'}


def ratio(code, value=20):
    return {'numerator': value, 'denominator': 100, 'metric': code,
            'subject': '控股股东甲' if code == 'major_shareholder_pledge' else '测试公司',
            'scope': 'major_shareholder' if code == 'major_shareholder_pledge' else 'consolidated',
            'period_end': '2025-12-31', 'period_type': 'annual',
            'currency': 'CNY' if code == 'related_sales' else 'shares', 'unit': '元' if code == 'related_sales' else '股',
            'numerator_basis': 'pledged_shares' if code == 'major_shareholder_pledge' else 'related_sales',
            'denominator_basis': 'held_shares' if code == 'major_shareholder_pledge' else 'operating_revenue',
            'numerator_currency': 'CNY' if code == 'related_sales' else 'shares',
            'denominator_currency': 'CNY' if code == 'related_sales' else 'shares',
            'numerator_unit': '元' if code == 'related_sales' else '股',
            'denominator_unit': '元' if code == 'related_sales' else '股',
            'complete': True, 'sources': [source()]}


def rule(event=False, **kw):
    return dict({'evaluated': True, 'complete': True, 'event_present': event,
                 'as_of': '2026-10-26', 'subject': '测试公司', 'scope': 'consolidated', 'sources': [source()]}, **kw)


def evidence(pledge=20, sales=5):
    return {'major_shareholder_pledge': {'ratio': ratio('major_shareholder_pledge', pledge),
                'rules': {'pledge_default': rule(subject='控股股东甲', scope='major_shareholder'),
                          'pledge_forced_disposal': rule(subject='控股股东甲', scope='major_shareholder')}},
            'related_sales': {'ratio': ratio('related_sales', sales),
                'rules': {'related_overdue': rule(), 'related_misstatement': rule()}}}


class GovernanceRiskTests(unittest.TestCase):
    def test_ratio_thresholds_complete_score_and_immutability(self):
        for p, s, pl, sl in [(0, 0, 'normal', 'normal'), (29.999, 9.999, 'normal', 'normal'),
                              (30, 10, 'watch', 'watch'), (49.999, 29.999, 'watch', 'watch'),
                              (50, 30, 'high', 'high'), (80, 50, 'high', 'high'), (100, 100, 'high', 'high')]:
            with self.subTest(p=p, s=s):
                data = evidence(p, s)
                before = copy.deepcopy(data)
                result = build_governance_risk(80, data, AS_OF)
                self.assertTrue(result['complete'])
                self.assertEqual([i['level'] for i in result['items']], [pl, sl])
                self.assertEqual(result['adjusted_score'], 80 - sum(i['deduction'] for i in result['items']))
                self.assertEqual(data, before)
                self.assertEqual(result['items'][0]['ratio_pct'], p)
                if p >= 80:
                    self.assertTrue(result['items'][0]['highly_pledged'])
                if s >= 50:
                    self.assertTrue(result['items'][1]['high_dependence'])
        self.assertEqual(build_governance_risk(0, evidence(), AS_OF)['adjusted_score'], 0)

    def test_invalid_ratios_are_unavailable_not_zero(self):
        invalid = [('numerator', True), ('numerator', -1), ('numerator', '20'),
                   ('numerator', float('nan')), ('numerator', float('inf')), ('numerator', 101),
                   ('denominator', 0), ('denominator', -1), ('denominator', False),
                   ('complete', False), ('complete', 1), ('sources', []), ('subject', ''),
                   ('scope', 'overall'), ('scope', 'mixed'), ('metric', 'overall'),
                   ('numerator_basis', 'overall'), ('denominator_basis', 'mixed'),
                   ('period_end', '2027-12-31'), ('period_end', 'bad'), ('stale', True),
                   ('numerator_currency', 'USD'), ('denominator_unit', '万元')]
        for code in ['major_shareholder_pledge', 'related_sales']:
            for key, value in invalid:
                with self.subTest(code=code, key=key, value=value):
                    data = evidence()
                    data[code]['ratio'][key] = value
                    result = build_governance_risk(80, data, AS_OF)
                    item = next(i for i in result['items'] if i['code'] == code)
                    self.assertEqual(item['level'], 'unavailable')
                    self.assertIsNone(item['ratio_pct'])
                    self.assertIsNone(result['adjusted_score'])
        for field, value in [('period_type', 'quarter'), ('period_end', '2025-09-30')]:
            data = evidence()
            data['related_sales']['ratio'][field] = value
            self.assertFalse(build_governance_risk(80, data, AS_OF)['complete'])
        for bad_source in [{}, {'url': 'javascript:alert(1)', 'title': 'x', 'date': '2026-01-01'},
                           dict(source(), date='2027-01-01'), dict(source(), title='')]:
            data = evidence()
            data['related_sales']['ratio']['sources'] = [bad_source]
            self.assertIsNone(build_governance_risk(80, data, AS_OF)['items'][1]['ratio_pct'])

    def test_invalid_score_and_malformed_input_fail_closed(self):
        for value in [None, True, '80', -1, 101, float('nan'), float('inf'), {}, []]:
            with self.subTest(value=value):
                result = build_governance_risk(value, evidence(), AS_OF)
                self.assertFalse(result['complete'])
                self.assertIsNone(result['adjusted_score'])
        for data in [[], 'bad', {'related_sales': []}, {'related_sales': {'ratio': []}}]:
            self.assertIsNone(build_governance_risk(80, data, AS_OF)['adjusted_score'])
        self.assertIsNone(build_governance_risk(80, evidence(), 'invalid')['adjusted_score'])

    def test_rule_coverage_requires_explicit_valid_evidence(self):
        for code, name in [('major_shareholder_pledge', 'pledge_default'),
                           ('major_shareholder_pledge', 'pledge_forced_disposal'),
                           ('related_sales', 'related_overdue'), ('related_sales', 'related_misstatement')]:
            for change in [None, {'evaluated': False}, {'evaluated': 1}, {'complete': False},
                           {'sources': []}, {'as_of': '2027-01-01'}, {'event_present': None},
                           {'subject': ''}, {'scope': 'mixed'}, {'stale': True}]:
                with self.subTest(code=code, name=name, change=change):
                    data = evidence(60, 40)
                    if change is None:
                        del data[code]['rules'][name]
                    else:
                        data[code]['rules'][name].update(change)
                    result = build_governance_risk(80, data, AS_OF)
                    item = next(i for i in result['items'] if i['code'] == code)
                    self.assertEqual(item['level'], 'high')
                    self.assertFalse(item['complete'])
                    self.assertIn('升级', item['reason'])
                    self.assertIsNone(result['adjusted_score'])
                    r = next(r for r in item['rule_results'] if r['code'] == name)
                    self.assertFalse(r['evaluated'])

    def test_pledge_default_requires_announced_unresolved_financing_default(self):
        event = rule(True, subject='控股股东甲', scope='major_shareholder', document_kind='announcement',
                     financing='pledge', default_confirmed=True, status='unresolved')
        data = evidence()
        data['major_shareholder_pledge']['rules']['pledge_default'] = event
        result = build_governance_risk(80, data, AS_OF)
        self.assertTrue(result['complete'])
        self.assertEqual(result['items'][0]['level'], 'critical')
        self.assertEqual(result['items'][0]['color'], 'red')
        self.assertEqual(result['items'][0]['deduction'], 20)
        self.assertEqual(result['adjusted_score'], 60)
        for key, value in [('document_kind', 'media'), ('financing', 'other'), ('default_confirmed', False)]:
            changed = copy.deepcopy(data)
            changed['major_shareholder_pledge']['rules']['pledge_default'][key] = value
            self.assertNotEqual(build_governance_risk(80, changed, AS_OF)['items'][0]['level'], 'critical')
        for status in ['resolved', None]:
            changed = copy.deepcopy(data)
            changed['major_shareholder_pledge']['rules']['pledge_default']['status'] = status
            result = build_governance_risk(80, changed, AS_OF)
            self.assertEqual(result['items'][0]['level'], 'critical')
            self.assertFalse(result['complete'])
        event.update(status='resolved', resolution_sources=[source()])
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][0]['level'], 'normal')
        event.update(status='unresolved')
        data['major_shareholder_pledge']['ratio'] = None
        result = build_governance_risk(80, data, AS_OF)
        self.assertEqual(result['items'][0]['level'], 'critical')
        self.assertIsNone(result['items'][0]['ratio_pct'])
        self.assertIsNone(result['adjusted_score'])

    def test_forced_disposal_requires_all_announcement_conditions(self):
        event = rule(True, subject='控股股东甲', scope='major_shareholder', document_kind='announcement',
                     financing='pledge', disposal_started=True, control_risk_explicit=True,
                     disposal_shares=12345, status='unresolved')
        data = evidence(90, 5)
        data['major_shareholder_pledge']['rules']['pledge_forced_disposal'] = event
        result = build_governance_risk(80, data, AS_OF)
        self.assertEqual(result['items'][0]['level'], 'critical')
        self.assertEqual(result['adjusted_score'], 60)
        for key, value in [('document_kind', 'investigation'), ('financing', 'other'),
                           ('disposal_started', False), ('control_risk_explicit', False),
                           ('disposal_shares', 0), ('disposal_shares', -1), ('disposal_shares', True),
                           ('disposal_shares', '100'), ('disposal_shares', float('inf'))]:
            changed = copy.deepcopy(data)
            changed['major_shareholder_pledge']['rules']['pledge_forced_disposal'][key] = value
            result = build_governance_risk(80, changed, AS_OF)
            self.assertEqual(result['items'][0]['level'], 'high')
            self.assertIsNone(result['adjusted_score'])
        event.update(status='resolved', resolution_sources=[source()])
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][0]['level'], 'high')
        event['resolution_sources'] = [dict(source(), date='2027-01-01')]
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][0]['level'], 'critical')
        event.update(status='unresolved')
        data['major_shareholder_pledge']['rules']['pledge_default'] = rule(
            True, subject='控股股东甲', scope='major_shareholder', document_kind='announcement',
            financing='pledge', default_confirmed=True, status='unresolved')
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][0]['deduction'], 20)

    def test_related_overdue_requires_same_annual_revenue_and_true_overdue(self):
        receivables = ratio('related_sales', 10)
        receivables.update(metric='related_trade_receivables_overdue_gt_180',
                           numerator_basis='related_trade_receivables_overdue_gt_180',
                           days_basis='overdue', days_operator='>', days_threshold=180)
        event = rule(True, receivables=receivables, status='unresolved')
        data = evidence(20, 50)
        data['related_sales']['rules']['related_overdue'] = event
        result = build_governance_risk(80, data, AS_OF)
        self.assertTrue(result['complete'])
        self.assertEqual(result['items'][1]['level'], 'critical')
        self.assertEqual(result['adjusted_score'], 60)
        for key, value in [('period_end', '2024-12-31'), ('period_type', 'quarter'),
                           ('days_basis', 'aging'), ('days_operator', '>='), ('days_threshold', 181),
                           ('currency', 'USD'), ('unit', '万元'), ('complete', False), ('scope', 'parent'),
                           ('subject', '另一公司'), ('denominator', 200), ('numerator', -1),
                           ('metric', 'mixed'), ('sources', [])]:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(data)
                changed['related_sales']['rules']['related_overdue']['receivables'][key] = value
                result = build_governance_risk(80, changed, AS_OF)
                self.assertEqual(result['items'][1]['level'], 'high')
                self.assertFalse(result['complete'])
        for sales, overdue in [(49.999, 10), (50, 9.999), (50, 0)]:
            changed = copy.deepcopy(data)
            changed['related_sales']['ratio']['numerator'] = sales
            changed['related_sales']['rules']['related_overdue']['receivables']['numerator'] = overdue
            result = build_governance_risk(80, changed, AS_OF)
            self.assertEqual(result['items'][1]['level'], 'high')
            self.assertTrue(result['complete'])
        receivables['numerator'] = 150  # receivables/revenue can exceed 100 percent
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][1]['level'], 'critical')
        event.update(status='resolved', resolution_sources=[source()])
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][1]['level'], 'high')
        del event['resolution_sources']
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][1]['level'], 'critical')

    def test_related_misstatement_requires_formal_material_related_revenue_finding(self):
        event = rule(True, document_kind='regulatory_decision', material=True,
                     related_revenue=True, finding='false_revenue', status='unresolved')
        data = evidence()
        data['related_sales']['rules']['related_misstatement'] = event
        for kind in ['regulatory_decision', 'audit_report']:
            for finding in ['false_revenue', 'improper_recognition']:
                event.update(document_kind=kind, finding=finding)
                result = build_governance_risk(80, data, AS_OF)
                self.assertTrue(result['complete'])
                self.assertEqual(result['items'][1]['level'], 'critical')
                self.assertEqual(result['adjusted_score'], 60)
        for key, value in [('document_kind', 'inquiry'), ('document_kind', 'investigation'),
                           ('document_kind', 'media'), ('material', False), ('related_revenue', False),
                           ('finding', 'suspected'), ('material', 1)]:
            changed = copy.deepcopy(data)
            changed['related_sales']['rules']['related_misstatement'][key] = value
            self.assertNotEqual(build_governance_risk(80, changed, AS_OF)['items'][1]['level'], 'critical')
        event.update(status='resolved')
        result = build_governance_risk(80, data, AS_OF)
        self.assertEqual(result['items'][1]['level'], 'critical')
        self.assertIsNone(result['adjusted_score'])
        event['resolution_sources'] = [source()]
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][1]['level'], 'normal')
        event.update(status='unresolved')
        data['related_sales']['ratio'] = None
        result = build_governance_risk(80, data, AS_OF)
        self.assertEqual(result['items'][1]['level'], 'critical')
        self.assertIsNone(result['adjusted_score'])

    def test_loader_is_read_only_and_rejects_bad_files_and_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / 'data/external_risk/governance_evidence'
            self.assertIsNone(load_governance_evidence('600000', root))
            self.assertFalse(directory.exists())
            directory.mkdir(parents=True)
            path = directory / '600000.json'
            data = evidence()
            path.write_text(json.dumps(data), encoding='utf-8')
            before = path.read_bytes()
            self.assertEqual(load_governance_evidence('600000', root), data)
            self.assertEqual(path.read_bytes(), before)
            for symbol in ['../600000', '600000.SH', '', None, 600000, '１２３４５６']:
                self.assertIsNone(load_governance_evidence(symbol, root))
            for broken in ['bad', '[]', 'null', '{"x":NaN}', '{"symbol":"000001"}', '\udcff']:
                path.write_bytes(broken.encode('utf-8', errors='surrogatepass'))
                self.assertIsNone(load_governance_evidence('600000', root))

    def test_evidence_identity_period_and_provenance_are_not_silently_mixed(self):
        for code in ['major_shareholder_pledge', 'related_sales']:
            for key, value in [('source_basis', 'overall'), ('source_basis', 'mixed'),
                               ('numerator_period_end', '2024-12-31'), ('denominator_period_end', '2024-12-31'),
                               ('numerator_subject', '另一主体'), ('denominator_scope', 'parent'),
                               ('numerator', 10 ** 400)]:
                data = evidence()
                data[code]['ratio'][key] = value
                self.assertIsNone(build_governance_risk(80, data, AS_OF)['items'][0 if code.startswith('major') else 1]['ratio_pct'])
        data = evidence()
        data['related_sales']['ratio']['sources'] = [dict(source(), date='2025-01-01')]
        self.assertIsNone(build_governance_risk(80, data, AS_OF)['items'][1]['ratio_pct'])
        data = evidence()
        data['major_shareholder_pledge']['rules']['pledge_default'] = rule(
            True, subject='另一股东', scope='major_shareholder', document_kind='announcement',
            financing='pledge', default_confirmed=True, status='unresolved')
        result = build_governance_risk(80, data, AS_OF)
        self.assertNotEqual(result['items'][0]['level'], 'critical')
        self.assertFalse(result['complete'])
        data = evidence()
        data['related_sales']['rules']['related_misstatement']['as_of'] = '2025-01-01'
        self.assertFalse(build_governance_risk(80, data, AS_OF)['complete'])

    def test_output_contains_auditable_details_and_valid_sources_only(self):
        data = evidence()
        result = build_governance_risk(80, data, AS_OF)
        self.assertEqual(result['items'][1]['details']['numerator'], 5)
        self.assertEqual(result['items'][1]['details']['denominator'], 100)
        self.assertEqual(result['items'][1]['details']['scope'], 'consolidated')
        self.assertEqual(result['items'][1]['details']['period_end'], '2025-12-31')
        data['related_sales']['ratio']['sources'] = [{'url': 'javascript:bad'}]
        self.assertTrue(all(s['url'].startswith('https://') for s in
                            build_governance_risk(80, data, AS_OF)['items'][1]['evidence']))

    def test_decimal_boundaries_and_red_evidence_are_auditable(self):
        data = evidence()
        data['related_sales']['ratio'].update(numerator=0.3, denominator=3)
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][1]['level'], 'watch')
        data['major_shareholder_pledge']['rules']['pledge_default'] = rule(
            True, subject='控股股东甲', scope='major_shareholder', document_kind='announcement',
            financing='pledge', default_confirmed=True, status='unresolved')
        data['major_shareholder_pledge']['ratio'] = None
        item = build_governance_risk(80, data, AS_OF)['items'][0]
        self.assertTrue(item['evidence'])
        self.assertEqual(item['rule_results'][0]['details']['status'], 'unresolved')
        self.assertIn('未解除', item['reason'])
        event = data['major_shareholder_pledge']['rules']['pledge_default']
        event.update(status='resolved', resolution_sources=[dict(source(), date='2025-01-01')])
        self.assertEqual(build_governance_risk(80, data, AS_OF)['items'][0]['level'], 'critical')

    def test_missing_evidence_never_means_normal(self):
        result = build_governance_risk(80, as_of=AS_OF)
        self.assertIsNone(result['adjusted_score'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['original_score'], 80)
        self.assertEqual(len(result['items']), 2)
        for item in result['items']:
            self.assertEqual(item['level'], 'unavailable')
            self.assertEqual(item['color'], 'gray')
            self.assertIsNone(item['deduction'])
            self.assertFalse(item['complete'])
            self.assertTrue(item['reason'])
            self.assertEqual(len(item['rule_results']), 2)
            self.assertTrue(all(not r['evaluated'] for r in item['rule_results']))


if __name__ == '__main__':
    unittest.main()
