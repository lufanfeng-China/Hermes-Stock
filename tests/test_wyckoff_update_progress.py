"""The Wyckoff update reports processed, successful and failed symbol counts."""
import json
from datetime import date, timedelta

import pytest

from app.pipeline.state import parse_data_update_progress_line
from app.wyckoff_snapshot import build_snapshot
from scripts.build_wyckoff_snapshot import main


def _export(root, code, *, broken=False):
    root.mkdir(exist_ok=True)
    path = root / f'SH#{code}.txt'
    if broken:
        path.write_text('broken', encoding='gb18030')
        return
    rows = ['metadata', 'date\topen\thigh\tlow\tclose\tvolume\tamount']
    for i in range(45):
        day = (date(2026, 1, 1) + timedelta(days=i)).strftime('%Y/%m/%d')
        rows.append(f'{day}\t10\t11\t9\t10\t1000\t10000')
    path.write_text('\n'.join(rows) + '\n', encoding='gb18030')


def test_snapshot_reports_exact_total_from_selected_universe_and_completed_counts(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    _export(source, '600000')
    _export(source, '600001')
    observed = []
    result = build_snapshot(source, output, trading_day='2026-02-14', limit=2,
                            progress_callback=lambda processed, total, success, failed:
                                observed.append((processed, total, success, failed)))
    assert observed == [(0, 2, 0, 0), (2, 2, 2, 0)]
    assert result['coverage']['symbols_total'] == 2


def test_failed_stock_counts_as_processed_but_not_successful(tmp_path):
    source, output = tmp_path / 'export', tmp_path / 'out'
    _export(source, '600000')
    _export(source, '600001', broken=True)
    observed = []
    with pytest.raises(RuntimeError, match='incomplete QFQ universe'):
        build_snapshot(source, output, trading_day='2026-02-14', limit=2,
                       progress_callback=lambda *counts: observed.append(counts))
    assert observed == [(0, 2, 0, 0), (2, 2, 1, 1)]
    assert not (output / 'wyckoff_signals_current.json').exists()


def test_cli_emits_flushed_progress_that_pipeline_parses(tmp_path, capsys):
    source, output = tmp_path / 'export', tmp_path / 'out'
    _export(source, '600000')
    main(['--export-dir', str(source), '--output-dir', str(output),
          '--trading-day', '2026-02-14', '--limit', '1'])
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ['WYCKOFF_PROGRESS 0/1 success=0 failed=0',
                         'WYCKOFF_PROGRESS 1/1 success=1 failed=0']
    assert json.loads(lines[-1])['coverage']['symbols_total'] == 1
    parsed = parse_data_update_progress_line(lines[1])
    assert parsed['progress_index'] == 1
    assert parsed['progress_total'] == 1
    assert parsed['current_progress_text'] == '威科夫股票：已处理 1/1 只，成功 1 只，失败 0 只'
