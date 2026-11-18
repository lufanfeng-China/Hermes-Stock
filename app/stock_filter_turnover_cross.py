"""Point-in-time, whole-universe first crossing of one-year turnover percentile."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import pandas as pd

SCHEMA = 'stock-filter-turnover-percentile-v2'


def crossing_keys(day: str, final_dir: Path) -> dict[str, dict] | None:
    """Require today's >75 and all previous 30 market trading days <=75.

    None means the dated audit cannot substantiate the request; {} is an
    available audit with no qualifying securities. Never fill missing days.
    """
    final = Path(final_dir)
    try:
        manifest = json.loads((final / 'stock_filter_turnover_percentile_current.json').read_text(encoding='utf-8'))
        published = manifest.get('as_of_date')
        filename = f'stock_filter_turnover_daily_{published}.parquet'
        if (manifest.get('schema_version') != SCHEMA or
                manifest.get('daily_audit_file') != filename or day > published):
            return None
        path = final / filename
        stat = path.stat()
        return _crossings(str(path), day, stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError, TypeError):
        return None


@lru_cache(maxsize=8)
def _crossings(path: str, day: str, size: int, mtime_ns: int) -> dict[str, dict] | None:
    try:
        frame = pd.read_parquet(path, columns=['market', 'symbol', 'date', 'rolling_percentile'],
                                filters=[('date', '<=', day)])
        dates = sorted(set(frame['date']))
        if day not in dates:
            return None
        end = dates.index(day)
        if end < 30:
            return None
        needed = dates[end - 30:end + 1]
        frame = frame[frame['date'].isin(needed)]
        matches = {}
        for (market, symbol), group in frame.groupby(['market', 'symbol'], sort=False):
            values = group.set_index('date')['rolling_percentile']
            if values.index.has_duplicates or not set(needed).issubset(values.index):
                continue
            values = values.loc[needed]
            if values.isna().any():
                continue
            if float(values.iloc[-1]) > 75 and (values.iloc[:-1] <= 75).all():
                matches[f'{market}:{symbol}'] = {'cross_date': day,
                    'previous_30_start': needed[0], 'percentile': float(values.iloc[-1])}
        return matches
    except (OSError, ValueError, KeyError, ImportError):
        return None
