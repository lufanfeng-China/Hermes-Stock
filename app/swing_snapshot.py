"""Dated, auditable QFQ v6 swing-structure snapshots for whole-universe screening.

The current TNF universe is a *current* list, not a survivorship-free historical universe.
Historical observations are recomputed from each date's QFQ prefix; never backfilled
from a later canonical swing chain. Raw prices and research CSVs are not fallbacks.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile

from app.search.index import DEFAULT_TNF_FILES, is_a_share_eligible, parse_tnf_file
from app.tdx.qfq_kline import load_tdx_qfq_daily, qfq_export_path
from app.wyckoff_snapshot import DEFAULT_EXPORT_DIR, DEFAULT_OUTPUT_DIR, DEFAULT_SYNC_MANIFEST, _source_day

SCHEMA_VERSION = 'swing-structure-v8'
RULE_VERSION = 'swing-confirmed-5x5-pressure-line-ceiling-v8'


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
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def discover_universe() -> list[tuple[str, str, str]]:
    """The same current TNF / ST universe used by the frozen v5 2026 study."""
    found = []
    for market, path in DEFAULT_TNF_FILES:
        if not path.is_file():
            raise FileNotFoundError(path)
        for stock in parse_tnf_file(path, market=market):
            code, name = stock['symbol'], stock['stock_name']
            if ((market == 'sh' and code.startswith('6'))
                or (market == 'sz' and code.startswith(('00', '30')))
                or (market == 'bj' and code.startswith('92'))):
                if is_a_share_eligible(code, name):
                    found.append((market, code, name))
    return sorted(set(found))


def build_snapshot(export_dir: Path = DEFAULT_EXPORT_DIR, output_dir: Path = DEFAULT_OUTPUT_DIR,
                   *, trading_day: str | None = None, sync_manifest: Path = DEFAULT_SYNC_MANIFEST,
                   limit: int | None = None) -> dict:
    """Publish a complete same-day snapshot, or an isolated sample-only snapshot."""
    export_dir, output_dir = Path(export_dir), Path(output_dir)
    source_day = _source_day(export_dir, Path(sync_manifest))
    trading_day = date.fromisoformat(trading_day or source_day).isoformat()
    if trading_day > source_day:
        raise ValueError(f'QFQ synchronization is stale: {source_day} < {trading_day}')
    if limit is not None and (limit < 1 or output_dir.resolve() == DEFAULT_OUTPUT_DIR.resolve()):
        raise ValueError('samples require a positive limit and isolated output directory')
    stocks = discover_universe()
    if not stocks:
        raise ValueError('empty TNF A-share universe')
    if limit is not None:
        stocks = stocks[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = output_dir / '.swing_structure.building'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode('ascii'))
        os.close(fd)
        current = output_dir / 'swing_structure_v8_current.json'
        historical = output_dir / 'swing_structure_v8' / f'{trading_day}.json'
        old = json.loads(current.read_text(encoding='utf-8')) if current.exists() else None
        if old and (old.get('schema_version'), old.get('rule_version'), old.get('price_basis')) != (SCHEMA_VERSION, RULE_VERSION, 'tdx_export_qfq'):
            raise ValueError('incompatible prior swing publication')
        if old and old['as_of_date'] > trading_day:
            raise ValueError('cannot roll current swing publication backwards')
        if old and old.get('completeness') == 'complete' and limit is not None:
            raise ValueError('sample cannot replace complete publication')
        results = {}
        status = Counter()
        for index, (market, code, name) in enumerate(stocks, 1):
            key = f'{market}:{code}'
            path = qfq_export_path(code, export_dir)
            record = {'name': name, 'status': 'missing_qfq', 'state': None, 'reason': '前复权日线缺失',
                      'last_bar_date': None}
            try:
                if not path.is_file():
                    status['missing_qfq'] += 1
                    results[key] = record
                    continue
                digest = _digest(path)
                previous = (old or {}).get('stocks', {}).get(key)
                if (old and old['as_of_date'] == trading_day and previous
                    and previous.get('source_sha256') == digest):
                    record = previous
                else:
                    from app.swing_structure import classify
                    from app.wyckoff_events import clean_wyckoff_bars
                    bars = load_tdx_qfq_daily(code, export_dir)
                    bars = clean_wyckoff_bars(bars.loc[bars.index <= trading_day])
                    if bars.empty:
                        raise ValueError('no valid QFQ bars before trading day')
                    record = classify(bars)
                    record.update(name=name, source_sha256=digest,
                                  last_bar_date=str(bars.index[-1].date()))
                    if _digest(path) != digest:
                        raise RuntimeError('QFQ export changed during swing build')
                if record.get('last_bar_date') != trading_day:
                    record = {**record, 'status': 'stale_qfq', 'state': None,
                              'new_low_risk': None, 'pressure_line': None,
                              'reason': f"前复权最新有效交易日 {record.get('last_bar_date')} 不是 {trading_day}"}
                else:
                    record = {**record, 'status': 'ok'}
                status[record['status']] += 1
            except (ValueError, FileNotFoundError, KeyError, IndexError, TypeError) as exc:
                record = {**record, 'status': 'parse_error', 'state': None,
                          'reason': f'{type(exc).__name__}: {exc}'[:240]}
                status['parse_error'] += 1
            results[key] = record
            if index % 500 == 0:
                print(f'swing progress {index}/{len(stocks)}', flush=True)
        if status['ok'] == 0:
            raise RuntimeError(f'no current QFQ stocks on {trading_day}')
        if sum(status.values()) != len(stocks):
            raise AssertionError('incomplete swing universe')
        payload = {'schema_version': SCHEMA_VERSION, 'rule_version': RULE_VERSION,
                   'price_basis': 'tdx_export_qfq', 'as_of_date': trading_day,
                   'completeness': 'sample_only' if limit else 'complete',
                   'universe_filter': 'current TNF SH6/SZ00/SZ30/BJ92 excluding current ST; not a PIT listing universe',
                   'coverage': {'symbols_total': len(stocks), 'states_current': status['ok'],
                                'missing_qfq': status['missing_qfq'], 'stale_qfq': status['stale_qfq'],
                                'parse_error': status['parse_error']},
                   'stocks': results}
        if historical.exists():
            old_history = json.loads(historical.read_text(encoding='utf-8'))
            if old_history != payload:
                raise FileExistsError(f'immutable swing snapshot differs: {historical}')
        else:
            _atomic_json(historical, payload)
        _atomic_json(current, payload)
        return payload
    finally:
        lock.unlink(missing_ok=True)
