#!/usr/bin/env python3
"""Page-local CURRENT financial evidence; never rewrites legacy strict peer data."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_strict_financial_health_snapshot import _report, _market_map, _industry_map
from app.stock_filter_snapshot import build_strict_financial_record
from app.search import index as search_index

WAREHOUSE = ROOT / 'data/derived/financial_ts/by_quarter'
OUT = ROOT / 'data/derived/datasets/final/good_stock_financial_current.json'
# Audited CW schema: stock/share/forecast/date fields may be populated on an
# otherwise empty report. Only statutory statements establish report content.
STATEMENT_FIELDS = ('资产总计', '负债合计', '所有者权益（或股东权益）合计',
                    '其中：营业收入', '归属于母公司所有者的净利润',
                    '扣除非经常性损益后的净利润', '经营活动产生的现金流量净额')


def period_date(period):
    return period[:4] + {'A': '1231', 'Q1': '0331', 'Q2': '0630', 'Q3': '0930'}[period[4:]]


def announcement(value):
    try:
        text = str(int(float(value)))
        if len(text) == 6:
            text = '20' + text
        return datetime.strptime(text, '%Y%m%d').date().isoformat()
    except (ValueError, TypeError, OverflowError):
        try:
            return date.fromisoformat(str(value)[:10]).isoformat()
        except (ValueError, TypeError):
            return None


def select_reports(frames, symbol, as_of):
    reports, excluded = [], []
    for period in sorted(frames, key=period_date):
        frame = frames[period]
        if symbol not in frame.index or period_date(period) > as_of.replace('-', ''):
            continue
        row = frame.loc[symbol]
        if isinstance(row, pd.DataFrame):
            raise ValueError(f'duplicate financial source rows: {period}:{symbol}')
        # A single legitimate zero/negative is never rejected: reject only an
        # entirely zero/missing statutory statement (TDX placeholder convention).
        values = [search_index._pick(row.get(key)) for key in STATEMENT_FIELDS]
        if not any(value is not None and pd.notna(value) and value != 0 for value in values):
            excluded.append({'period': period, 'reason': 'empty_statutory_statement_placeholder'})
            continue
        published = announcement(row.get('announce_date')) or announcement(row.get('财报公告日期'))
        if published and (published > as_of or published.replace('-', '') < period_date(period)):
            excluded.append({'period': period, 'reason': 'future_or_inconsistent_announcement', 'announce_date': published})
            continue
        report = _report(period, row)
        report['announce_date'] = published
        reports.append(report)
    latest = reports[-1] if reports else {}
    return reports, {
        'latest_report_period': latest.get('period'),
        'latest_report_date': latest.get('report_date'),
        'latest_announce_date': latest.get('announce_date'),
        'selection_reason': 'latest_non_placeholder_report_by_period' if latest else 'no_usable_report',
        'availability_status': ('announcement_date_verified_current_source' if latest.get('announce_date') else 'announcement_date_unknown_pending_verification') if latest else 'unavailable',
        'available_evidence': [{'period': r['period'], 'announce_date': r['announce_date'],
                                'missing_metrics': [k for k, v in r['metrics'].items() if v is None]} for r in reports],
        'excluded_reports': excluded,
        'pit_limitation': 'Current warehouse versions; first publication/version timestamps unavailable. Not a historical PIT reconstruction.',
    }


def build_snapshot(as_of=None, limit=0):
    as_of = date.fromisoformat(as_of or date.today().isoformat()).isoformat()
    # In January the previous calendar year's annual report is normally not
    # published yet. Keep the newest actually announced annual base, rather
    # than demanding a future annual file and breaking the daily refresh.
    paths = [p for p in WAREHOUSE.glob('*.parquet') if re.fullmatch(r'\d{4}(A|Q[123])', p.stem)
             and int(as_of[:4]) - 6 <= int(p.stem[:4]) <= int(as_of[:4]) and period_date(p.stem) <= as_of.replace('-', '')]
    frames, sources = {}, []
    for path in sorted(paths):
        frame = pd.read_parquet(path)
        frame.index = frame.index.map(lambda x: str(x).zfill(6))
        frames[path.stem] = frame
        st = path.stat()
        sources.append({'path': str(path.relative_to(ROOT)), 'period': path.stem, 'rows': len(frame),
                        'mtime_ns': st.st_mtime_ns, 'size': st.st_size})
    announced_annuals = []
    for period, frame in frames.items():
        if not period.endswith('A'):
            continue
        for _, row in frame.iterrows():
            published = announcement(row.get('announce_date')) or announcement(row.get('财报公告日期'))
            statement_present = any(search_index._pick(row.get(key)) not in (None, 0) for key in STATEMENT_FIELDS)
            if statement_present and (published is None or period_date(period) <= published.replace('-', '') <= as_of.replace('-', '')):
                announced_annuals.append(period)
                break
    if not announced_annuals:
        raise ValueError('no announced annual source available; publication aborted')
    annual_year = max(int(period[:4]) for period in announced_annuals)
    annual_periods = [f'{year}A' for year in range(annual_year - 4, annual_year + 1)]
    if not frames or any(period not in frames for period in annual_periods):
        raise ValueError('financial warehouse or five annual source files missing; publication aborted')
    markets, industries = _market_map(), _industry_map()
    codes = sorted(set(markets) & set.union(*(set(frame.index) for frame in frames.values())))  # union, never period intersection
    universe_count = len(codes)
    if limit:
        codes = codes[:limit]
    stocks = {}
    for n, symbol in enumerate(codes, 1):
        market = markets[symbol]
        reports, evidence = select_reports(frames, symbol, as_of)
        latest = evidence['latest_report_period']
        annual = [r for r in reports if r['period'] in annual_periods]
        # Only the selected quarter and its same-quarter historical comparators;
        # annual fallback must NOT accidentally score the previous year's Q3.
        quarters = [r for r in reports if latest and not latest.endswith('A') and r['period'].endswith(latest[4:])]
        record = build_strict_financial_record(annual + quarters, industry_level_1=industries.get((market, symbol), (None, None))[0],
                                               annual_anchor=annual_periods[-1], quarterly_anchor=latest if latest and not latest.endswith('A') else None)
        record['financial_evidence'] = evidence
        record.update({key: evidence[key] for key in ('latest_report_period', 'latest_report_date', 'latest_announce_date', 'selection_reason')})
        # Base-missing/special-industry monitor deliberately returns no period;
        # preserve actual selected report even when a metric/monitor is unavailable.
        if latest and not latest.endswith('A'):
            record['quarterly']['period'] = latest
            record['quarterly_momentum']['period'] = latest
        stocks[f'{market}:{symbol}'] = record
        if n % 500 == 0:
            print(json.dumps({'progress': n, 'total': len(codes)}), flush=True)
    return {'schema_version': 'good-stock-financial-current-v1', 'built_at': datetime.now(timezone.utc).isoformat(),
            'as_of_date': as_of, 'scope': 'current_snapshot_only', 'annual_anchor': annual_periods[-1],
            'annual_periods': annual_periods, 'quarterly_anchor': 'per_stock_latest_available',
            'sources': sources, 'partial_sample': bool(limit), 'universe_records': universe_count,
            'latest_period_counts': dict(Counter(r['latest_report_period'] or 'unavailable' for r in stocks.values())),
            'availability_counts': dict(Counter(r['financial_evidence']['availability_status'] for r in stocks.values())),
            'stocks': stocks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', default=None)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    if args.limit < 0 or (args.limit and args.output.resolve() == OUT.resolve()):
        parser.error('--limit requires a non-production --output staging path')
    payload = build_snapshot(args.as_of, args.limit)
    if not payload['stocks']:
        raise SystemExit('empty financial snapshot; last published output retained')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', dir=args.output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        os.replace(temporary, args.output)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'output': str(args.output), 'stocks': len(payload['stocks']), 'latest_period_counts': payload['latest_period_counts']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
