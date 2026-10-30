#!/usr/bin/env python3
"""Build all-market good-stock diagnostics, publishing only complete batches."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.undervaluation import service
from app.relative_valuation.data_loader import INDUSTRY_VALUATION_CURRENT_PATH

OUT = ROOT / 'data/derived/datasets/final/good_stock_undervaluation_current.json'


def validate_publication(output, limit, financial):
    if output.resolve() == OUT.resolve() and (limit or financial.get('partial_sample')):
        raise ValueError('limited/sample input cannot overwrite production output; specify --output staging')
    if limit < 0:
        raise ValueError('--limit must be nonnegative')


def build_payload(financial, limit=0):
    keys = sorted((financial.get('stocks') or {}).keys())
    if limit:
        keys = keys[:limit]
    if not keys:
        raise ValueError('empty financial source; last published diagnostics retained')
    rows, failures = [], []
    for index, key in enumerate(keys, 1):
        market, symbol = key.split(':', 1)
        try:
            result = service.build_current_diagnosis(market, symbol)
            if result.get('ok'):
                rows.append(result)
            else:
                failures.append({'key': key, 'reasons': result.get('reasons') or [result.get('status')]})
        except Exception as exc:
            failures.append({'key': key, 'error': str(exc)})
        if index % 25 == 0 or index == len(keys):
            print(json.dumps({'progress': index, 'total': len(keys), 'diagnosed': len(rows), 'failed': len(failures)}, ensure_ascii=False), flush=True)
    if failures:
        raise ValueError(f'incomplete diagnostic batch ({len(failures)}/{len(keys)} failed); last published output retained: {failures[:10]}')
    industry_source = json.loads(INDUSTRY_VALUATION_CURRENT_PATH.read_text())
    st = INDUSTRY_VALUATION_CURRENT_PATH.stat()
    dates = Counter(row.get('as_of_date') or 'unavailable' for row in rows)
    return {
        'schema_version': 'good-stock-undervaluation-current-snapshot-v2',
        'built_at': datetime.now(timezone.utc).isoformat(), 'scope': 'current_snapshot_only',
        'partial_sample': bool(limit or financial.get('partial_sample')),
        'source_metadata': {
            'financial_source': str(service.STRICT_SNAPSHOT),
            'financial_as_of': financial.get('as_of_date'), 'financial_built_at': financial.get('built_at'),
            'annual_periods': financial.get('annual_periods'),
            'latest_period_counts': dict(Counter(row.get('latest_report_period') or 'unavailable' for row in rows)),
            'availability_counts': dict(Counter((row.get('financial_evidence') or {}).get('availability_status') or 'unavailable' for row in rows)),
            'financial_sources': financial.get('sources'),
            'industry_source': str(INDUSTRY_VALUATION_CURRENT_PATH),
            'industry_source_metadata': ({k: v for k, v in industry_source.items() if k in ('built_at', 'generated_at', 'trading_day', 'as_of_date', 'summary', 'meta', 'metadata')} if isinstance(industry_source, dict) else {'industry_records': len(industry_source), 'trading_day_counts': dict(Counter(r.get('trading_day') or 'unavailable' for r in industry_source)), 'generated_at': None, 'generation_time_evidence': 'source_does_not_publish_generation_time'}),
            'industry_source_fingerprint': {'mtime_ns': st.st_mtime_ns, 'size': st.st_size},
            'industry_as_of_counts': dict(dates), 'industry_covered_records': sum(n for day, n in dates.items() if day != 'unavailable'),
        },
        'stocks': rows, 'failures': [],
        'summary': {'universe_records': len(keys), 'diagnosed_records': len(rows), 'failed_records': 0,
                    'quadrants': dict(Counter((row.get('quadrant') or {}).get('quadrant') for row in rows))},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--financial-snapshot', type=Path, help='Alternate financial input for staging tests')
    args = parser.parse_args()
    if args.financial_snapshot:
        service.STRICT_SNAPSHOT = args.financial_snapshot
    financial = service._strict_snapshot()
    validate_publication(args.output, args.limit, financial)
    lock = args.output.with_suffix('.building')
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise SystemExit(f'existing build lock: {lock}')
    with os.fdopen(fd, 'w') as handle:
        json.dump({'started_at': datetime.now(timezone.utc).isoformat()}, handle)
    temporary = None
    try:
        before = service._file_fingerprint(service.STRICT_SNAPSHOT), service._file_fingerprint(INDUSTRY_VALUATION_CURRENT_PATH)
        payload = build_payload(financial, args.limit)
        after = service._file_fingerprint(service.STRICT_SNAPSHOT), service._file_fingerprint(INDUSTRY_VALUATION_CURRENT_PATH)
        if before != after:
            raise ValueError('source changed during build; mixed-version publication aborted')
        with NamedTemporaryFile('w', encoding='utf-8', dir=args.output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        os.replace(temporary, args.output)
        print(json.dumps({'output': str(args.output), **payload['summary']}, ensure_ascii=False))
    finally:
        lock.unlink(missing_ok=True)
        if temporary:
            temporary.unlink(missing_ok=True)

if __name__ == '__main__':
    main()
