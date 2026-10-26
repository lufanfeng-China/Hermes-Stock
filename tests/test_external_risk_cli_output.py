"""Offline CLI regressions; all archives are synthetic TEST fixtures, not market data."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

if __package__:
    from . import test_external_risk_updates as archive_fixtures
else:
    import test_external_risk_updates as archive_fixtures


REPO = Path(__file__).resolve().parents[1]
# Run the actual CLI/core in a fresh interpreter so shutdown-time flush is tested.
DRIVER = r'''
import builtins
import hashlib
import json
import os
from pathlib import Path
import sys
from scripts import update_external_risk as cli

mode, root, source, evidence = sys.argv[1:]
root, evidence = Path(root), Path(evidence)
original_update = cli.update_external_risk
original_print = builtins.print
reader = None
if mode == 'broken_pipe':
    reader, writer = os.pipe()
    os.dup2(writer, sys.stdout.fileno())
    os.close(writer)

def update(*args, **kwargs):
    original_progress = kwargs['progress']
    def progress(line):
        if line.startswith('[3/3] 完成'):
            # Capture ALL committed bytes before either post-commit notification.
            committed = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in root.rglob('*') if p.is_file()}
            evidence.write_text(json.dumps(committed))
            if mode == 'broken_pipe':
                # Earlier stages really wrote to a live pipe, not a mock stream.
                earlier = os.read(reader, 65536).decode('utf-8')
                evidence.with_suffix('.progress').write_text(earlier)
                os.close(reader)
            elif mode == 'os_error':
                def fail_json(*values, **options):
                    if values and isinstance(values[0], str) and values[0].startswith('{'):
                        raise OSError('synthetic TEST final JSON output failure')
                    return original_print(*values, **options)
                builtins.print = fail_json
        return original_progress(line)
    kwargs['progress'] = progress
    if mode == 'download_failure':
        import app.data.external_risk_updates as core
        def fail_download(*args, **kwargs):
            raise OSError('synthetic TEST download failure')
        core._download = fail_download
    return original_update(*args, **kwargs)
cli.update_external_risk = update
argv = ['--dataset', 'company_pledge', '--root', str(root)]
if mode != 'download_failure':
    argv += ['--import-from', source]
raise SystemExit(cli.main(argv))
'''


class ExternalRiskCliOutputTests(unittest.TestCase):
    def run_cli(self, directory, mode):
        root = directory / 'TEST-published'
        source = directory / 'TEST-synthetic-archive'
        if not source.exists():
            archive_fixtures.ExternalRiskTests().archive(source)
        evidence = directory / ('TEST-evidence-' + mode + '.json')
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run(
            [sys.executable, '-B', '-c', DRIVER, mode, str(root), str(source), str(evidence)],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
        )
        return result, root, evidence

    def assert_committed_unchanged(self, root, evidence):
        committed = json.loads(evidence.read_text())
        actual = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob('*') if p.is_file()}
        self.assertEqual(actual, committed)
        current = json.loads((root / 'company_pledge/current.json').read_text())
        run = Path(current['snapshot_path'])
        self.assertEqual(current, json.loads((run / 'metadata.json').read_text()))
        self.assertEqual(current, json.loads((root / 'company_pledge/last_attempt.json').read_text()))
        self.assertTrue(current['complete'])
        self.assertIsNone(current['error'])
        manifest = json.loads((run / 'sha256_manifest.json').read_text())
        for name, digest in manifest.items():
            self.assertEqual(hashlib.sha256((run / name).read_bytes()).hexdigest(), digest)

    def test_real_pipe_closed_only_after_commit_exits_zero_including_shutdown(self):
        with tempfile.TemporaryDirectory(prefix='TEST-external-risk-cli-') as td:
            result, root, evidence = self.run_cli(Path(td), 'broken_pipe')
            self.assert_committed_unchanged(root, evidence)
            earlier = evidence.with_suffix('.progress').read_text()
            self.assertIn('[1/3]', earlier)
            self.assertIn('[2/3]', earlier)
            self.assertNotIn('[3/3] 完成', earlier)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')

    def test_final_json_oserror_is_noncritical_and_preserves_publication(self):
        with tempfile.TemporaryDirectory(prefix='TEST-external-risk-cli-') as td:
            result, root, evidence = self.run_cli(Path(td), 'os_error')
            self.assert_committed_unchanged(root, evidence)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('[3/3] 完成', result.stdout)
            self.assertEqual(result.stderr, '')

    def test_normal_stdout_retains_progress_then_exact_result_json(self):
        with tempfile.TemporaryDirectory(prefix='TEST-external-risk-cli-') as td:
            result, root, evidence = self.run_cli(Path(td), 'normal')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            lines = result.stdout.splitlines()
            self.assertTrue(lines[0].startswith('[1/3]'))
            self.assertTrue(any(line.startswith('[2/3]') for line in lines))
            self.assertTrue(lines[-2].startswith('[3/3] 完成'))
            current = json.loads((root / 'company_pledge/current.json').read_text())
            self.assertEqual(lines[-1], json.dumps(current, ensure_ascii=False, default=str))
            self.assert_committed_unchanged(root, evidence)

    def test_prepublication_download_and_validation_failures_remain_nonzero(self):
        for mode in ('download_failure', 'validation_failure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='TEST-external-risk-cli-') as td:
                directory = Path(td)
                initial, root, evidence = self.run_cli(directory, 'normal')
                self.assertEqual(initial.returncode, 0, initial.stderr)
                current_path = root / 'company_pledge/current.json'
                before = current_path.read_bytes()
                run = Path(json.loads(before)['snapshot_path'])
                old_run = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
                if mode == 'validation_failure':
                    (directory / 'TEST-synthetic-archive/company_pledge_latest.json').write_text('{}')
                result, _, failed_evidence = self.run_cli(directory, mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('[3/3] 失败', result.stderr)
                self.assertNotIn('[3/3] 完成', result.stdout)
                self.assertFalse(failed_evidence.exists(), 'must not reach post-commit callback')
                self.assertEqual(current_path.read_bytes(), before)
                for path, content in old_run.items():
                    self.assertEqual(path.read_bytes(), content)
                attempt = json.loads((root / 'company_pledge/last_attempt.json').read_text())
                self.assertFalse(attempt['complete'])
                self.assertIn('download failure' if mode == 'download_failure' else 'hash mismatch', attempt['error'])


if __name__ == '__main__':
    unittest.main()
