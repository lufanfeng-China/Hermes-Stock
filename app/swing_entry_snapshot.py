"""Small, dated all-market publication for *recent* causal swing-state entry.

Only the last five valid sessions need a transition check. Longer and unobserved
runs are deliberately not given an invented start date or exact duration.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import os

import pandas as pd

from app.swing_structure import classify
from app.swing_snapshot import (_atomic_json, _digest, SCHEMA_VERSION as SWING_SCHEMA,
                                RULE_VERSION, DEFAULT_OUTPUT_DIR, DEFAULT_EXPORT_DIR)
from app.tdx.qfq_kline import load_tdx_qfq_daily, qfq_export_path
from app.wyckoff_events import clean_wyckoff_bars

SCHEMA_VERSION = 'swing-state-runs-v5'
MAX_ENTRY_DAYS = 5


def recent_run(bars: pd.DataFrame, state: str) -> dict | None:
    """Find a known state change no more than five valid bars ago."""
    valid = clean_wyckoff_bars(bars)
    if valid.empty or classify(valid)['state'] != state:
        return None
    size = len(valid)
    for days in range(1, min(MAX_ENTRY_DAYS, size - 1) + 1):
        previous_size = size - days
        previous_state = classify(valid.iloc[:previous_size])['state']
        if previous_state != state:
            return {'state': state, 'start_date': str(valid.index[previous_size].date()),
                    'through_date': str(valid.index[-1].date()), 'trading_days': days,
                    'start_confirmed': True, 'previous_state': previous_state,
                    'previous_date': str(valid.index[previous_size - 1].date())}
    return {'state': state, 'start_date': None,
            'through_date': str(valid.index[-1].date()), 'trading_days': None,
            'start_confirmed': False, 'previous_state': None, 'previous_date': None}


def build_snapshot(*, export_dir: Path = DEFAULT_EXPORT_DIR,
                   output_dir: Path = DEFAULT_OUTPUT_DIR, trading_day: str | None = None) -> dict:
    """Publish only against a complete, matching parent swing snapshot."""
    output_dir, export_dir = Path(output_dir), Path(export_dir)
    parent_path = (output_dir / 'swing_structure_v8' / f'{trading_day}.json'
                   if trading_day else output_dir / 'swing_structure_v8_current.json')
    parent = json.loads(parent_path.read_text(encoding='utf-8'))
    day = parent.get('as_of_date')
    if (parent.get('schema_version') != SWING_SCHEMA or parent.get('rule_version') != RULE_VERSION
        or parent.get('price_basis') != 'tdx_export_qfq' or parent.get('completeness') != 'complete'
        or not isinstance(parent.get('stocks'), dict) or not day
        or (trading_day and day != trading_day)):
        raise ValueError('swing parent publication missing, incomplete or not on requested day')
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = output_dir / '.swing_state_runs.building'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.close(fd)
        rows = {}
        coverage = Counter()
        for key, stock in parent['stocks'].items():
            market, symbol = key.split(':', 1)
            row = {field: stock.get(field) for field in ('status', 'state', 'last_bar_date', 'source_sha256')}
            if stock.get('status') == 'ok' and stock.get('state') in (None, '证据不足'):
                row['status'] = 'insufficient_state'
            row['state_run'] = None
            if stock.get('status') == 'ok' and stock.get('state') not in (None, '证据不足'):
                path = qfq_export_path(symbol, export_dir)
                if _digest(path) != stock.get('source_sha256'):
                    raise ValueError(f'{key}: QFQ source changed since parent swing publication')
                bars = load_tdx_qfq_daily(symbol, export_dir)
                bars = bars.loc[bars.index <= day]
                valid = clean_wyckoff_bars(bars)
                if valid.empty or str(valid.index[-1].date()) != day:
                    raise ValueError(f'{key}: QFQ last valid bar does not match parent date')
                row['state_run'] = recent_run(valid, stock['state'])
                if row['state_run'] is None or _digest(path) != stock.get('source_sha256'):
                    raise ValueError(f'{key}: classification/source disagrees with parent publication')
                coverage['confirmed_entry'] += int(row['state_run']['start_confirmed'])
                coverage['outside_window_or_unconfirmed'] += int(not row['state_run']['start_confirmed'])
            else:
                coverage[row['status'] or 'unknown'] += 1
            rows[key] = row
        result = {'schema_version': SCHEMA_VERSION, 'rule_version': RULE_VERSION,
                  'price_basis': 'tdx_export_qfq', 'completeness': 'complete',
                  'as_of_date': day, 'max_entry_days': MAX_ENTRY_DAYS,
                  'coverage': {'symbols_total':len(rows), **coverage}, 'stocks':rows}
        dated = output_dir / 'swing_state_runs_v5' / f'{day}.json'
        if dated.exists():
            if json.loads(dated.read_text(encoding='utf-8')) != result:
                raise FileExistsError(f'immutable entry snapshot differs: {dated}')
        else:
            _atomic_json(dated, result)
        _atomic_json(output_dir / 'swing_state_runs_v5_current.json', result)
        return result
    finally:
        lock.unlink(missing_ok=True)
