"""Aggregate a Wyckoff historical quality audit without changing event rules."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from collections import Counter
from app.tdx.qfq_kline import load_tdx_qfq_daily
from app.wyckoff_events import clean_wyckoff_bars
import math


def select_pool(coverage, names):
    """Current non-ST reference ∩ readable QFQ ∩ end-date coverage, not PIT universe."""
    pool, reasons = set(), Counter()
    for row in coverage:
        key = (row['market'], row['symbol'])
        name = names.get((key[0].lower(), key[1]), '')
        if not name:
            reasons['not_in_current_names'] += 1
        elif name.strip().upper().startswith(('ST', '*ST', 'S')):
            reasons['current_st_or_s'] += 1
        elif row['end_covered'] != 'True' or row['status'] == 'failed':
            reasons['source_not_asof'] += 1
        elif int(row['traded_bars']) <= 40:
            reasons['insufficient_bars'] += 1
        else:
            pool.add(key)
    return pool, dict(reasons)


def analyze(input_dir, names):
    """Validate scanner outputs, then stream separate raw and current-pool counts.

    Year-of-event status is measured at resolution_as_of; resolution-year counts
    use confirmation/invalidated dates independently. A later-invalidated event
    may have been confirmed earlier, so these columns must not be subtracted.
    """
    import csv
    import hashlib
    import json
    from pathlib import Path
    base = Path(input_dir)
    manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
    with (base / 'coverage.csv').open(newline='', encoding='utf-8') as stream:
        coverage = list(csv.DictReader(stream))
    if len(coverage) != manifest['symbols_total']:
        raise AssertionError('coverage rows disagree with manifest')
    coverage_keys = {(r['market'], r['symbol']) for r in coverage}
    if len(coverage_keys) != len(coverage):
        raise AssertionError('duplicate security in coverage')
    pool, reasons = select_pool(coverage, names)
    coverage_by_status = Counter(r['status'] for r in coverage)
    by_year = Counter()
    by_resolution = Counter()
    by_kind = Counter()
    raw_by_year = Counter()
    margin_tiny = Counter()
    ever_confirmed_later_invalidated = 0
    raw_events = eligible_events = 0
    samples_by_stratum = {}
    with (base / 'events.csv').open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            raw_events += 1
            key = (row['market'], row['symbol'])
            if key not in coverage_keys:
                raise AssertionError(f'event without coverage: {key}')
            year, kind, status = row['date'][:4], row['type'], row['status']
            raw_by_year[(year, kind, status)] += 1
            if key not in pool:
                continue
            eligible_events += 1
            by_year[(year, kind, status)] += 1
            by_kind[kind] += 1
            margin = margin_fraction(row)
            if margin < -1e-12:
                raise AssertionError(f'negative event penetration: {row}')
            if margin < 0.005:
                margin_tiny[kind] += 1
            for field in ('box_lower', 'box_upper', 'high', 'low', 'close', 'volume'):
                if field in row and row[field] and not math.isfinite(float(row[field])):
                    raise ValueError(f'nonfinite {field}: {key} {row["date"]}')
            for field, state in (('confirmation_date', 'confirmed'), ('invalidated_date', 'invalidated')):
                resolved = row[field]
                if resolved:
                    if resolved < row['date'] or resolved > manifest['resolution_as_of']:
                        raise AssertionError(f'invalid lifecycle date: {row}')
                    by_resolution[(resolved[:4], kind, state)] += 1
            if row['confirmation_date'] and row['invalidated_date']:
                if row['invalidated_date'] <= row['confirmation_date']:
                    raise AssertionError(f'out-of-order lifecycle: {row}')
                ever_confirmed_later_invalidated += 1
            stratum = (year, kind, status)
            digest = hashlib.sha256(('|'.join((row['market'], row['symbol'], row['date'], kind))).encode()).hexdigest()
            if stratum not in samples_by_stratum or digest < samples_by_stratum[stratum][0]:
                samples_by_stratum[stratum] = (digest, dict(row, current_name=names[(row['market'].lower(), row['symbol'])], margin_pct=round(margin * 100, 5)))
    if raw_events != manifest['events_total']:
        raise AssertionError('event rows disagree with manifest')
    with (base / 'year_type_status.csv').open(newline='', encoding='utf-8') as stream:
        actual = {(r['year'], r['type'], r['status']): int(r['count']) for r in csv.DictReader(stream)}
    for key in set(raw_by_year) | set(actual):
        if raw_by_year[key] != actual.get(key, 0):
            raise AssertionError(f'raw year/type/status disagrees: {key}')
    years = sorted({y for y, _, _ in raw_by_year} | {y for y, _, _ in by_year})
    kinds = ('Spring', 'UT', 'SOS', 'SOW', 'LPS', 'LPSY')
    states = ('candidate', 'confirmed', 'invalidated')
    years_resolution = sorted({y for y, _, _ in by_resolution} | set(years))
    summary = dict(
        source_manifest=manifest, raw_symbols=len(coverage), raw_events=raw_events,
        coverage_by_status=dict(coverage_by_status),
        current_eligible_symbols=len(pool), excluded_reasons=reasons,
        eligible_events=eligible_events, eligible_by_type={k: by_kind[k] for k in kinds},
        event_year_type_status={y: {k: {s: by_year[(y, k, s)] for s in states} for k in kinds} for y in years},
        resolution_year_type={y: {k: {s: by_resolution[(y, k, s)] for s in ('confirmed','invalidated')} for k in kinds} for y in years_resolution},
        ever_confirmed_then_invalidated=ever_confirmed_later_invalidated,
        margin_below_half_percent={k: margin_tiny[k] for k in kinds},
        margin_threshold_is_diagnostic_only=0.005,
        sample_rule='minimum SHA256(market|symbol|event_date|type) per event year × type × as-of status',
    )
    return summary, [v[1] for _, v in sorted(samples_by_stratum.items())]


def publish(input_dir, names, with_durations=False):
    """Write only post-audit derived files; never overwrite scanner's four files."""
    import csv
    from datetime import datetime, timezone
    import hashlib
    import json
    import os
    from pathlib import Path
    import tempfile
    base = Path(input_dir)
    if not (base / 'manifest.json').is_file():
        raise FileNotFoundError('scanner manifest must exist before reporting')
    summary, samples = analyze(base, names)
    with (base / 'coverage.csv').open(newline='', encoding='utf-8') as f:
        coverage = list(csv.DictReader(f))
    pool, _ = select_pool(coverage, names)
    duration_rows = []
    if with_durations:
        manifest = summary['source_manifest']
        counts = summarize_durations(base, pool, manifest['resolution_as_of'], manifest['source'])
        if sum(counts[(kind, state)] for kind in summary['eligible_by_type']
               for state in ('invalidated', 'unresolved_asof')) != summary['eligible_events']:
            raise AssertionError('lifecycle duration counts do not sum to eligible events')
        for kind in summary['eligible_by_type']:
            duration_rows.append(dict(type=kind, total=summary['eligible_by_type'][kind],
                                      invalidated=counts[(kind, 'invalidated')],
                                      within_1_valid_bar=counts[(kind, 'within_1_valid_bar')],
                                      within_5_valid_bars=counts[(kind, 'within_5_valid_bars')],
                                      unresolved_asof=counts[(kind, 'unresolved_asof')],
                                      invalidated_bar_sum=counts[(kind, 'loss_bar_sum')]))
        summary['loss_duration_by_type'] = {row['type']: row for row in duration_rows}

    def atomic_write(filename, payload):
        target = base / filename
        with tempfile.NamedTemporaryFile(dir=base, prefix='.' + filename + '.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(payload)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        os.replace(temporary, target)

    def csv_bytes(fields, rows):
        from io import StringIO
        sink = StringIO(newline='')
        writer = csv.DictWriter(sink, fields)
        writer.writeheader()
        writer.writerows(rows)
        return sink.getvalue().encode('utf-8')

    atomic_write('quality_summary.json', (json.dumps(summary, ensure_ascii=False, indent=2) + '\n').encode())
    sample_fields = list(samples[0]) if samples else ['market', 'symbol', 'date', 'type', 'status', 'current_name', 'margin_pct']
    atomic_write('stratified_samples.csv', csv_bytes(sample_fields, samples))
    atomic_write('current_non_st_pool.csv', csv_bytes(['market', 'symbol', 'name'],
                 (dict(market=m, symbol=c, name=names[(m.lower(), c)]) for m, c in sorted(pool))))
    atomic_write('year_type_status_current_pool.csv', csv_bytes(['year', 'type', 'status', 'count'],
                 (dict(year=y, type=k, status=s, count=n)
                  for y, kinds in summary['event_year_type_status'].items()
                  for k, states in kinds.items() for s, n in states.items())))
    atomic_write('year_type_resolution_current_pool.csv', csv_bytes(['year', 'type', 'resolution', 'count'],
                 (dict(year=y, type=k, resolution=s, count=n)
                  for y, kinds in summary['resolution_year_type'].items()
                  for k, states in kinds.items() for s, n in states.items())))
    if with_durations:
        atomic_write('loss_duration_current_pool.csv', csv_bytes(
            ['type', 'total', 'invalidated', 'within_1_valid_bar', 'within_5_valid_bars',
             'unresolved_asof', 'invalidated_bar_sum'], duration_rows))
    files = ['events.csv', 'coverage.csv', 'year_type_status.csv', 'manifest.json',
             'quality_summary.json', 'stratified_samples.csv', 'current_non_st_pool.csv',
             'year_type_status_current_pool.csv', 'year_type_resolution_current_pool.csv']
    if with_durations:
        files.append('loss_duration_current_pool.csv')
    hashes = {}
    for filename in files:
        h = hashlib.sha256()
        with (base / filename).open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
        hashes[filename] = h.hexdigest()
    report_manifest = dict(generated_at=datetime.now(timezone.utc).isoformat(),
                           current_names_source='app.search.index._stock_name_lookup, current TDX security list; not historical PIT',
                           current_eligible_symbols=len(pool), raw_events=summary['raw_events'],
                           eligible_events=summary['eligible_events'], files_sha256=hashes,
                           summary_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    atomic_write('report_manifest.json', (json.dumps(report_manifest, ensure_ascii=False, indent=2) + '\n').encode())
    return report_manifest


def duration_for_symbol(rows, valid_dates):
    """Count loss latency in this security's own valid QFQ bars, not weekdays."""
    positions = {day: i for i, day in enumerate(valid_dates)}
    if len(positions) != len(valid_dates):
        raise ValueError('duplicate effective QFQ trading dates')
    counts = Counter()
    for row in rows:
        kind, date, loss = row['type'], row['date'], row['invalidated_date']
        if date not in positions:
            raise AssertionError(f'event date missing in clean source: {date}')
        if not loss:
            counts[(kind, 'unresolved_asof')] += 1
            continue
        if loss not in positions:
            raise AssertionError(f'invalidation date missing in clean source: {loss}')
        duration = positions[loss] - positions[date]
        if duration < 1:
            raise AssertionError(f'nonpositive loss duration: {row}')
        counts[(kind, 'invalidated')] += 1
        if duration <= 1:
            counts[(kind, 'within_1_valid_bar')] += 1
        if duration <= 5:
            counts[(kind, 'within_5_valid_bars')] += 1
        counts[(kind, 'loss_bar_sum')] += duration
    return counts


def summarize_durations(input_dir, pool, asof, source):
    """Re-open each cohort's QFQ once; exact loss latency on effective bars."""
    import csv
    from itertools import groupby
    from pathlib import Path
    from app.wyckoff_events import _day
    total = Counter()
    previous_key = None
    with (Path(input_dir) / 'events.csv').open(newline='', encoding='utf-8') as stream:
        rows = csv.DictReader(stream)
        for key, grouped in groupby(rows, lambda r: (r['market'], r['symbol'])):
            if previous_key is not None and key <= previous_key:
                raise AssertionError('events.csv must be sorted by unique market/symbol')
            previous_key = key
            if key not in pool:
                continue
            relevant = list(grouped)
            clean = clean_wyckoff_bars(load_tdx_qfq_daily(key[1], Path(source)))
            import numpy as np
            if not np.isfinite(clean[['open', 'high', 'low', 'close', 'volume']].to_numpy(dtype=float)).all():
                raise ValueError(f'nonfinite effective QFQ bar for {key}')
            valid_dates = [_day(idx) for idx in clean.index if _day(idx) <= asof]
            total.update(duration_for_symbol(relevant, valid_dates))
    return total


def margin_fraction(row):
    """Absolute penetration of event-day OHLC beyond its frozen boundary."""
    boundary = float(row['boundary'])
    if not math.isfinite(boundary) or boundary <= 0:
        raise ValueError(f'invalid frozen boundary: {boundary}')
    kind = row['type']
    key = {'Spring': 'low', 'SOW': 'close', 'LPSY': 'close',
           'UT': 'high', 'SOS': 'close', 'LPS': 'close'}[kind]
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f'nonfinite event {kind} {key}: {value}')
    return (boundary - value) / boundary if kind in ('Spring', 'SOW', 'LPSY') else (value - boundary) / boundary


def main():
    import argparse
    import json
    from app.search.index import _stock_name_lookup
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', required=True, type=Path,
                        help='Published audit directory with manifest.json, events.csv, coverage.csv')
    args = parser.parse_args()
    print(json.dumps(publish(args.input_dir, _stock_name_lookup(), with_durations=True), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
