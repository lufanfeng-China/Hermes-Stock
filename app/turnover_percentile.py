"""Seven-effective-day trimmed turnover rank with conservative share provenance.

GBBQ input is an *independent, normalized snapshot*, not a dependency on the
external decoder. To produce it, the upstream GbbqReader.get_df yields category
5/9 rows: use its ``datetime``, ``category`` and
``songgu_qianzongguben`` (v3). v3 represents POST-event circulating A shares
in 10,000-share units, despite the upstream decoder's misleading field name.
Never mark quarter-end records effective solely on their GBBQ date: supply
``verified_effective_date=True`` only after independent effective-date validation.
Unverified events are ignored; the last strictly earlier announced financial
report is then a proxy, not a verified actual historical share ledger.
"""
from __future__ import annotations

from datetime import date, datetime
from bisect import bisect_left, bisect_right, insort
from collections import deque
from math import isfinite
from pathlib import Path
import re


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, float) and isfinite(value) and value.is_integer():
        value = int(value)
    text = str(value or "").replace("-", "")
    if len(text) == 6 and text.isdigit():
        text = "20" + text
    try:
        return datetime.strptime(text, "%Y%m%d").date() if len(text) == 8 else None
    except ValueError:
        return None


def _positive(value):
    try:
        number = float(value)
        return number if isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def _cutoff(day):
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def read_stock_share_reports(warehouse_dir: Path, symbol: str) -> list[dict]:
    """Read per-stock quarter files, keeping invalid latest values for PIT masking."""
    import pyarrow.parquet as pq

    if not re.fullmatch(r"\d{6}", symbol):
        raise ValueError("invalid stock code")
    rows = []
    for path in sorted(Path(warehouse_dir).glob("*.parquet")):
        if not re.fullmatch(r"20\d{2}(?:Q[1-3]|A)", path.stem):
            continue
        columns = pq.ParquetFile(path).schema_arrow.names
        required = {"code", "已上市流通A股", "announce_date"}
        if missing := required.difference(columns):
            raise ValueError(f"incomplete share report {path}: missing {sorted(missing)}")
        for row in pq.read_table(path, columns=["已上市流通A股", "announce_date"],
                                 filters=[("code", "==", symbol)]).to_pylist():
            rows.append({"period": path.stem, **row})
    return rows


def compute_turnover_percentile(bars, reports, *, gbbq_events=()):
    """Rank the seven-effective-day trimmed turnover against complete windows.

    Volumes and shares are *shares*, not lots. Current date is the latest valid
    bar date. A reported denominator is an announced-report proxy (not an actual
    daily effective-date fact). No report is projected backwards in time. Each
    published day's rank uses its own inclusive trailing calendar year; fewer
    than 120 complete windows yields a null percentile.
    """
    valid = []
    for row in bars:
        day = _day(row.get("date"))
        volume = _positive(row.get("volume"))
        if day and volume and _positive(row.get("open")) and _positive(row.get("close")):
            valid.append((day, volume))
    valid.sort()
    if not valid:
        return {"status": "missing_valid_bars", "percentile": None, "current_turnover": None,
                "sample_size": 0, "current_date": None, "daily_samples": []}
    end = valid[-1][0]
    cutoff = _cutoff(end)
    eligible = []
    for row in reports:
        day = _day(row.get("announce_date"))
        period = str(row.get("period") or "")
        if day and re.fullmatch(r"20\d{2}(?:Q[1-3]|A)", period):
            order = (int(period[:4]), {"Q1": 1, "Q2": 2, "Q3": 3, "A": 4}[period[4:]])
            eligible.append((day, order, row))
    # Only independently verified effective dates may be treated as events.
    events = []
    for row in gbbq_events:
        day = _day(row.get("date", row.get("datetime")))
        shares = _positive(row.get("post_shares_v3", row.get("songgu_qianzongguben")))
        if day and row.get("verified_effective_date") is True and row.get("category") in (5, 9):
            events.append((day, shares * 10000 if shares else None))
    events.sort(key=lambda x: x[0])
    all_days = []
    current_source = None
    current_report = None
    for day, volume in valid:
        known = [item for item in eligible if item[0] < day]
        latest = max(known, key=lambda x: (x[1], x[0])) if known else None
        effective = [event for event in events if event[0] <= day]
        event = effective[-1] if effective else None
        # A newer report may supersede a previously verified event. Without
        # evidence that they describe the same share basis, prefer report proxy.
        if event and (latest is None or event[0] >= latest[0]):
            shares = event[1]
            source = "gbbq_verified"
        else:
            shares = _positive(latest[2].get("已上市流通A股")) if latest else None
            source = "report_proxy" if latest else None
        if day == end:
            current_source = source
            current_report = latest
        if shares:
            all_days.append({"date": day.isoformat(), "turnover": volume / shares,
                           "shares": shares, "source": source,
                           "report_period": latest[2]["period"] if latest else None,
                           "report_announce": latest[0].isoformat() if latest else None})
    # Complete windows use valid turnover observations rather than calendar
    # adjacency. Invalid/no-share days never enter the seven observations.
    windows = []
    for i in range(6, len(all_days)):
        seven = sorted(row['turnover'] for row in all_days[i - 6:i + 1])
        windows.append((all_days[i]['date'], sum(seven[1:-1]) / 5))
    output = []
    trailing = deque()
    ranked = []
    cursor = 0
    for row in all_days:
        day_text = row['date']
        if day_text < cutoff.isoformat():
            continue
        while cursor < len(windows) and windows[cursor][0] <= day_text:
            window_day, value = windows[cursor]
            trailing.append((window_day, value))
            insort(ranked, value)
            cursor += 1
        own_cutoff = _cutoff(_day(day_text)).isoformat()
        while trailing and trailing[0][0] < own_cutoff:
            ranked.pop(bisect_left(ranked, trailing.popleft()[1]))
        trimmed = windows[cursor - 1][1] if cursor and windows[cursor - 1][0] == day_text else None
        count = len(ranked)
        output.append({**row, 'rolling_7_trimmed_avg_pct': round(100 * trimmed, 6) if trimmed is not None else None,
                       'rolling_percentile': round(100 * bisect_right(ranked, trimmed) / count, 2)
                       if trimmed is not None and count >= 120 else None,
                       'eligible_window_count': count})
    latest = output[-1] if output and output[-1]['date'] == end.isoformat() else None
    current = latest['turnover'] if latest else None
    status = ('missing_current_shares' if current is None else
              'insufficient_history' if latest['eligible_window_count'] < 120 else 'ok')
    return {"status": status,
            "percentile": latest['rolling_percentile'] if latest else None,
            "current_turnover": current, "sample_size": latest['eligible_window_count'] if latest else 0,
            "rolling_7_trimmed_avg_pct": latest['rolling_7_trimmed_avg_pct'] if latest else None,
            "daily_samples": output,
            "current_date": end.isoformat(), "window_start": cutoff.isoformat(),
            "denominator_source": current_source,
            "latest_report_period": current_report[2]["period"] if current_report is not None else None,
            "latest_announce_date": current_report[0].isoformat() if current_report else None,
            "first_valid_date": output[0]["date"] if output else None,
            "last_valid_date": output[-1]["date"] if output else None}
