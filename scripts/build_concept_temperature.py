#!/usr/bin/env python3
"""Build the QFQ-based current concept-temperature dataset, including temperature streaks."""
from __future__ import annotations

import argparse
import multiprocessing
import os
import shutil
import tempfile
import time
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.concept_temperature import (attach_temperature_streaks, build_temperature_rows,
                                     fill_member_names, parse_tdx_concept_mapping, prepare_series)
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
    # 源快照没有名称，补上，否则成分股清单的「名称」列会是空的
    fill_member_names(mapping)
    return mapping


def add_streaks(mapping, frames, window, concepts, as_of, min_members, prepared=None):
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
            daily_rows, _ = build_temperature_rows(mapping, frames, window=window, min_members=min_members,
                                                    as_of=date, include_members=False, prepared=prepared)
            levels = {row['concept_code']: row['temperature'] for row in daily_rows}
        history.append(levels)
        unresolved = {code for code in unresolved if levels.get(code) == current_levels[code]}
        if not unresolved:
            break
    attach_temperature_streaks(concepts, history)
    for row in concepts:
        row['temperature_streak_capped'] = row['concept_code'] in unresolved


def build_heat_history(mapping, frames, window, as_of, min_members, prepared=None):
    """Return six-month heat-score series for every concept at the selected window."""
    dates = sorted({date for frame in frames.values() for date in frame.index if date <= as_of})[-HEAT_TREND_DAYS:]
    history = {}
    for date in dates:
        rows, _ = build_temperature_rows(mapping, frames, window=window, min_members=min_members,
                                          as_of=date, include_members=False, prepared=prepared)
        for row in rows:
            history.setdefault(row['concept_code'], []).append({'date': date.strftime('%Y-%m-%d'), 'heat_score': row['heat_score']})
    return history


def _window_payload(window, mapping, frames, as_of, min_members, prepared=None):
    """单窗口完整产物：当日温度 + 连续天数 + 热度序列。"""
    concepts, members = build_temperature_rows(mapping, frames, window=window, min_members=min_members,
                                               prepared=prepared)
    add_streaks(mapping, frames, window, concepts, as_of, min_members, prepared=prepared)
    heat_history = build_heat_history(mapping, frames, window, as_of, min_members, prepared=prepared)
    return {'concepts': concepts, 'members': members, 'heat_history': heat_history}


def _window_worker(window, mapping, frames, as_of, min_members, out_path, prepared=None):
    """fork 子进程：算完一个窗口后写 JSON，避免把大对象 pickle 回父进程。"""
    started = time.monotonic()
    payload = _window_payload(window, mapping, frames, as_of, min_members, prepared=prepared)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'窗口 {window} 完成（{time.monotonic() - started:.1f}s，进程 {os.getpid()}）', flush=True)


def _available_memory_mb() -> int | None:
    try:
        with open('/proc/meminfo', encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def frames_memory_mb(frames) -> int:
    """frames 的常驻估算（MB）。fork 后的子进程会各自涨到相近量级，
    CPython 的引用计数会不断写脏共享页，所以不能假设写时复制等于免费。"""
    try:
        return int(sum(frame.memory_usage(deep=False).sum() for frame in frames.values()) // (1024 * 1024))
    except Exception:
        return 0


def default_jobs(window_count: int, frames_mb: int) -> int:
    """按可用内存决定窗口并发数：每个子进程 ≈ frames_mb + 250MB 余量。"""
    available = _available_memory_mb()
    if available is None:
        return 1
    per_worker = max(900, frames_mb + 500)      # 实测：frames 690 MB → 每进程约 1.2 GB
    by_memory = (available - 1200) // per_worker if available > 1200 else 0
    return max(1, min(window_count, multiprocessing.cpu_count() // 2, by_memory, 5))


def build_windows(target_windows, mapping, frames, as_of, min_members, jobs=1, prepared=None):
    """按窗口并行计算；jobs<=1 或只有一个窗口时走原来的串行路径。

    采用 fork + 独立进程：frames 在 fork 时被继承（写时复制），不需要 pickle
    5,500 个 DataFrame；每个子进程把该窗口的产物写成临时 JSON，父进程再合并。
    """
    windows = sorted(target_windows)
    if jobs <= 1 or len(windows) == 1:
        built = {}
        for window in windows:
            started = time.monotonic()
            built[str(window)] = _window_payload(window, mapping, frames, as_of, min_members, prepared=prepared)
            print(f'窗口 {window} 完成（{time.monotonic() - started:.1f}s，串行）', flush=True)
        return built

    context = multiprocessing.get_context('fork')
    workdir = Path(tempfile.mkdtemp(prefix='hermes-temp-window-'))
    pending = [(window, workdir / f'window-{window}.json') for window in windows]
    running: list[tuple[int, object, Path]] = []
    finished: list[tuple[int, Path]] = []
    failed: list[int] = []
    try:
        while pending or running:
            while pending and len(running) < jobs:
                window, out_path = pending.pop(0)
                process = context.Process(
                    target=_window_worker,
                    args=(window, mapping, frames, as_of, min_members, str(out_path), prepared),
                )
                process.start()
                running.append((window, process, out_path))
            time.sleep(0.5)
            for entry in list(running):
                window, process, out_path = entry
                if process.is_alive():
                    continue
                process.join()
                running.remove(entry)
                if process.exitcode == 0:
                    finished.append((window, out_path))
                else:
                    failed.append(window)
        if failed:
            raise RuntimeError(f'窗口构建失败：{sorted(failed)}（退出码非 0）')
        built = {}
        for window, out_path in finished:
            built[str(window)] = json.loads(out_path.read_text(encoding='utf-8'))
        return built
    finally:
        for _window, process, _out in running:
            if process.is_alive():
                process.terminate()
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--window', type=int, choices=WINDOWS, help='build only one window, for parallel builds')
    parser.add_argument('--output', type=Path, help='write to an alternate JSON output path')
    parser.add_argument('--scope', choices=sorted(SCOPES), default='concept', help='concept (default) or industry')
    parser.add_argument('--min-members', type=int, help='override the per-scope minimum member count')
    parser.add_argument('--jobs', type=int, default=0,
                        help='并行窗口数（0=按 CPU 自动，1=串行）；仅有 --window 时无意义')
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
    prepared = prepare_series(frames)
    jobs = args.jobs if args.jobs > 0 else default_jobs(len(target_windows), frames_memory_mb(frames))
    print(f'可用内存 {_available_memory_mb()} MB，frames {frames_memory_mb(frames)} MB → 窗口并发 {jobs}', flush=True)
    windows = build_windows(target_windows, mapping, frames, as_of, min_members, jobs=jobs, prepared=prepared)
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
    print(json.dumps({'path': str(output_path), 'as_of_date': payload['as_of_date'], 'windows': sorted(windows), 'concepts': sum(len(section['concepts']) for section in windows.values()), 'stocks': len(frames), 'jobs': jobs}, ensure_ascii=False))


if __name__ == '__main__':
    main()
