"""Read the exact published v5 QFQ swing record and matching real OHLC evidence."""
from __future__ import annotations

from datetime import date
import re
from typing import Any

from app.stock_filter import _swing_snapshot
from app.swing_duration import state_run
from app.swing_presentation import presentation
from app.swing_snapshot import DEFAULT_EXPORT_DIR, DEFAULT_SYNC_MANIFEST, RULE_VERSION, _digest, _source_day
from app.tdx.qfq_kline import load_tdx_qfq_daily, qfq_export_path
from app.wyckoff_events import clean_wyckoff_bars


def _chart_bars(bars, record: dict) -> list[dict]:
    earliest = None
    for field in ('last_10_peaks', 'last_10_valleys', 'candidate_peaks', 'candidate_valleys'):
        for point in record.get(field) or []:
            when = point.get('date')
            if isinstance(when, str) and (earliest is None or when < earliest):
                earliest = when
    start = max(0, len(bars)-260)
    if earliest:
        first = bars.index.searchsorted(earliest)
        start = min(start, max(0, first-7))
    return [dict(date=str(t.date()), open=float(row.open), high=float(row.high),
                 low=float(row.low), close=float(row.close), volume=float(row.volume))
            for t, row in bars.iloc[start:].iterrows()]


def _latest_qfq_response(symbol: str, market: str, source_day: str | None) -> dict[str, Any]:
    """Single-stock observation from the latest valid local QFQ bar, independent of publication."""
    from app.swing_structure import classify

    path = qfq_export_path(symbol, DEFAULT_EXPORT_DIR)
    try:
        source_hash = _digest(path)
        bars = clean_wyckoff_bars(load_tdx_qfq_daily(symbol, DEFAULT_EXPORT_DIR))
        if bars.empty:
            raise ValueError('没有有效的前复权交易日')
        bar_day = str(bars.index[-1].date())
        record = classify(bars)
        record.update(status='ok', last_bar_date=bar_day, source_sha256=source_hash)
        run = state_run(bars, str(record.get('state') or ''))
        chart = _chart_bars(bars, record)
        if _digest(path) != source_hash:
            raise ValueError('前复权文件在计算期间发生变化，请重试。')
    except (FileNotFoundError, ValueError, KeyError, IndexError, TypeError) as exc:
        return {'ok': False, 'error': {'code': 'swing_source_unavailable', 'message': str(exc)}}
    observation = {**record, **presentation(record)}
    return {'ok': True, 'data': {
        'symbol': symbol, 'market': market, 'name': None,
        'as_of_date': bar_day, 'price_basis': 'tdx_export_qfq',
        'rule_version': RULE_VERSION,
        'source_type': 'live_qfq', 'source_as_of_date': source_day,
        'snapshot_lagged': False, 'observation': observation, 'bars': chart,
        'state_duration': run,
        'duration_unavailable_reason': None if run else '逐日重放与最新结构不一致，持续时间不可核验。',
    }}


def swing_response(symbol: str, market: str = '', as_of_date: str = '') -> dict[str, Any]:
    symbol = str(symbol).strip()
    if not re.fullmatch(r'\d{6}', symbol):
        return {'ok': False, 'error': {'code': 'invalid_symbol', 'message': '请输入6位股票代码。'}}
    expected = 'sh' if symbol.startswith('6') else ('bj' if symbol.startswith('92') else 'sz')
    if market and market.lower() != expected:
        return {'ok': False, 'error': {'code': 'invalid_market', 'message': '市场与股票代码不一致。'}}
    if as_of_date:
        try:
            day = date.fromisoformat(as_of_date).isoformat()
        except ValueError:
            return {'ok': False, 'error': {'code': 'invalid_date', 'message': '日期应为YYYY-MM-DD。'}}
    else:
        try:
            day = _source_day(DEFAULT_EXPORT_DIR, DEFAULT_SYNC_MANIFEST)
        except (FileNotFoundError, KeyError, ValueError, OSError):
            day = None  # Only a comparison marker; the single-stock source file is authoritative.
        return _latest_qfq_response(symbol, expected, day)
    try:
        snapshot = _swing_snapshot(day, True)
    except (ValueError, FileNotFoundError) as exc:
        return {'ok': False, 'error': {'code': 'swing_snapshot_unavailable', 'message': str(exc)}}
    key = f'{expected}:{symbol}'
    if key not in snapshot['stocks']:
        return {'ok': False, 'error': {'code': 'not_in_universe', 'message': '当前证券不在快照样本池；不可冒充中性。'}}
    record = snapshot['stocks'][key]
    observation = {**record, **presentation(record)}
    snapshot_day = snapshot['as_of_date']
    output = {'symbol': symbol, 'market': expected, 'name': record.get('name'),
              'as_of_date': snapshot['as_of_date'], 'price_basis': snapshot['price_basis'],
              'rule_version': snapshot['rule_version'], 'observation': observation, 'bars': [],
              'source_as_of_date': day, 'snapshot_lagged': snapshot_day < day,
              'state_duration': None,
              'duration_unavailable_reason': '该股票没有可核验的同日状态与前复权交易日。'}
    if record.get('status') != 'ok' or record.get('last_bar_date') != snapshot_day:
        return {'ok': True, 'data': output}
    path = qfq_export_path(symbol, DEFAULT_EXPORT_DIR)
    if not path.is_file() or _digest(path) != record.get('source_sha256'):
        if snapshot_day < day:
            output['chart_unavailable_reason'] = '前复权源已变化，与旧快照不一致；只展示已发布结构，不绘制无法核验的旧K线。'
            output['duration_unavailable_reason'] = '旧快照的前复权源已变化，不能用新K线回推旧状态的持续时间。'
            return {'ok': True, 'data': output}
        return {'ok': False, 'error': {'code': 'swing_source_changed',
                'message': '前复权源已变化，详情K线可能与快照不一致；等待重新发布同日快照。'}}
    data = load_tdx_qfq_daily(symbol, DEFAULT_EXPORT_DIR)
    bars = clean_wyckoff_bars(data.loc[data.index <= snapshot_day])
    if bars.empty or str(bars.index[-1].date()) != snapshot_day:
        return {'ok': False, 'error': {'code': 'swing_source_stale',
                'message': '真实前复权日线与快照日期不一致。'}}
    run = state_run(bars, str(record.get('state') or ''))
    if _digest(path) != record.get('source_sha256'):
        return {'ok': False, 'error': {'code': 'swing_source_changed',
                'message': '前复权源在结构持续时间核算期间变化；请等待一致的快照与日线。'}}
    output['state_duration'] = run
    output['duration_unavailable_reason'] = None if run else '逐日重放与已发布状态不一致，持续时间不可核验。'
    earliest = None
    for field in ('last_10_peaks', 'last_10_valleys', 'candidate_peaks', 'candidate_valleys'):
        for point in record.get(field) or []:
            when = point.get('date')
            if isinstance(when, str) and (earliest is None or when < earliest):
                earliest = when
    start = max(0, len(bars)-260)
    if earliest:
        first = bars.index.searchsorted(earliest)
        start = min(start, max(0, first-7))
    output['bars'] = [dict(date=str(t.date()), open=float(row.open), high=float(row.high),
                           low=float(row.low), close=float(row.close), volume=float(row.volume))
                      for t, row in bars.iloc[start:].iterrows()]
    return {'ok': True, 'data': output}
