#!/usr/bin/env python3
"""Build the QFQ-based current concept-temperature dataset, including temperature streaks."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.concept_temperature import attach_temperature_streaks, build_temperature_rows, parse_tdx_concept_mapping
from app.config import TDX_QFQ_EXPORT_DIR
from app.tdx.qfq_kline import load_tdx_qfq_daily

CONCEPT_MAPPING_PATH = Path('/mnt/c/new_tdx64/T0002/export/概念板块.txt')
INDUSTRY_MAPPING_PATH = PROJECT_ROOT / 'data/derived/datasets/final/snapshot_stock_industry_membership.json'
FINAL_DIR = PROJECT_ROOT / 'data/derived/datasets/final'
WINDOWS = (3, 5, 10, 20, 60)
STREAK_LOOKBACK = 20
HEAT_TREND_DAYS = 126

# 概念与二级行业共用同一套算法，只有成分来源、最小成员数和输出文件不同。
# 行业是全覆盖划分且存在 3 只成员的小行业，故 min_members 取 3；概念重叠、小概念多，沿用 10。
SCOPES = {
    'concept': {
        'dataset_name': 'dataset_concept_temperature_current',
        'out_path': FINAL_DIR / 'dataset_concept_temperature_current.json',
        'min_members': 10,
        'unit_label': '概念',
    },
    'industry': {
        'dataset_name': 'dataset_industry_temperature_current',
        'out_path': FINAL_DIR / 'dataset_industry_temperature_current.json',
        'min_members': 3,
        'unit_label': '二级行业',
    },
}


def load_concept_mapping() -> list[dict[str, str]]:
    return parse_tdx_concept_mapping(CONCEPT_MAPPING_PATH.read_text(encoding='gb18030'))


def load_industry_mapping() -> list[dict[str, str]]:
    """申万二级行业映射 → 与概念映射同构的 (code, name, symbol) 三元组。"""
    rows = json.loads(INDUSTRY_MAPPING_PATH.read_text(encoding='utf-8'))
    mapping: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        code = str(row.get('industry_level_2_code') or '').strip()
        name = str(row.get('industry_level_2_name') or '').strip()
        symbol = str(row.get('symbol') or '').strip().zfill(6)
        if not code or not name or len(symbol) != 6 or not symbol.isdigit():
            continue
        key = (code, symbol)
        if key in seen:
            continue
        seen.add(key)
        mapping.append({'concept_code': code, 'concept_name': name, 'symbol': symbol,
                        'stock_name': str(row.get('stock_name') or '').strip()})
    return mapping


def add_streaks(mapping, frames, window, concepts, as_of, min_members):
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
            daily_rows, _ = build_temperature_rows(mapping, frames, window=window, min_members=min_members, as_of=date, include_members=False)
            levels = {row['concept_code']: row['temperature'] for row in daily_rows}
        history.append(levels)
        unresolved = {code for code in unresolved if levels.get(code) == current_levels[code]}
        if not unresolved:
            break
    attach_temperature_streaks(concepts, history)
    for row in concepts:
        row['temperature_streak_capped'] = row['concept_code'] in unresolved


def build_heat_history(mapping, frames, window, as_of, min_members):
    """Return six-month heat-score series for every concept at the selected window."""
    dates = sorted({date for frame in frames.values() for date in frame.index if date <= as_of})[-HEAT_TREND_DAYS:]
    history = {}
    for date in dates:
        rows, _ = build_temperature_rows(mapping, frames, window=window, min_members=min_members, as_of=date, include_members=False)
        for row in rows:
            history.setdefault(row['concept_code'], []).append({'date': date.strftime('%Y-%m-%d'), 'heat_score': row['heat_score']})
    return history


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--window', type=int, choices=WINDOWS, help='build only one window, for parallel builds')
    parser.add_argument('--output', type=Path, help='write to an alternate JSON output path')
    parser.add_argument('--scope', choices=sorted(SCOPES), default='concept', help='concept (default) or industry')
    parser.add_argument('--min-members', type=int, help='override the per-scope minimum member count')
    args = parser.parse_args()
    config = SCOPES[args.scope]
    min_members = args.min_members or config['min_members']
    target_windows = (args.window,) if args.window else WINDOWS
    mapping = load_concept_mapping() if args.scope == 'concept' else load_industry_mapping()
    if not mapping:
        raise RuntimeError(f'no mapping rows for scope={args.scope}')
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
    for window in target_windows:
        concepts, members = build_temperature_rows(mapping, frames, window=window, min_members=min_members)
        add_streaks(mapping, frames, window, concepts, as_of, min_members)
        heat_history = build_heat_history(mapping, frames, window, as_of, min_members)
        windows[str(window)] = {'concepts': concepts, 'members': members, 'heat_history': heat_history}
    payload = {
        'dataset_name': config['dataset_name'],
        'scope': args.scope,
        'unit_label': config['unit_label'],
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'as_of_date': as_of.strftime('%Y-%m-%d'),
        'price_basis': 'tdx_export_qfq',
        'mapping_path': str(CONCEPT_MAPPING_PATH if args.scope == 'concept' else INDUSTRY_MAPPING_PATH),
        'mapping_encoding': 'gb18030' if args.scope == 'concept' else 'utf-8',
        'mapping_rows': len(mapping),
        'mapped_concepts': len({row['concept_code'] for row in mapping}),
        'loaded_qfq_stocks': len(frames),
        'skipped_qfq_stocks': skipped,
        'min_members': min_members,
        'temperature_streak_unit': 'trading_days',
        'temperature_streak_lookback': STREAK_LOOKBACK,
        'windows': windows,
    }
    output_path = args.output or config['out_path']
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'path': str(output_path), 'as_of_date': payload['as_of_date'], 'windows': sorted(windows), 'concepts': sum(len(section['concepts']) for section in windows.values()), 'stocks': len(frames)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
