"""Published data coverage per workbench task, never process time or file mtime.

All task rows have the same contract: data_date (ISO date or null), label.
Financial reports expose their report-period end, not their publication date.
A missing/unverifiable coverage date is explicitly unknown.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'data' / 'derived'
FINAL = 'datasets/final/'

# Each task points only to its own publication, not to a downstream snapshot or
# the last job execution.  Keys are field names in that publication's metadata.
SOURCES = {
    'sync_tdx_qfq_exports': ('cache/tdx_qfq_export_sync.json', 'latest_trading_day'),
    'refresh_industry_membership': (FINAL + 'dataset_stock_industry_current.json', 'trading_day'),
    'build_stock_filter_qfq_daily': (FINAL + 'stock_filter_qfq_daily.parquet', 'parquet:date'),
    'build_stock_filter_market_snapshot': (FINAL + 'stock_filter_market_metrics_current.json', 'qfq_as_of'),
    'build_stock_filter_fundamental_history': (FINAL + 'stock_filter_fundamental_history', 'historical_pit_files'),
    'build_stock_filter_turnover_percentile_snapshot': (FINAL + 'stock_filter_turnover_percentile_current.json', 'as_of_date'),
    'build_market_relative_strength': (FINAL + 'market_relative_strength_current.json', 'as_of_date'),
    'update_financial_ts': ('financial_ts/by_quarter', 'quarter_files'),
    'update_financial_sector_external': ('financial_sector/update_status/current_summary.json', 'latest_announced_period'),
    'build_financial_sector_health_snapshot': ('financial_sector/sector_health_snapshot.json', 'quarterly_newest_period'),
    'build_strict_financial_health_snapshot': (FINAL + 'strict_financial_health_snapshot_2025A__latest_quarter.json', 'quarterly_newest_period'),
    'build_financial_health_peer_snapshot': (FINAL + 'financial_health_peer_snapshot_current.json', 'quarterly_anchor'),
    'build_financial_snapshot': (FINAL, 'financial_snapshot_files'),
    'build_industry_metric_snapshot': (FINAL + 'dataset_industry_metric_peers_current.json', 'quarter_anchor'),
    'build_industry_relative_valuation_snapshot': (FINAL + 'dataset_industry_valuation_current.json', 'trading_day'),
    'build_good_stock_financial_snapshot': (FINAL + 'good_stock_financial_current.json', 'as_of_date'),
    'build_good_stock_undervaluation_current': (FINAL + 'good_stock_undervaluation_current.json', 'as_of_date'),
    'refresh_rps_daily': (FINAL + 'dataset_stock_rps_history.parquet', 'parquet:trading_day'),
    'build_stock_filter_pe_percentile_snapshot': (FINAL + 'stock_filter_pe_percentile_current.json', 'as_of_date'),
    # The MACD current publication only contains generated_at on individual
    # signals, not a coverage day; generated_at must not masquerade as data day.
    'rebuild_macd_signals': (FINAL + 'dataset_macd_signals_current.json', 'unavailable'),
    'build_wyckoff_snapshot': (FINAL + 'wyckoff_signals_current.json', 'as_of_date'),
    'build_concept_temperature': (FINAL + 'dataset_concept_temperature_current.json', 'as_of_date'),
    'build_industry_temperature': (FINAL + 'dataset_industry_temperature_current.json', 'as_of_date'),
}


def _iso(value: object) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _period(value: str) -> str | None:
    match = re.fullmatch(r'(20\d{2})(Q[123]|A)', value)
    if not match:
        return None
    month_day = {'Q1': '-03-31', 'Q2': '-06-30', 'Q3': '-09-30', 'A': '-12-31'}[match[2]]
    return _iso(match[1] + month_day)


@lru_cache(maxsize=128)
def _published_date(path: str, size: int, mtime_ns: int, field: str, fingerprint: tuple) -> str | None:
    """Cache by file identity/content; timestamps never become data dates."""
    file = Path(path)
    try:
        if field.startswith('parquet:'):
            import pyarrow.parquet as pq
            parquet = pq.ParquetFile(file)
            col = parquet.schema_arrow.get_field_index(field.split(':', 1)[1])
            if col < 0:
                return None
            values = []
            for i in range(parquet.metadata.num_row_groups):
                stats = parquet.metadata.row_group(i).column(col).statistics
                if stats and stats.has_min_max:
                    day = _iso(stats.max)
                    if day:
                        values.append(day)
                else:
                    # No row-group statistics means no trustworthy coverage date.
                    return None
            return max(values) if values else None
        # All JSON metadata fields are string scalars. Stream a list of rows in
        # bounded chunks rather than parsing a large historical/event payload.
        pattern = re.compile(rb'"' + re.escape(field.encode()) + rb'"\s*:\s*"([^"]+)"')
        newest = None
        with file.open('rb') as source:
            # Most published snapshots put the authoritative as-of field in
            # their header. Do not scan 477 MB of Wyckoff event history on each
            # plan request; a nested row date is not its publication date.
            if field in ('as_of_date', 'latest_trading_day'):
                header = source.read(4096)
                if header.lstrip().startswith(b'{'):
                    match = pattern.search(header)
                    if match:
                        return _iso(match.group(1).decode('utf-8', errors='replace'))
                source.seek(0)
            while chunk := source.read(1024 * 1024):
                for match in pattern.finditer(chunk):
                    value = match.group(1).decode('utf-8', errors='replace')
                    day = _period(value) if field in ('quarter_anchor', 'quarterly_anchor', 'quarterly_newest_period', 'latest_announced_period') else _iso(value)
                    if day and (newest is None or day > newest):
                        newest = day
                # A scalar metadata field at the top is sufficient for objects.
                if newest and field not in ('trading_day', 'qfq_as_of', 'as_of_date'):
                    break
                # List-valued source dates may cross chunk boundaries; overlap.
                source.seek(-min(128, source.tell()), 1)
                if source.tell() >= size - 128:
                    break
        return newest
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ImportError):
        return None


def task_freshness(task_id: str, root: Path = ROOT) -> dict[str, str | None]:
    label = '数据截至'
    source = SOURCES.get(task_id)
    if not source:
        return {'data_date': None, 'label': label}
    relative, field = source
    if field in ('quarter_anchor', 'quarterly_anchor', 'quarterly_newest_period', 'latest_announced_period', 'quarter_files', 'financial_snapshot_files'):
        label = '报告期截至'
    path = root / relative
    if field == 'unavailable':
        return {'data_date': None, 'label': label}
    if field == 'historical_pit_files':
        # Date is the newest *published v7* file, never a progress/lock timestamp
        # or an obsolete schema. Cache parsed files by immutable publication identity.
        for file in sorted(path.glob('????-??-??.json'), reverse=True):
            day = _iso(file.stem)
            if not day:
                continue
            try:
                stat = file.stat()
                with file.open('rb') as source:
                    header = source.read(256)
                if b'stock-filter-fundamental-history-v7' not in header:
                    continue
                if _valid_pit_publication(str(file), day, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                    return {'data_date': day, 'label': label}
            except OSError:
                continue
        return {'data_date': None, 'label': label}
    if field in ('quarter_files', 'financial_snapshot_files'):
        prefix = 'financial_snapshot_' if field == 'financial_snapshot_files' else ''
        days = [_period(p.stem.removeprefix(prefix)) for p in path.glob(prefix + '*.json' if prefix else '*.parquet') if p.stat().st_size > 0]
        return {'data_date': max((day for day in days if day), default=None), 'label': label}
    try:
        stat = path.stat()
        if stat.st_size <= 0:
            return {'data_date': None, 'label': label}
        fingerprint = (stat.st_ino, stat.st_ctime_ns)
        if path.suffix == '.json':
            with path.open('rb') as source:
                fingerprint += (hashlib.blake2b(source.read(4096), digest_size=8).digest(),)
        return {'data_date': _published_date(str(path), stat.st_size, stat.st_mtime_ns, field, fingerprint), 'label': label}
    except OSError:
        return {'data_date': None, 'label': label}


@lru_cache(maxsize=128)
def _valid_pit_publication(path: str, day: str, inode: int, size: int, mtime_ns: int, ctime_ns: int) -> bool:
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return (isinstance(payload, dict) and payload.get('schema_version') == 'stock-filter-fundamental-history-v7'
            and payload.get('as_of_date') == day and payload.get('financial_information_cutoff') == day
            and payload.get('valuation_price_basis') == 'raw_unadjusted_close'
            and isinstance(payload.get('stocks'), dict) and bool(payload['stocks']))
