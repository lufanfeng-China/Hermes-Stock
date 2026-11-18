"""Point-in-time, whole-universe turnover snapshot; no fixed-share QFQ field used."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import re
from typing import Any

import pandas as pd

from app.turnover_percentile import compute_turnover_percentile

SCHEMA = 'stock-filter-turnover-percentile-v2'
FIELDS = ('turnover_percentile_1y', 'turnover_percentile_1y_as_of',
          'turnover_percentile_1y_status', 'turnover_percentile_1y_sample_count',
          'turnover_percentile_1y_current_pct', 'turnover_percentile_1y_source',
          'turnover_percentile_1y_shares', 'turnover_percentile_1y_report_period',
          'turnover_percentile_1y_report_announce', 'turnover_percentile_1y_window_start',
          'turnover_percentile_1y_current_turnover', 'turnover_percentile_1y_current_shares_source',
          'turnover_percentile_1y_report_fallback_count',
          'turnover_percentile_1y_rolling_7_trimmed_avg_pct')


def reports_from_frames(frames: dict[str, pd.DataFrame]) -> dict[str, list[dict]]:
    """Read only dated quarterly share fields, retaining missing values as masks."""
    reports: dict[str, list[dict]] = {}
    for period, frame in frames.items():
        if not re.fullmatch(r'20\d{2}(?:A|Q[1-3])', period):
            continue
        if not {'已上市流通A股', 'announce_date'} <= set(frame.columns):
            raise ValueError(f'{period} share report is missing mandatory columns')
        for code, shares, announced in zip(frame.index, frame['已上市流通A股'], frame['announce_date']):
            reports.setdefault(str(code).zfill(6), []).append({
                'period': period, 'announce_date': announced, '已上市流通A股': shares})
    return reports


def load_reports_bulk(warehouse: Path) -> dict[str, list[dict]]:
    """One read per quarter, not one parquet read per stock per quarter."""
    frames = {path.stem: pd.read_parquet(path, columns=['已上市流通A股', 'announce_date'])
              for path in sorted(warehouse.glob('20*.parquet'))
              if re.fullmatch(r'20\d{2}(?:A|Q[1-3])', path.stem)}
    if not frames:
        raise FileNotFoundError(f'no share reports under {warehouse}')
    return reports_from_frames(frames)


def build_turnover_snapshot(
    bars: pd.DataFrame, reports_by_symbol: dict[str, list[dict]], *,
    as_of_date: str, universe_keys: Iterable[str],
    on_daily: Callable[[list[dict]], Any] | None = None,
) -> tuple[dict, list[dict]]:
    """Rank each stock's seven-effective-day trimmed means through as_of_date.

    GBBQ is intentionally NOT passed as a verified event source: its dated rows
    have not been independently proven to be actual effective-date records. All
    denominator evidence here is explicitly labelled report_proxy. This is a
    conservative PIT fallback, not an assertion of actual daily share changes.
    """
    end = pd.Timestamp(as_of_date)
    if end.strftime('%Y-%m-%d') != as_of_date:
        raise ValueError('as_of_date must be YYYY-MM-DD')
    cutoff = end - pd.DateOffset(years=1)
    required = {'date', 'market', 'symbol', 'open', 'close', 'volume'}
    if missing := required - set(bars.columns):
        raise ValueError(f'missing QFQ daily fields: {sorted(missing)}')
    # Publication hands us an already aligned datetime column. Avoid duplicating
    # the multi-million-row QFQ frame just to group by stock on memory-limited WSL.
    frame = bars if pd.api.types.is_datetime64_any_dtype(bars['date']) else bars.assign(date=pd.to_datetime(bars['date']))
    if frame['date'].max() > end:
        frame = frame[frame['date'] <= end]
    groups = {f'{market}:{symbol}': group for (market, symbol), group in frame.groupby(['market', 'symbol'], sort=False)}
    stocks: dict[str, dict] = {}
    history: list[dict] = []
    for key in sorted(set(universe_keys)):
        if ':' not in key:
            raise ValueError(f'invalid universe key: {key}')
        _, symbol = key.split(':', 1)
        stock = groups.get(key)
        if stock is None or stock.empty:
            result = None
        else:
            records = stock[['date', 'open', 'close', 'volume']].to_dict('records')
            result = compute_turnover_percentile(records, reports_by_symbol.get(symbol, []))
        current_date = result.get('current_date') if result else None
        status = (result['status'] if result else 'missing_valid_bars') if current_date == as_of_date else 'stale_bar'
        samples = result.get('daily_samples', []) if result else []
        latest = samples[-1] if samples and samples[-1]['date'] == as_of_date else None
        if samples:
            batch = [{'market': key.split(':', 1)[0], 'symbol': symbol, **sample} for sample in samples]
            if on_daily is None:
                history.extend(batch)
            else:
                on_daily(batch)
        stocks[key] = {
            'turnover_percentile_1y': result['percentile'] if status == 'ok' else None,
            'turnover_percentile_1y_as_of': as_of_date,
            'turnover_percentile_1y_status': status,
            'turnover_percentile_1y_sample_count': result['sample_size'] if result else 0,
            'turnover_percentile_1y_current_pct': round(100 * latest['turnover'], 4) if latest else None,
            'turnover_percentile_1y_current_turnover': round(100 * latest['turnover'], 4) if latest else None,
            'turnover_percentile_1y_rolling_7_trimmed_avg_pct': result.get('rolling_7_trimmed_avg_pct') if result else None,
            'turnover_percentile_1y_source': latest['source'] if latest else None,
            'turnover_percentile_1y_current_shares_source': latest['source'] if latest else None,
            'turnover_percentile_1y_report_fallback_count': sum(sample['source'] == 'report_proxy' for sample in samples),
            'turnover_percentile_1y_shares': latest['shares'] if latest else None,
            'turnover_percentile_1y_report_period': result.get('latest_report_period') if result else None,
            'turnover_percentile_1y_report_announce': result.get('latest_announce_date') if result else None,
            'turnover_percentile_1y_window_start': cutoff.date().isoformat(),
        }
    return ({'schema_version': SCHEMA, 'as_of_date': as_of_date,
             'denominator': '已上市流通A股', 'share_basis': 'reported_PIT_proxy_unverified_effective_dates',
             'window': 'each_day_trailing_one_calendar_year_inclusive',
             'turnover_rule': 'volume_shares / reported_PIT_circulating_A_shares; seven_valid_days_drop_min_max_mean_remaining_five',
             'minimum_complete_windows': 120,
             'rank_rule': 'count(complete_rolling_7_trimmed_mean <= own_current_mean) / complete_window_count',
             'stocks': stocks, 'stock_count': len(stocks)}, history)
