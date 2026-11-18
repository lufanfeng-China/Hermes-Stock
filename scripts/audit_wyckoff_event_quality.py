#!/usr/bin/env python3
"""Standalone TDX QFQ Wyckoff event audit; never changes production rules.

Default: full available history warms the observer; only event dates inside
[start, end] are reported, with statuses resolved through end (no future bars).
A symbol with insufficient coverage is disclosed, not silently dropped.
Output directory must not already exist. The entire staged directory is
atomically renamed only after parity, coverage, and integrity checks pass.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
from app.tdx.qfq_kline import load_tdx_qfq_daily
from app.wyckoff_events import (
    MIN_PRIOR, WINDOW, _day, _event, _passes_event_gate, _resolve, clean_wyckoff_bars,
    observe_wyckoff,
)

KINDS = ("Spring", "UT", "SOS", "SOW", "LPS", "LPSY")
STATUSES = ("candidate", "confirmed", "invalidated")
NAME_RE = re.compile(r"^(SH#6\d{5}|SZ#(?:00|30)\d{4}|BJ#92\d{4})\.txt$", re.I)
EVENT_FIELDS = ("market", "symbol", "date", "type", "status", "confirmation_date",
                "invalidated_date", "invalidated_close", "invalidated_reason",
                "boundary", "box_lower", "box_upper", "box_through_date", "high",
                "low", "close", "volume", "prior_volume_median_20", "volume_ratio_20")
COVERAGE_FIELDS = ("market", "symbol", "status", "error", "source_first", "source_last",
                   "traded_first", "traded_last", "traded_bars", "bars_before_start",
                   "bars_in_window", "events_in_window", "end_covered")


def discover(export_dir: Path) -> list[tuple[str, str]]:
    """Filename-based A-share selection; no claim about ST without metadata."""
    found = {}
    for path in export_dir.iterdir():
        if NAME_RE.fullmatch(path.name):
            market, code = path.stem.upper().split('#')
            key = (market, code)
            if key in found:
                raise ValueError(f'duplicate export for {key}: {path}')
            found[key] = path
    return sorted(found)


def fast_events(bars: pd.DataFrame) -> list[dict]:
    """Same event lifecycle as observe_wyckoff, using bounded NumPy quantiles.

    Reuse production _event/_resolve, and keep only non-invalidated events in
    resolution loop. Every event on sampled symbols is parity-checked against
    the original observer, including float-exact frozen boundaries.
    """
    clean = clean_wyckoff_bars(bars)
    if len(clean) <= MIN_PRIOR:
        return []
    # Series.quantile uses NumPy linear interpolation, unlike rolling.quantile:
    # e.g. 0.04900000000000001 vs 0.049 changes frozen evidence and edge tests.
    # Convert columns once, then quantile only bounded 60-bar NumPy views.
    lows = clean['low'].to_numpy(dtype=float)
    highs = clean['high'].to_numpy(dtype=float)
    events: list[dict] = []
    live: list[dict] = []
    active = None
    for i in range(MIN_PRIOR, len(clean)):
        row = clean.iloc[i]
        day = _day(clean.index[i])
        box = {'lower': float(np.quantile(lows[max(0, i-WINDOW):i], .10)),
               'upper': float(np.quantile(highs[max(0, i-WINDOW):i], .90)),
               'lookback_bars': min(i, WINDOW), 'through_date': _day(clean.index[i - 1]),
               'method': 'prior_60_high_q90_low_q10'}
        live_next = []
        for event in live:
            _resolve(event, row, day)
            if event['status'] != 'invalidated':
                live_next.append(event)
        live = live_next
        if active is not None and active['status'] == 'invalidated':
            active = None
        upper, lower = box['upper'], box['lower']
        high, low, close = (float(row[x]) for x in ('high', 'low', 'close'))
        old_close = float(clean.iloc[i - 1]['close'])
        kind = None
        if active is not None and active['status'] == 'confirmed':
            edge = active['evidence']['boundary']
            if active['type'] == 'SOS' and low <= edge <= close < old_close:
                kind = 'LPS'
            elif active['type'] == 'SOW' and high >= edge >= close > old_close:
                kind = 'LPSY'
            if kind:
                frozen = active['evidence']
                event_box = {'lower': frozen['box_lower'], 'upper': frozen['box_upper'],
                             'through_date': frozen['box_through_date']}
                if _passes_event_gate(kind, event_box, row, clean.iloc[:i]):
                    event = _event(kind, day, event_box, row, clean.iloc[:i])
                    events.append(event)
                    live.append(event)
                    active = None
                    continue
                kind = None
        if lower < close < upper:
            if low < lower and high <= upper:
                kind = 'Spring'
            elif high > upper and low >= lower:
                kind = 'UT'
        elif close > upper and old_close <= upper:
            kind = 'SOS'
        elif close < lower and old_close >= lower:
            kind = 'SOW'
        if kind and _passes_event_gate(kind, box, row, clean.iloc[:i]):
            event = _event(kind, day, box, row, clean.iloc[:i])
            events.append(event)
            live.append(event)
            if kind in ('SOS', 'SOW'):
                active = event
    return events


def assert_parity(bars: pd.DataFrame, actual: list[dict]) -> int:
    expected = observe_wyckoff(bars)['events']
    if len(expected) != len(actual):
        raise AssertionError(f'event count mismatch: baseline={len(expected)} fast={len(actual)}')
    for n, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            raise AssertionError(f'event {n} mismatch baseline={left!r} fast={right!r}')
    return len(expected)


def event_row(market: str, symbol: str, event: dict) -> dict:
    evidence = event['evidence']
    invalid = event['invalidated_by'] or {}
    return {'market': market, 'symbol': symbol, 'date': event['date'],
            'type': event['type'], 'status': event['status'],
            'confirmation_date': event['confirmation_date'] or '',
            'invalidated_date': invalid.get('date', ''),
            'invalidated_close': invalid.get('close', ''),
            'invalidated_reason': invalid.get('reason', ''),
            **{key: evidence[key] if evidence[key] is not None else '' for key in EVENT_FIELDS[9:]}}


def _one(job: tuple[str, str, str, str, str, bool]) -> tuple[list[dict], dict, int]:
    market, code, source, start, end, parity = job
    base = dict(market=market, symbol=code, status='ok', error='', source_first='',
                source_last='', traded_first='', traded_last='', traded_bars=0,
                bars_before_start=0, bars_in_window=0, events_in_window=0, end_covered=False)
    try:
        bars = load_tdx_qfq_daily(code, Path(source))
        base['source_first'], base['source_last'] = _day(bars.index[0]), _day(bars.index[-1])
        # Truncate future data before both optimization and reference parity.
        bars = bars.loc[bars.index <= end]
        clean = clean_wyckoff_bars(bars)
        if len(clean):
            base['traded_first'], base['traded_last'] = _day(clean.index[0]), _day(clean.index[-1])
        base['traded_bars'] = len(clean)
        base['bars_before_start'] = int((clean.index < start).sum())
        base['bars_in_window'] = int(((clean.index >= start) & (clean.index <= end)).sum())
        base['end_covered'] = bool(len(clean) and base['traded_last'] >= end)
        events = fast_events(bars)
        checked = assert_parity(bars, events) if parity else 0
        rows = [event_row(market, code, e) for e in events if start <= e['date'] <= end]
        base['events_in_window'] = len(rows)
        if not base['bars_in_window']:
            base['status'] = 'no_window_bars'
        elif not base['end_covered']:
            base['status'] = 'source_ended_early'
        elif base['bars_before_start'] < MIN_PRIOR:
            base['status'] = 'short_warmup'
        return rows, base, checked
    except AssertionError:
        raise
    except Exception as exc:
        base.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        return [], base, 0


def _write_csv(path: Path, fields: tuple[str, ...], rows) -> None:
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(export_dir: Path, output_dir: Path, start: str, end: str, *, workers: int = 4,
        sample_count: int = 20, strict: bool = True, limit: int | None = None) -> dict:
    export_dir, output_dir = Path(export_dir), Path(output_dir)
    if not export_dir.is_dir():
        raise FileNotFoundError(export_dir)
    start, end = pd.Timestamp(start).strftime('%Y-%m-%d'), pd.Timestamp(end).strftime('%Y-%m-%d')
    if start > end or not 1 <= workers <= 4 or sample_count < 1 or (limit is not None and limit < 1):
        raise ValueError('require start <= end, workers 1..4, sample_count >= 1, limit >= 1')
    if output_dir.exists():
        raise FileExistsError(f'output exists; choose a new directory: {output_dir}')
    symbols = discover(export_dir)
    if limit is not None:
        symbols = symbols[:limit]
    if not symbols:
        raise ValueError('no matching SH/SZ/BJ A-share export files')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{output_dir.name}.tmp-', dir=output_dir.parent))
    t0 = time.perf_counter()
    # Evenly spread deterministic parity samples across the entire sorted universe.
    samples = {i * len(symbols) // min(sample_count, len(symbols))
               for i in range(min(sample_count, len(symbols)))}
    jobs = ((m, c, str(export_dir), start, end, i in samples)
            for i, (m, c) in enumerate(symbols))
    counts: Counter = Counter()
    markets: Counter = Counter()
    statuses: Counter = Counter()
    checked_symbols = checked_events = total_events = 0
    try:
        with (staging / 'events.csv').open('w', newline='', encoding='utf-8') as ef, \
             (staging / 'coverage.csv').open('w', newline='', encoding='utf-8') as cf:
            ew, cw = csv.DictWriter(ef, EVENT_FIELDS), csv.DictWriter(cf, COVERAGE_FIELDS)
            ew.writeheader()
            cw.writeheader()
            def consume(i, result):
                nonlocal checked_symbols, checked_events, total_events
                rows, coverage, matched = result
                if i in samples and coverage['status'] != 'failed':
                    checked_symbols += 1
                    checked_events += matched
                if strict and coverage['status'] == 'failed':
                    raise RuntimeError(f'failed export: {coverage}')
                cw.writerow(coverage)
                markets[coverage['market']] += 1
                statuses[coverage['status']] += 1
                for row in rows:
                    if row['type'] not in KINDS or row['status'] not in STATUSES:
                        raise AssertionError(f'unrecognized event: {row}')
                    ew.writerow(row)
                    counts[(row['date'][:4], row['type'], row['status'])] += 1
                    total_events += 1
            if workers == 1:
                for i, job in enumerate(jobs):
                    consume(i, _one(job))
            else:
                # At most 2*workers in flight, including queued jobs and results.
                from collections import deque
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    iterator = enumerate(jobs)
                    pending = deque()
                    for _ in range(workers * 2):
                        try:
                            i, job = next(iterator)
                            pending.append((i, executor.submit(_one, job)))
                        except StopIteration:
                            break
                    while pending:
                        i, future = pending.popleft()
                        consume(i, future.result())
                        try:
                            next_i, job = next(iterator)
                            pending.append((next_i, executor.submit(_one, job)))
                        except StopIteration:
                            pass
        if sum(counts.values()) != total_events:
            raise AssertionError('year/type/status counts do not match event rows')
        _write_csv(staging / 'year_type_status.csv', ('year', 'type', 'status', 'count'),
                   (dict(year=y, type=k, status=s, count=counts.get((str(y), k, s), 0))
                    for y in range(int(start[:4]), int(end[:4]) + 1)
                    for k in KINDS for s in STATUSES))
        manifest = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                        source=str(export_dir.resolve()), price_basis='tdx_export_qfq',
                        start=start, end=end, warmup='full_history', resolution_as_of=end,
                        universe_filter='SH6xxxxx/SZ00xxxx/SZ30xxxx/BJ92xxxx filenames; ST not excluded (no reliable name metadata)',
                        symbols_total=len(symbols), symbols_by_market=dict(markets),
                        symbols_by_status=dict(statuses), symbols_failed=statuses['failed'],
                        events_total=total_events, parity=dict(checked_symbols=checked_symbols,
                        checked_events=checked_events, mismatches=0),
                        elapsed_seconds=round(time.perf_counter() - t0, 3), workers=workers,
                        sample_count=sample_count, limit=limit,
                        completeness=('sample_only' if limit is not None else
                                      'complete' if statuses == Counter({'ok': len(symbols)}) else 'partial_coverage'),
                        files=['events.csv', 'coverage.csv', 'year_type_status.csv', 'manifest.json'])
        (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(staging, output_dir)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-dir', type=Path, default=Path('/mnt/c/new_tdx64/T0002/export'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--start', default='2023-01-01')
    parser.add_argument('--end', default='2026-10-30')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--parity-samples', type=int, default=20)
    parser.add_argument('--allow-failures', action='store_true', help='Publish explicit incomplete manifest if exports fail')
    parser.add_argument('--limit', type=int, help='Small deterministic smoke run; never a full-market claim')
    args = parser.parse_args()
    print(json.dumps(run(args.export_dir, args.output_dir, args.start, args.end,
                         workers=args.workers, sample_count=args.parity_samples,
                         strict=not args.allow_failures, limit=args.limit), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
