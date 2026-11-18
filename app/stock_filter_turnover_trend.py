"""Read published point-in-time turnover-percentile history for one stock."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from app.config import DERIVED_FINAL_DIR
from app.turnover_percentile import compute_turnover_percentile, read_stock_share_reports

FINAL = DERIVED_FINAL_DIR
QFQ_DAILY = FINAL / 'stock_filter_qfq_daily.parquet'
SHARE_WAREHOUSE = FINAL.parent.parent / 'financial_ts' / 'by_quarter'
SCHEMA = 'stock-filter-turnover-percentile-v2'


def _error(code: str, message: str) -> dict:
    return {'ok': False, 'error': {'code': code, 'message': message}}


def turnover_trend_response(market: str, symbol: str, as_of_date: str, *,
                            final_dir: Path | None = None) -> dict:
    """Never rank against the current-day window; only read precomputed daily PIT ranks."""
    if (market not in ('sh', 'sz', 'bj') or not re.fullmatch(r'\d{6}', symbol or '')
            or (market == 'sh' and not symbol.startswith('6'))
            or (market == 'sz' and not symbol.startswith(('00', '30')))
            or (market == 'bj' and not symbol.startswith('92'))):
        return _error('invalid_stock', '证券市场或代码无效')
    try:
        day = date.fromisoformat(as_of_date)
        if day.isoformat() != as_of_date:
            raise ValueError('invalid ISO date')
    except (TypeError, ValueError):
        return _error('invalid_date', '筛选日期必须是有效的 YYYY-MM-DD')
    final = Path(final_dir) if final_dir is not None else FINAL
    try:
        manifest = json.loads((final / 'stock_filter_turnover_percentile_current.json').read_text(encoding='utf-8'))
        published = manifest.get('as_of_date')
        filename = manifest.get('daily_audit_file')
        if (manifest.get('schema_version') != SCHEMA or
                not re.fullmatch(r'\d{4}-\d{2}-\d{2}', published or '') or
                filename != f'stock_filter_turnover_daily_{published}.parquet' or
                as_of_date > published):
            return _error('turnover_trend_unavailable', '换手分位逐日快照版本或日期不匹配')
        path = final / filename
        if as_of_date == published:
            frame = pd.read_parquet(path, filters=[('market', '==', market),
                                                    ('symbol', '==', symbol),
                                                    ('date', '<=', as_of_date)])
        else:
            # A published trend only retains the last year relative to its
            # publication day. Recomputing this single stock is required for a
            # historical selected date's *entire* preceding year, with no later
            # bar/report allowed into its percentile.
            qfq = pd.read_parquet(QFQ_DAILY, columns=['date', 'market', 'symbol', 'open', 'close', 'volume'],
                                  filters=[('market', '==', market), ('symbol', '==', symbol),
                                           ('date', '<=', pd.Timestamp(as_of_date))])
            if qfq.empty or pd.Timestamp(qfq['date'].max()).date().isoformat() != as_of_date:
                return _error('turnover_trend_unavailable', '所选交易日的前复权源日线缺失')
            reports = read_stock_share_reports(SHARE_WAREHOUSE, symbol)
            result = compute_turnover_percentile(qfq.to_dict('records'), reports)
            if result['current_date'] != as_of_date:
                return _error('turnover_trend_unavailable', '所选交易日的逐日换手证据缺失')
            frame = pd.DataFrame(result['daily_samples'])
        needed = {'date', 'rolling_percentile', 'rolling_7_trimmed_avg_pct', 'eligible_window_count'}
        if not needed.issubset(frame.columns) or frame.empty:
            return _error('turnover_trend_unavailable', '该股逐日换手分位证据缺失')
        frame['date'] = pd.to_datetime(frame['date']).dt.strftime('%Y-%m-%d')
        frame = frame.sort_values('date')
        if frame['date'].iloc[-1] != as_of_date or frame['date'].duplicated().any():
            return _error('turnover_trend_unavailable', '所选交易日的逐日证据缺失或重复')
        if as_of_date == published:
            stock_row = (manifest.get('stocks') or {}).get(f'{market}:{symbol}')
            pct = frame.iloc[-1]['rolling_percentile']
            if not isinstance(stock_row, dict) or (None if pd.isna(pct) else float(pct)) != stock_row.get('turnover_percentile_1y'):
                return _error('turnover_trend_unavailable', '趋势末点与筛选结果的分位不一致')
        cutoff = (pd.Timestamp(day) - pd.DateOffset(years=1)).date().isoformat()
        frame = frame[frame['date'] >= cutoff]
        rows = []
        for record in frame.to_dict('records'):
            pct = record['rolling_percentile']
            avg = record['rolling_7_trimmed_avg_pct']
            count = record['eligible_window_count']
            rows.append({'date': record['date'],
                         'percentile': None if pd.isna(pct) else float(pct),
                         'trimmed_average_pct': None if pd.isna(avg) else float(avg),
                         'sample_count': None if pd.isna(count) else int(count),
                         'source': record.get('source')})
        return {'ok': True, 'market': market, 'symbol': symbol,
                'as_of_date': as_of_date, 'window_start': cutoff,
                'sample_count': len(rows), 'rows': rows,
                'definition': '7日换手率去最高最低后5日平均；当日与当时过去一年完整窗口比较；至少120个窗口',
                'share_basis': manifest.get('share_basis')}
    except (OSError, ValueError, KeyError, ImportError) as exc:
        return _error('turnover_trend_unavailable', f'逐日换手分位证据不可读取：{exc}')
