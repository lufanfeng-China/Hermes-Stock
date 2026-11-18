"""Strict local Tongdaxin front-adjusted daily bars for the stock-filter chart."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re

import numpy as np

from app.config import TDX_QFQ_EXPORT_DIR
from app.tdx.qfq_kline import load_tdx_qfq_daily, qfq_export_path

MAX_BARS = 2000


def _error(code: str, message: str) -> dict:
    return {'ok': False, 'error': {'code': code, 'message': message}}


def trend_response(market: str, symbol: str, as_of_date: str, *, limit: int = 300,
                   export_dir: Path | None = None) -> dict:
    """Never substitute a raw series or silently use a different last trading day."""
    if not re.fullmatch(r'\d{6}', symbol or ''):
        return _error('invalid_symbol', 'symbol must be six digits')
    if market not in ('sz', 'sh', 'bj') or market.upper() != qfq_export_path(symbol, export_dir or TDX_QFQ_EXPORT_DIR).name[:2]:
        return _error('invalid_market', 'market does not match the stock symbol')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', as_of_date or ''):
        return _error('invalid_date', 'as_of_date must be YYYY-MM-DD')
    try:
        day = date.fromisoformat(as_of_date)
    except ValueError:
        return _error('invalid_date', 'as_of_date is not a calendar date')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BARS:
        return _error('invalid_limit', f'limit must be between 1 and {MAX_BARS}')

    try:
        bars = load_tdx_qfq_daily(symbol, export_dir or TDX_QFQ_EXPORT_DIR)
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _error('qfq_export_unavailable', str(exc))
    bars = bars.loc[bars.index <= as_of_date]
    values = bars[['open', 'high', 'low', 'close', 'volume']]
    valid = np.isfinite(values).all(axis=1) & (values[['open', 'high', 'low', 'close']] > 0).all(axis=1)
    valid &= values['volume'] > 0
    bars = bars.loc[valid]
    if bars.empty or bars.index[-1].date() != day:
        return _error('qfq_source_stale', f'QFQ export has no valid traded bar on {as_of_date}')
    result = [
        {'trading_day': str(timestamp.date()),
         **{field: float(row[field]) for field in ('open', 'high', 'low', 'close', 'volume')}}
        for timestamp, row in bars.iloc[-limit:].iterrows()
    ]
    return {'ok': True, 'market': market, 'symbol': symbol, 'as_of_date': as_of_date,
            'price_basis': 'tdx_export_qfq', 'bars': result}
