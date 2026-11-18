"""Contract tests for point-in-time, atomic QFQ snapshot publication."""
import json
from pathlib import Path

import pytest

from app.wyckoff_snapshot import build_snapshot


def export(root: Path, code='600000', closes=None):
    closes = closes or [10.] * 45
    root.mkdir(exist_ok=True)
    lines = ['metadata', 'date\topen\thigh\tlow\tclose\tvolume\tamount']
    from datetime import date, timedelta
    for n, close in enumerate(closes):
        day = (date(2026, 1, 1) + timedelta(days=n)).strftime('%Y/%m/%d')
        lines.append(f'{day}\t{close}\t{close+1}\t{close-1}\t{close}\t1000\t10000')
    (root / f'SH#{code}.txt').write_text('\n'.join(lines) + '\n', encoding='gb18030')


def test_sample_build_truncates_future_and_publishes_schema(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    day = '2026-02-11'
    result = build_snapshot(source, output, trading_day=day, limit=1)
    current = json.loads((output / 'wyckoff_signals_current.json').read_text())
    history = json.loads((output / 'wyckoff_signals' / f'{day}.json').read_text())
    assert current == history == result
    assert (result['schema_version'], result['rule_version'], result['price_basis']) == (
        'wyckoff-signals-v1', 'wyckoff-approved-20261103-v1', 'tdx_export_qfq')
    assert result['completeness'] == 'sample_only'
    assert result['stocks']['sh:600000']['last_bar_date'] == day
    assert result['stocks']['sh:600000']['valid_bar_count'] == 42
    assert result['stocks']['sh:600000']['events'] == []
    assert result['coverage']['symbols_total'] == 1


def test_incremental_reuses_unchanged_and_recomputes_readjusted_source(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    first = build_snapshot(source, output, trading_day='2026-02-12', limit=1)
    # Same-day rerun with an identical export carries the symbol; a newly
    # selected market day without any source bars is correctly rejected.
    second = build_snapshot(source, output, trading_day='2026-02-12', limit=1)
    assert second['coverage']['carried_forward'] == 1
    assert second['coverage']['recomputed'] == 0
    with pytest.raises(RuntimeError, match='stale QFQ source'):
        build_snapshot(source, output, trading_day='2026-02-13', limit=1)
    export(source, closes=[11.] * 45)
    third = build_snapshot(source, output, trading_day='2026-02-14', limit=1)
    assert third['coverage']['recomputed'] == 1
    assert third['stocks']['sh:600000']['source_sha256'] != first['stocks']['sh:600000']['source_sha256']
    assert json.loads((output / 'wyckoff_signals/2026-02-12.json').read_text()) == first


def test_bad_export_preserves_current_and_refuses_incomplete_universe(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    build_snapshot(source, output, trading_day='2026-02-11', limit=1)
    current = (output / 'wyckoff_signals_current.json').read_bytes()
    (source / 'SH#600000.txt').write_text('broken', encoding='utf8')
    with pytest.raises(RuntimeError, match='incomplete QFQ universe'):
        build_snapshot(source, output, trading_day='2026-02-12', limit=1)
    assert (output / 'wyckoff_signals_current.json').read_bytes() == current
    assert not (output / 'wyckoff_signals/2026-02-12.json').exists()
    assert not (output / '.wyckoff_signals.building').exists()


def test_full_run_requires_matching_validated_manifest(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    manifest = tmp_path / 'sync.json'
    manifest.write_text(json.dumps({'price_basis': 'tdx_raw', 'source_dir': str(source),
                                    'latest_trading_day': '2026-02-14', 'file_count': 1,
                                    'valid_daily_file_count': 1}))
    with pytest.raises(ValueError, match='manifest source/basis'):
        build_snapshot(source, output, sync_manifest=manifest)
    assert not (output / 'wyckoff_signals_current.json').exists()


def test_full_run_rejects_stale_manifest_before_publication(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    manifest = tmp_path / 'sync.json'
    manifest.write_text(json.dumps({'price_basis': 'tdx_export_qfq', 'source_dir': str(source),
                                    'latest_trading_day': '2026-02-11', 'file_count': 1,
                                    'valid_daily_file_count': 1}))
    with pytest.raises(ValueError, match='stale QFQ sync manifest'):
        build_snapshot(source, output, sync_manifest=manifest)
    assert not (output / 'wyckoff_signals_current.json').exists()


def test_explicit_trading_day_cannot_bypass_outdated_manifest(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    manifest = tmp_path / 'sync.json'
    manifest.write_text(json.dumps({'price_basis': 'tdx_export_qfq', 'source_dir': str(source),
                                    'latest_trading_day': '2026-02-11', 'file_count': 1,
                                    'valid_daily_file_count': 1}))
    with pytest.raises(ValueError, match='stale QFQ sync manifest'):
        build_snapshot(source, output, trading_day='2026-02-14', sync_manifest=manifest)
    assert not (output / 'wyckoff_signals_current.json').exists()


def test_full_run_discloses_header_only_placeholders_not_broken_exports(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    placeholder = source / 'SH#600001.txt'
    placeholder.write_bytes(b'metadata\ndate\topen\thigh\tlow\tclose\tvolume\tamount\n#source\n')
    manifest = tmp_path / 'sync.json'
    manifest.write_text(json.dumps({'price_basis': 'tdx_export_qfq', 'source_dir': str(source),
                                    'latest_trading_day': '2026-02-14', 'file_count': 2,
                                    'valid_daily_file_count': 1}))
    result = build_snapshot(source, output, sync_manifest=manifest)
    assert result['completeness'] == 'complete'
    assert result['coverage']['excluded_empty_symbols'] == ['sh:600001']
    assert result['coverage']['symbols_total'] == 1
    assert 'sh:600001' not in result['stocks']
    placeholder.write_text('broken', encoding='utf8')
    with pytest.raises(RuntimeError, match='incomplete QFQ universe'):
        build_snapshot(source, output, sync_manifest=manifest)


def test_same_day_readjustment_refuses_to_rewrite_history(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    build_snapshot(source, output, trading_day='2026-02-11', limit=1)
    original = (output / 'wyckoff_signals_current.json').read_bytes()
    export(source, closes=[12.] * 45)
    with pytest.raises(FileExistsError, match='immutable history'):
        build_snapshot(source, output, trading_day='2026-02-11', limit=1)
    assert (output / 'wyckoff_signals_current.json').read_bytes() == original


def test_cli_exposes_isolated_sample_build(tmp_path):
    from scripts.build_wyckoff_snapshot import main
    source, output = tmp_path / 'export', tmp_path / 'out'
    export(source)
    main(['--export-dir', str(source), '--output-dir', str(output), '--trading-day',
          '2026-02-11', '--limit', '1'])
    assert (output / 'wyckoff_signals_current.json').exists()
