#!/usr/bin/env python3
"""Build the QFQ-based current concept-temperature dataset, including temperature streaks."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.concept_temperature import attach_temperature_streaks, build_temperature_rows, parse_tdx_concept_mapping
from app.config import TDX_QFQ_EXPORT_DIR
from app.tdx.qfq_kline import load_tdx_qfq_daily

MAPPING_PATH = Path('/mnt/c/new_tdx64/T0002/export/概念板块.txt')
OUT_PATH = PROJECT_ROOT / 'data/derived/datasets/final/dataset_concept_temperature_current.json'
WINDOWS = (3, 5, 10, 20, 60)
MIN_MEMBERS = 10
STREAK_LOOKBACK = 20


def add_streaks(mapping, frames, window, concepts, as_of):
    """Measure each current temperature's uninterrupted trading-day run backward."""
    current_levels = {row['concept_code']: row['temperature'] for row in concepts if row['temperature'] is not None}
    unresolved = set(current_levels)
    all_dates = sorted({date for frame in frames.values() for date in frame.index if date <= as_of})
    dates = list(reversed(all_dates[-STREAK_LOOKBACK:]))
    history = []
    for date in dates:
        if date == as_of:
            levels = {row['concept_code']: row['temperature'] for row in concepts}
        else:
            daily_rows, _ = build_temperature_rows(mapping, frames, window=window, min_members=MIN_MEMBERS, as_of=date, include_members=False)
            levels = {row['concept_code']: row['temperature'] for row in daily_rows}
        history.append(levels)
        unresolved = {code for code in unresolved if levels.get(code) == current_levels[code]}
        if not unresolved:
            break
    attach_temperature_streaks(concepts, history)
    for row in concepts:
        row['temperature_streak_capped'] = row['concept_code'] in unresolved


def main() -> None:
    mapping = parse_tdx_concept_mapping(MAPPING_PATH.read_text(encoding='gb18030'))
    frames = {}
    skipped = 0
    for symbol in sorted({row['symbol'] for row in mapping}):
        try:
            frames[symbol] = load_tdx_qfq_daily(symbol)
        except (FileNotFoundError, ValueError):
            skipped += 1
    if not frames:
        raise RuntimeError('No QFQ frames could be loaded')
    as_of = max(frame.index.max() for frame in frames.values())
    frames = {symbol: frame for symbol, frame in frames.items() if frame.index.max() == as_of}
    windows = {}
    for window in WINDOWS:
        concepts, members = build_temperature_rows(mapping, frames, window=window, min_members=MIN_MEMBERS)
        add_streaks(mapping, frames, window, concepts, as_of)
        windows[str(window)] = {'concepts': concepts, 'members': members}
    payload = {
        'dataset_name': 'dataset_concept_temperature_current',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'as_of_date': as_of.strftime('%Y-%m-%d'),
        'price_basis': 'tdx_export_qfq',
        'mapping_path': str(MAPPING_PATH),
        'mapping_encoding': 'gb18030',
        'mapping_rows': len(mapping),
        'mapped_concepts': len({row['concept_code'] for row in mapping}),
        'loaded_qfq_stocks': len(frames),
        'skipped_qfq_stocks': skipped,
        'min_members': MIN_MEMBERS,
        'temperature_streak_unit': 'trading_days',
        'temperature_streak_lookback': STREAK_LOOKBACK,
        'windows': windows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'path': str(OUT_PATH), 'as_of_date': payload['as_of_date'], 'concepts': len(windows['10']['concepts']), 'stocks': len(frames)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
