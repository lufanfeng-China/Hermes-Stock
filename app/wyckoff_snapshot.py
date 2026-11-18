"""Immutable dated Wyckoff QFQ snapshots; only source-changed symbols are recomputed.

The filename universe is SH6/SZ00/SZ30/BJ92; ST cannot be excluded without
reliable name metadata. Neither raw prices nor old audit CSVs are fallback data.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable

from app.tdx.qfq_kline import load_tdx_qfq_daily
from app.wyckoff_events import clean_wyckoff_bars
from scripts.audit_wyckoff_event_quality import discover, fast_events
from scripts.sync_tdx_qfq_exports import latest_bar_date

SCHEMA_VERSION = 'wyckoff-signals-v1'
RULE_VERSION = 'wyckoff-approved-20261103-v1'
DEFAULT_EXPORT_DIR = Path('/mnt/c/new_tdx64/T0002/export')
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / 'data/derived/datasets/final'
DEFAULT_SYNC_MANIFEST = Path(__file__).resolve().parents[1] / 'data/derived/cache/tdx_qfq_export_sync.json'


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def _day(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('trading_day must be ISO YYYY-MM-DD')
    return value


def _source_day(export_dir: Path, sync_manifest: Path) -> str:
    manifest = json.loads(sync_manifest.read_text(encoding='utf-8'))
    if manifest.get('price_basis') != 'tdx_export_qfq' or Path(manifest.get('source_dir', '')).resolve() != export_dir.resolve():
        raise ValueError('QFQ sync manifest source/basis does not match export directory')
    if not manifest.get('valid_daily_file_count', 0) or not manifest.get('file_count', 0):
        raise ValueError('QFQ sync manifest has no validated files')
    return _day(manifest['latest_trading_day'])


def _header_only(path: Path) -> bool:
    """TDX exported a security with its two headers and source footer, no daily rows."""
    if path.stat().st_size > 1024:
        return False
    lines = path.read_bytes().splitlines()
    return len(lines) == 3 and lines[1].count(b'\t') >= 5 and lines[2].startswith(b'#')


def _stock(export_dir: Path, market: str, code: str, trading_day: str, digest: str) -> dict:
    path = export_dir / f'{market}#{code}.txt'
    bars = load_tdx_qfq_daily(code, export_dir)
    if _digest(path) != digest:
        raise RuntimeError(f'QFQ export changed during build: {path}')
    clean = clean_wyckoff_bars(bars.loc[bars.index <= trading_day])
    if clean.empty:
        raise ValueError(f'no valid QFQ bars through {trading_day}: {path}')
    if clean.index[-1].date().isoformat() > trading_day:
        raise AssertionError('future bar in snapshot')
    # fast_events uses the same frozen-edge gates and lifecycle as the observer.
    events = fast_events(clean)
    return {'events': events, 'last_bar_date': clean.index[-1].date().isoformat(),
            'valid_bar_count': len(clean), 'source_sha256': digest}


def build_snapshot(export_dir: Path = DEFAULT_EXPORT_DIR, output_dir: Path = DEFAULT_OUTPUT_DIR,
                   *, trading_day: str | None = None, sync_manifest: Path = DEFAULT_SYNC_MANIFEST,
                   limit: int | None = None, workers: int = 1,
                   progress_callback: Callable[[int, int, int, int], None] | None = None) -> dict:
    """Build and publish a daily QFQ snapshot. Returns the exact published payload.

    Full runs require a matching validated sync manifest. An explicit date may
    select an earlier historical day, never a day newer than the sync manifest.
    Sample runs require an isolated output directory and are marked sample_only.
    """
    export_dir, output_dir = Path(export_dir), Path(output_dir)
    if not export_dir.is_dir():
        raise FileNotFoundError(export_dir)
    if not 1 <= workers <= 4 or (limit is not None and limit < 1):
        raise ValueError('workers must be 1..4 and limit positive')
    if limit is not None and output_dir.resolve() == DEFAULT_OUTPUT_DIR.resolve():
        raise ValueError('sample cannot publish to the production output directory')
    source_day = None
    if limit is None:
        source_day = _source_day(export_dir, Path(sync_manifest))
        trading_day = _day(trading_day) if trading_day else source_day
        if trading_day > source_day:
            raise ValueError(f'stale QFQ sync manifest: requested={trading_day}, synced={source_day}')
    else:
        trading_day = _day(trading_day) if trading_day else _source_day(export_dir, Path(sync_manifest))
    symbols = discover(export_dir)
    if not symbols:
        raise ValueError('no matching QFQ A-share exports')
    if limit is None:
        all_exports = list(export_dir.glob('*.txt'))
        latest = max((value for path in all_exports if (value := latest_bar_date(path))), default=None)
        manifest = json.loads(Path(sync_manifest).read_text(encoding='utf-8'))
        if len(all_exports) != manifest['file_count'] or latest != source_day:
            raise ValueError(f'stale QFQ sync manifest: files={len(all_exports)}, latest={latest}, '
                             f"manifest files={manifest['file_count']}, day={source_day}")
        empty_symbols = [f'{market.lower()}:{code}' for market, code in symbols
                         if _header_only(export_dir / f'{market}#{code}.txt')]
        empty_set = set(empty_symbols)
        symbols = [(market, code) for market, code in symbols
                   if f'{market.lower()}:{code}' not in empty_set]
    else:
        empty_symbols = []
        symbols = symbols[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = output_dir / '.wyckoff_signals.building'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode('ascii'))
        os.close(fd)
        current_path = output_dir / 'wyckoff_signals_current.json'
        history_path = output_dir / 'wyckoff_signals' / f'{trading_day}.json'
        old = json.loads(current_path.read_text(encoding='utf-8')) if current_path.exists() else None
        if old and (old.get('schema_version'), old.get('rule_version'), old.get('price_basis')) != (
                SCHEMA_VERSION, RULE_VERSION, 'tdx_export_qfq'):
            raise ValueError('existing current snapshot has incompatible rule/schema/basis')
        if old and old['as_of_date'] > trading_day:
            raise ValueError('refusing to roll current snapshot backwards')
        if limit is not None and old and old.get('completeness') != 'sample_only':
            raise ValueError('sample cannot overwrite a complete snapshot')
        stocks = {}
        counts = Counter()
        errors = {}
        recomputed = 0
        total = len(symbols)
        if progress_callback:
            progress_callback(0, total, 0, 0)
        for processed, (market, code) in enumerate(symbols, start=1):
            key = f'{market.lower()}:{code}'
            path = export_dir / f'{market}#{code}.txt'
            try:
                digest = _digest(path)
                prior = (old or {}).get('stocks', {}).get(key)
                if prior and prior.get('source_sha256') == digest and old['as_of_date'] <= trading_day:
                    stock = prior
                    counts['carried_forward'] += 1
                else:
                    stock = _stock(export_dir, market, code, trading_day, digest)
                    recomputed += 1
                if stock['last_bar_date'] == trading_day:
                    counts['current'] += 1
                else:
                    counts['lagged'] += 1
                stocks[key] = stock
            except Exception as exc:
                errors[key] = f'{type(exc).__name__}: {exc}'
                counts['failed'] += 1
            if progress_callback and (processed % 25 == 0 or processed == total):
                progress_callback(processed, total, len(stocks), len(errors))
        if errors:
            raise RuntimeError(f'incomplete QFQ universe ({len(errors)} failed): {json.dumps(errors, ensure_ascii=False)[:1500]}')
        if counts['current'] == 0:
            raise RuntimeError(f'stale QFQ source: no valid bars on {trading_day}')
        if len(stocks) != len(symbols):
            raise AssertionError('universe cardinality mismatch')
        payload = {'schema_version': SCHEMA_VERSION, 'rule_version': RULE_VERSION,
                   'as_of_date': trading_day, 'price_basis': 'tdx_export_qfq',
                   'completeness': 'sample_only' if limit is not None else 'complete',
                   'universe_filter': 'SH6/SZ00/SZ30/BJ92 filenames; ST not excluded',
                   'coverage': {'symbols_total': len(symbols), 'excluded_empty_symbols': empty_symbols,
                                'discovered_symbols_total': len(symbols) + len(empty_symbols),
                                'current': counts['current'],
                                'lagged': counts['lagged'], 'failed': 0,
                                'carried_forward': counts['carried_forward'], 'recomputed': recomputed,
                                'lagged_symbols': {k: v['last_bar_date'] for k, v in stocks.items()
                                                   if v['last_bar_date'] < trading_day}},
                   'stocks': stocks}
        if history_path.exists():
            previous = json.loads(history_path.read_text(encoding='utf-8'))
            # Build metadata may differ on retries; observations themselves must not.
            if previous['stocks'] != stocks or any(previous.get(k) != payload[k] for k in (
                    'schema_version', 'rule_version', 'price_basis', 'as_of_date', 'completeness')):
                raise FileExistsError(f'immutable history differs: {history_path}')
        else:
            _atomic_json(history_path, payload)
        _atomic_json(current_path, payload)
        return payload
    finally:
        lock.unlink(missing_ok=True)
