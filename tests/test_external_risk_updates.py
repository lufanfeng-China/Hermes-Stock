import unittest
import tempfile
from pathlib import Path
import importlib


class ExternalRiskTests(unittest.TestCase):
    def test_missing_status_is_read_only(self):
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'absent'
            status = m.load_external_risk_status(root)
            self.assertEqual(set(status), {'company_pledge', 'related_transactions'})
            self.assertFalse(status['company_pledge']['available'])
            self.assertFalse(root.exists())

    def archive(self, root, dataset='company_pledge', rows=None):
        import json, hashlib, gzip, csv
        rows = rows if rows is not None else [
            {'SECURITY_CODE': '000001', 'SECUCODE': '000001.SZ', 'TRADE_DATE': '2026-10-23', 'PLEDGE_RATIO': None},
            {'SECURITY_CODE': '000002', 'SECUCODE': '000002.SZ', 'TRADE_DATE': '2026-09-01', 'PLEDGE_RATIO': 1.2}]
        root.mkdir(); (root / 'raw').mkdir()
        (root / 'raw/page_001.json').write_text(json.dumps({'success': True, 'result': {'count': len(rows), 'pages': 1, 'data': rows}}))
        (root / 'verification.json').write_text(json.dumps({'passed': True, 'downloaded_rows': len(rows), 'downloaded_at': '2026-10-26T12:00:00+08:00'}))
        if dataset == 'company_pledge':
            (root / 'company_pledge_latest.json').write_text(json.dumps({'data': rows, 'source_count': len(rows)}))
        else:
            (root / 'config.json').write_text(json.dumps({'announcement_end': '2026-10-24', 'started_at': '2026-10-26T12:00:00+08:00'}))
            with gzip.open(root / 'related_transactions_2026.jsonl.gz', 'wt') as f:
                for row in rows: f.write(json.dumps(row) + '\n')
        files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        (root / 'sha256_manifest.json').write_text(json.dumps(files))
        return root

    def test_import_publishes_partitioned_project_snapshot(self):
        import json
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'project'; source = self.archive(Path(td) / 'source')
            status = m.update_external_risk('company_pledge', root=root, import_from=source)
            self.assertTrue(status['available'])
            self.assertEqual((status['row_count'], status['company_count']), (2, 2))
            self.assertEqual((status['latest_date_rows'], status['older_date_rows']), (1, 1))
            self.assertEqual(status['data_date'], '2026-10-23')
            self.assertEqual(status['acquisition_mode'], 'import')
            snapshot = Path(status['snapshot_path'])
            self.assertTrue((snapshot / 'by_date/2026-09-01.jsonl').exists())
            self.assertTrue(json.loads((snapshot / 'metadata.json').read_text())['complete'])
            self.assertEqual(m.load_external_risk_status(root)['company_pledge']['row_count'], 2)

    def test_final_progress_failure_cannot_mutate_committed_snapshot(self):
        import json
        m = importlib.import_module('app.data.external_risk_updates')
        for error_type in [BrokenPipeError, RuntimeError]:
            for dataset in ['company_pledge', 'related_transactions']:
                with self.subTest(error=error_type.__name__, dataset=dataset), tempfile.TemporaryDirectory() as td:
                    rows = None if dataset == 'company_pledge' else [{'SECURITY_CODE': '000001', 'NOTICE_DATE': '2026-10-24'}]
                    source = self.archive(Path(td)/'source', dataset, rows)
                    root = Path(td)/'project'
                    committed = {}
                    messages = []
                    def progress(message):
                        messages.append(message)
                        if message.startswith('[3/3] 完成'):
                            current = root/dataset/'current.json'
                            run = Path(json.loads(current.read_text())['snapshot_path'])
                            for path in [current, root/dataset/'last_attempt.json', *[p for p in run.rglob('*') if p.is_file()]]:
                                committed[path] = path.read_bytes()
                            raise error_type('final progress output failed')
                    caught = result = None
                    try:
                        result = m.update_external_risk(dataset, root=root, import_from=source, progress=progress)
                    except Exception as exc:
                        caught = exc
                    self.assertTrue(committed, 'callback must run after current was published')
                    for path, content in committed.items():
                        self.assertEqual(path.read_bytes(), content, str(path))
                    self.assertIsNone(caught, 'post-commit logging is not a failed update')
                    current = json.loads((root/dataset/'current.json').read_text())
                    run = Path(current['snapshot_path'])
                    self.assertEqual(result, current)
                    self.assertEqual(current, json.loads((run/'metadata.json').read_text()))
                    self.assertTrue(current['complete'])
                    self.assertIsNone(current['error'])
                    manifest = json.loads((run/'sha256_manifest.json').read_text())
                    self.assertTrue(all(m._hash(run/name) == digest for name, digest in manifest.items()))
                    self.assertFalse(any(message.startswith('[3/3] 失败') for message in messages))

    def test_failed_import_keeps_current_and_reports_error(self):
        import json
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'project'; source = self.archive(Path(td) / 'source')
            m.update_external_risk('company_pledge', root=root, import_from=source)
            current = (root / 'company_pledge/current.json').read_bytes()
            (source / 'company_pledge_latest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'hash'):
                m.update_external_risk('company_pledge', root=root, import_from=source)
            self.assertEqual(current, (root / 'company_pledge/current.json').read_bytes())
            status = m.load_external_risk_status(root)['company_pledge']
            self.assertTrue(status['available']); self.assertIn('hash', status['error'])

    def test_related_import_preserves_duplicates_decimal_null_and_scope(self):
        import gzip, json
        m = importlib.import_module('app.data.external_risk_updates')
        row = {'SECURITY_CODE': '000001', 'NOTICE_DATE': '2026-10-24', 'TRADE_AMT': '0.123456789', 'OPERATE_INCOME': '123.45', 'NETPROFIT': None, 'EID': 'same'}
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td) / 'source', 'related_transactions', [row, row])
            status = m.update_external_risk('related_transactions', root=Path(td)/'project', import_from=source)
            with gzip.open(Path(status['snapshot_path']) / 'data.jsonl.gz', 'rt') as f: rows = [json.loads(x) for x in f]
            self.assertEqual(len(rows), 2); self.assertEqual(rows[0]['_AMOUNT_UNITS'], '1234.567890000')
            self.assertEqual(rows[0]['OPERATE_INCOME'], '123.45'); self.assertIsNone(rows[0]['NETPROFIT'])
            self.assertEqual(status['exact_duplicate_rows_preserved'], 1)
            self.assertIn('公告', status['source_scope'])

    def test_related_import_rejects_outside_announcement_year(self):
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td)/'source', 'related_transactions', [{'SECURITY_CODE': '000001', 'NOTICE_DATE': '2025-12-31'}])
            with self.assertRaisesRegex(ValueError, 'announcement'):
                m.update_external_risk('related_transactions', root=Path(td)/'root', import_from=source)

    def test_related_archive_rejects_invalid_or_unhashed_cutoff(self):
        import json
        m = importlib.import_module('app.data.external_risk_updates')
        for cutoff in ['2027-01-01', '2025-12-31', '2026-02-30', '2026-13-01',
                       '2026-1-01', '', None, '2026-10-24T00:00:00', 'unhashed']:
            with self.subTest(cutoff=cutoff), tempfile.TemporaryDirectory() as td:
                source = self.archive(Path(td)/'source', 'related_transactions',
                                      [{'SECURITY_CODE': '000001', 'NOTICE_DATE': '2026-01-01'}])
                config = source/'config.json'
                config.write_text(json.dumps({'announcement_end': '2026-10-24' if cutoff == 'unhashed' else cutoff}))
                manifest_path = source/'sha256_manifest.json'
                manifest = json.loads(manifest_path.read_text())
                if cutoff == 'unhashed':
                    del manifest['config.json']
                else:
                    manifest['config.json'] = m._hash(config)
                manifest_path.write_text(json.dumps(manifest))
                root = Path(td)/'project'
                with self.assertRaises(ValueError):
                    m.update_external_risk('related_transactions', root=root, import_from=source, progress=lambda _: None)
                self.assertFalse((root/'related_transactions/current.json').exists())

    def test_related_export_has_fixed_year_end_even_with_later_cutoff(self):
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, 'announcement'):
                m._export(Path(td), 'related_transactions',
                          [{'SECURITY_CODE': '000001', 'NOTICE_DATE': '2027-01-01'}],
                          {'announcement_end': '2027-01-01'}, lambda _: None)

    def test_related_archive_accepts_real_year_end_and_hashes_config_evidence(self):
        import json
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td)/'source', 'related_transactions',
                                  [{'SECURITY_CODE': '000001', 'NOTICE_DATE': '2026-12-31'}])
            config = source/'config.json'
            config.write_text(json.dumps({'announcement_end': '2026-12-31'}))
            manifest_path = source/'sha256_manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['config.json'] = m._hash(config)
            manifest_path.write_text(json.dumps(manifest))
            result = m.update_external_risk('related_transactions', root=Path(td)/'project', import_from=source, progress=lambda _: None)
            run = Path(result['snapshot_path'])
            output_manifest = json.loads((run/'sha256_manifest.json').read_text())
            self.assertEqual(result['data_date'], '2026-12-31')
            self.assertEqual(output_manifest['import_evidence/config.json'], m._hash(config))

    def test_network_pagination_tail_and_first_page_recheck(self):
        m = importlib.import_module('app.data.external_risk_updates')
        rows = [{'SECURITY_CODE': f'{n:06d}', 'TRADE_DATE': '2026-10-23'} for n in range(501)]
        calls = []
        def fetch(params):
            calls.append(dict(params)); n = int(params['pageNumber'])
            return {'success': True, 'result': {'count': 501, 'pages': 2, 'data': rows[(n-1)*500:n*500]}}
        with tempfile.TemporaryDirectory() as td:
            result = m.update_external_risk('company_pledge', root=td, fetcher=fetch)
            self.assertEqual(result['row_count'], 501)
            self.assertEqual([p['pageNumber'] for p in calls], ['1', '2', '1'])
            self.assertTrue(all(p['pageSize'] == '500' for p in calls))
            self.assertEqual(calls[0]['reportName'], 'RPT_CSDC_LIST_NEWEST')

    def test_bad_network_pages_never_publish(self):
        m = importlib.import_module('app.data.external_risk_updates')
        row = {'SECURITY_CODE': '000001', 'TRADE_DATE': '2026-10-23'}
        for case in ['empty', 'tail', 'count', 'first_page']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                calls = []
                def fetch(params):
                    calls.append(params)
                    count, pages, data = 1, 1, [row]
                    if case == 'empty': count, pages, data = 0, 0, []
                    if case == 'tail': count = 2
                    if len(calls) > 1 and case == 'count': count = 2
                    if len(calls) > 1 and case == 'first_page': data = [dict(row, TRADE_DATE='2026-10-24')]
                    return {'success': True, 'result': {'count': count, 'pages': pages, 'data': data}}
                with self.assertRaises(ValueError): m.update_external_risk('company_pledge', root=td, fetcher=fetch)
                self.assertFalse((Path(td)/'company_pledge/current.json').exists())

    def test_network_related_freezes_2026_announcement_scope(self):
        m = importlib.import_module('app.data.external_risk_updates')
        calls = []
        def fetch(params):
            calls.append(dict(params))
            return {'success': True, 'result': {'count': 1, 'pages': 1, 'data': [{'SECURITY_CODE': '000001', 'NOTICE_DATE': '2026-10-24', 'TRADE_AMT': None}]}}
        with tempfile.TemporaryDirectory() as td:
            m.update_external_risk('related_transactions', root=td, fetcher=fetch)
        self.assertEqual(len(calls), 3)
        self.assertIn("NOTICE_DATE<='2026-10-24'", calls[1]['filter'])
        self.assertIn("NOTICE_DATE>='2026-01-01'", calls[1]['filter'])
        self.assertIn('EID,RELATED_PARTY', calls[1]['sortColumns'])

    def test_same_dataset_process_lock(self):
        import fcntl
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)/'company_pledge'; base.mkdir()
            with (base/'.update.lock').open('a') as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    m.update_external_risk('company_pledge', root=td)

    def test_http_client_rate_limits_retries_and_timeouts(self):
        from unittest.mock import patch
        import io
        m = importlib.import_module('app.data.external_risk_updates')
        class Response(io.BytesIO):
            status = 200
        clock = [100.0]; starts = []; timeouts = []
        def sleep(n): clock[0] += n
        def opener(req, timeout):
            starts.append(clock[0]); timeouts.append(timeout)
            if len(starts) == 1: raise OSError('temporary')
            return Response(b'{"success":true,"result":{"count":1,"pages":1,"data":[]}}')
        with patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(m.time, 'sleep', side_effect=sleep), patch.object(m.urllib.request, 'urlopen', side_effect=opener):
            client = m.PublicAPIClient()
            client({'x': 'y'}); client({'x': 'z'})
        self.assertTrue(all(b-a >= 2 for a,b in zip(starts, starts[1:])))
        self.assertTrue(all(0 < t <= 60 for t in timeouts))

    def test_cli_import_uses_root(self):
        import subprocess, sys, json
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td)/'source')
            proc = subprocess.run([sys.executable, 'scripts/update_external_risk.py', '--dataset', 'company_pledge', '--import-from', str(source), '--root', str(Path(td)/'project')], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('[3/3] 完成', proc.stdout)
            self.assertTrue((Path(td)/'project/company_pledge/current.json').exists())

    def test_import_rejects_csv_value_tampering_even_when_hash_column_matches(self):
        import csv, json, hashlib
        m = importlib.import_module('app.data.external_risk_updates')
        row = {'SECURITY_CODE': '000001', 'NOTICE_DATE': '2026-10-24', 'TRADE_AMT': '1', 'OPERATE_INCOME': '20'}
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td)/'source', 'related_transactions', [row])
            csvpath = source/'关联交易明细_2026公告.csv'
            with csvpath.open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['股票代码', '公告日期', '交易金额原值_万原币', '交易金额换算值_元原币', '参考营业收入_元_期间待核', '整行内容SHA256'])
                writer.writeheader(); writer.writerow({'股票代码': '000001', '公告日期': '2026-10-24', '交易金额原值_万原币': '1', '交易金额换算值_元原币': '10000', '参考营业收入_元_期间待核': '999', '整行内容SHA256': m._digest(row)})
            manifest = json.loads((source/'sha256_manifest.json').read_text())
            manifest[csvpath.name] = hashlib.sha256(csvpath.read_bytes()).hexdigest()
            (source/'sha256_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'CSV.*field'):
                m.update_external_risk('related_transactions', root=Path(td)/'root', import_from=source)

    def test_import_primary_duplicate_counts_must_match_raw(self):
        import gzip, json, hashlib
        m = importlib.import_module('app.data.external_risk_updates')
        a = {'SECURITY_CODE': '000001', 'NOTICE_DATE': '2026-10-24', 'EID': 'a'}
        b = dict(a, EID='b')
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td)/'source', 'related_transactions', [a,a,b])
            path = source/'related_transactions_2026.jsonl.gz'
            with gzip.open(path, 'wt') as f:
                for row in [a,b,b]: f.write(json.dumps(row)+'\n')
            manifest = json.loads((source/'sha256_manifest.json').read_text()); manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            (source/'sha256_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'multiplicity'):
                m.update_external_risk('related_transactions', root=Path(td)/'root', import_from=source)

    def test_export_readback_checks_csv_fields_not_just_hash_column(self):
        from unittest.mock import patch
        import csv
        m = importlib.import_module('app.data.external_risk_updates')
        original = csv.DictWriter
        class CorruptWriter(original):
            def writerow(self, row):
                if row.get('SECURITY_CODE') == '000001':
                    row = dict(row, SECURITY_CODE='999999')
                return super().writerow(row)
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td)/'source')
            with patch.object(m.csv, 'DictWriter', CorruptWriter):
                with self.assertRaisesRegex(ValueError, 'CSV.*fields'):
                    m.update_external_risk('company_pledge', root=Path(td)/'root', import_from=source)

    def test_import_rejects_absolute_manifest_paths(self):
        import json, hashlib
        m = importlib.import_module('app.data.external_risk_updates')
        with tempfile.TemporaryDirectory() as td:
            source = self.archive(Path(td)/'source')
            path = source/'verification.json'
            manifest = json.loads((source/'sha256_manifest.json').read_text())
            manifest[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            (source/'sha256_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                m.update_external_risk('company_pledge', root=Path(td)/'root', import_from=source)


if __name__ == '__main__':
    unittest.main()
