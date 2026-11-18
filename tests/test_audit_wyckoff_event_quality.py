"""Contract checks for standalone event audit, using real QFQ exports for parity."""
import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from app.wyckoff_events import observe_wyckoff
from scripts import audit_wyckoff_event_quality as audit


def test_fast_observer_exact_event_parity_on_export():
    source = Path('/mnt/c/new_tdx64/T0002/export')
    if not (source / 'SZ#000001.txt').exists():
        pytest.skip('TDX QFQ export unavailable')
    from app.tdx.qfq_kline import load_tdx_qfq_daily
    bars = load_tdx_qfq_daily('000001', source)
    audit.assert_parity(bars, audit.fast_events(bars))


def test_audit_writes_events_coverage_counts_and_manifest(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    rows = ['证券代码', '日期\t开盘\t最高\t最低\t收盘\t成交量\t成交额']
    dates = pd.bdate_range('2022-01-03', periods=110)
    rows += [f'{d:%Y/%m/%d}\t10\t10.1\t9.9\t10\t100\t1000' for d in dates]
    (source / 'SZ#000001.txt').write_text('\n'.join(rows), encoding='gb18030')
    (source / 'SZ#000002.txt').write_text('bad export', encoding='gb18030')
    out = tmp_path / 'out'
    audit.run(source, out, '2022-01-03', '2022-12-31', workers=1, sample_count=1, strict=False)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['symbols_total'] == 2
    assert manifest['symbols_failed'] == 1
    assert manifest['warmup'] == 'full_history'
    assert manifest['parity']['checked_symbols'] == 1
    with (out / 'coverage.csv').open() as f:
        coverage = list(csv.DictReader(f))
    assert {r['status'] for r in coverage} == {'source_ended_early', 'failed'}
    assert (out / 'events.csv').exists()
    with (out / 'year_type_status.csv').open() as f:
        stats = list(csv.DictReader(f))
    assert len(stats) == 6 * 3
    assert sum(int(row['count']) for row in stats) == manifest['events_total']
    assert manifest['completeness'] == 'partial_coverage'


def test_short_warmup_does_not_hide_early_source_end(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    rows = ['证券代码', '日期\t开盘\t最高\t最低\t收盘\t成交量\t成交额']
    rows += [f'{d:%Y/%m/%d}\t10\t10.1\t9.9\t10\t100\t1000'
             for d in pd.bdate_range('2023-01-03', periods=90)]
    (source / 'SZ#000001.txt').write_text('\n'.join(rows), encoding='gb18030')
    _, cover, _ = audit._one(('SZ', '000001', str(source), '2023-01-01', '2023-12-31', False))
    assert cover['bars_before_start'] == 0
    assert cover['end_covered'] is False
    assert cover['status'] == 'source_ended_early'


def test_nonzero_year_type_status_matches_event_rows(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'SZ#000001.txt').write_text('stub')
    row = {k: '' for k in audit.EVENT_FIELDS}
    row.update(market='SZ', symbol='000001', date='2023-03-01', type='Spring', status='invalidated')
    cover = {k: '' for k in audit.COVERAGE_FIELDS}
    cover.update(market='SZ', symbol='000001', status='ok')
    monkeypatch.setattr(audit, '_one', lambda _: ([row], cover, 1))
    out = tmp_path / 'out'
    audit.run(source, out, '2023-01-01', '2023-12-31', workers=1, sample_count=1)
    with (out / 'year_type_status.csv').open() as f:
        counts = {(r['year'], r['type'], r['status']): int(r['count']) for r in csv.DictReader(f)}
    assert counts[('2023', 'Spring', 'invalidated')] == 1
    assert sum(counts.values()) == 1


def test_failed_export_in_parity_sample_is_disclosed_not_fatal_with_allow_failures(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'BJ#920000.txt').write_text('bad export', encoding='gb18030')
    rows = ['证券代码', '日期\t开盘\t最高\t最低\t收盘\t成交量\t成交额']
    rows += [f'{d:%Y/%m/%d}\t10\t10.1\t9.9\t10\t100\t1000'
             for d in pd.bdate_range('2022-01-03', periods=110)]
    (source / 'SZ#000001.txt').write_text('\n'.join(rows), encoding='gb18030')
    manifest = audit.run(source, tmp_path / 'out', '2023-01-01', '2026-10-30',
                         workers=1, sample_count=2, strict=False)
    assert manifest['symbols_failed'] == 1
    assert manifest['parity']['checked_symbols'] == 1
    assert manifest['completeness'] == 'partial_coverage'


def test_parity_mismatch_prevents_publishing(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    rows = ['证券代码', '日期\t开盘\t最高\t最低\t收盘\t成交量\t成交额']
    rows += [f'{d:%Y/%m/%d}\t10\t10.1\t9.9\t10\t100\t1000'
             for d in pd.bdate_range('2022-01-03', periods=110)]
    (source / 'SZ#000001.txt').write_text('\n'.join(rows), encoding='gb18030')
    out = tmp_path / 'out'
    monkeypatch.setattr(audit, 'assert_parity', lambda *a: (_ for _ in ()).throw(AssertionError('mismatch')))
    with pytest.raises(AssertionError, match='mismatch'):
        audit.run(source, out, '2023-01-01', '2026-10-30', workers=1, sample_count=1, strict=False)
    assert not (out / 'manifest.json').exists()
