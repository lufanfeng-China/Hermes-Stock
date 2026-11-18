"""Local TDX index close vs. seven simple moving averages (daily bars)."""
from __future__ import annotations

import math
import struct
from datetime import datetime
from pathlib import Path

from app.config import TONGDAXIN_DIR

INDEX_DEFS = (
    ('sh', '000001', '上证指数'),
    ('sz', '399001', '深证成指'),
    ('sz', '399006', '创业板指'),
    ('sh', '000680', '科创综指'),
)
MA_PERIODS = (240, 120, 60, 30, 20, 10, 5)
_DAY = struct.Struct('<IIIIIfII')


def _index_bars(path: Path) -> list[tuple[str, float]]:
    data = path.read_bytes()
    if len(data) % _DAY.size:
        raise ValueError('日线文件记录不完整')
    closes: dict[str, float] = {}
    for date_int, _open, _high, _low, raw_close, _amount, _volume, _reserved in _DAY.iter_unpack(data):
        try:
            day = datetime.strptime(str(date_int), '%Y%m%d').date().isoformat()
        except ValueError:
            continue
        close = raw_close / 100.0
        if math.isfinite(close) and close > 0:
            closes[day] = close
    return sorted(closes.items())


def index_temperature_response(tdx_dir: Path | str = TONGDAXIN_DIR) -> dict:
    """Use each index's latest valid local daily close; missing MAs remain unknown."""
    root = Path(tdx_dir)
    rows = []
    for market, symbol, name in INDEX_DEFS:
        row = {'market': market, 'symbol': symbol, 'name': name,
               'as_of_date': None, 'close': None, 'status': 'missing',
               'above': [], 'below': [], 'unavailable': [], 'moving_averages': {}}
        path = root / 'vipdoc' / market / 'lday' / f'{market}{symbol}.day'
        try:
            bars = _index_bars(path)
        except (OSError, ValueError) as exc:
            row['error'] = str(exc)
            bars = []
        if bars:
            row['as_of_date'], row['close'] = bars[-1]
            closes = [close for _, close in bars]
            row['status'] = 'ok' if len(closes) >= max(MA_PERIODS) else 'insufficient'
            for period in MA_PERIODS:
                if len(closes) < period:
                    row['unavailable'].append(period)
                    continue
                ma = sum(closes[-period:]) / period
                row['moving_averages'][str(period)] = round(ma, 4)
                (row['above'] if row['close'] > ma else row['below']).append(period)
        else:
            row['unavailable'] = list(MA_PERIODS)
        rows.append(row)
    latest = max((r['as_of_date'] for r in rows if r['as_of_date']), default=None)
    for row in rows:
        if row['as_of_date'] and row['as_of_date'] != latest:
            row['status'] = 'stale'
    return {'ok': True, 'source': '本地通达信指数日线收盘价', 'latest_date': latest,
            'indices': rows}


def index_history_response(market: str, symbol: str,
                           tdx_dir: Path | str = TONGDAXIN_DIR) -> dict:
    """Whitelisted index OHLCV and causal 5+5 markers from the same raw .day file.

    Compute pivots on the complete valid history before limiting chart bars;
    the fifth following bar is required for every confirmed marker.
    """
    identity = next(((m, s, name) for m, s, name in INDEX_DEFS
                     if market == m and symbol == s), None)
    if identity is None:
        return {'ok': False, 'error': {'code': 'invalid_index', 'message': '仅支持四张大盘温度卡对应的指数'}}
    path = Path(tdx_dir) / 'vipdoc' / market / 'lday' / f'{market}{symbol}.day'
    try:
        raw = path.read_bytes()
        if len(raw) % _DAY.size:
            raise ValueError('指数日线文件记录不完整')
        by_day: dict[str, dict] = {}
        for date_int, opened, high, low, close, _amount, volume, _reserved in _DAY.iter_unpack(raw):
            try:
                day = datetime.strptime(str(date_int), '%Y%m%d').date().isoformat()
            except ValueError:
                continue
            if not (opened > 0 and low > 0 and low <= min(opened, close)
                    and high >= max(opened, close) and volume >= 0):
                continue
            by_day[day] = {'date': day, 'trading_day': day,
                           'open': opened / 100, 'high': high / 100,
                           'low': low / 100, 'close': close / 100,
                           'volume': volume}
        all_bars = [by_day[day] for day in sorted(by_day)]
        if not all_bars:
            raise ValueError('无有效指数日线')
    except (OSError, ValueError) as exc:
        return {'ok': False, 'error': {'code': 'index_history_unavailable', 'message': str(exc)}}

    from app.swing_structure import _canonical, _pending, _pivots
    import numpy as np

    highs = np.array([b['high'] for b in all_bars], dtype=float)
    lows = np.array([b['low'] for b in all_bars], dtype=float)
    raw_peaks, raw_valleys, _ = _pivots(highs, lows)
    peaks, valleys, _ = _canonical(raw_peaks, raw_valleys, highs, lows)
    visible = all_bars[-1000:]
    first_day = visible[0]['date']
    def points(indices: list[int], kind: str, confirmed: bool = True) -> list[dict]:
        result = []
        for i in indices:
            if all_bars[i]['date'] < first_day:
                continue
            item = {'date': all_bars[i]['date'],
                    kind: round(float(highs[i] if kind == 'high' else lows[i]), 4)}
            if confirmed:
                item['confirmed'] = all_bars[i + 5]['date']
            else:
                item['waiting_bars'] = len(all_bars) - 1 - i
            result.append(item)
        return result

    return {'ok': True, 'market': market, 'symbol': symbol, 'name': identity[2],
            'price_basis': 'tdx_index_raw', 'source': '本地通达信指数原始日线',
            'as_of_date': all_bars[-1]['date'], 'bars': visible,
            'observation': {
                'last_10_peaks': points(peaks[-10:], 'high'),
                'last_10_valleys': points(valleys[-10:], 'low'),
                'candidate_peaks': points(_pending(highs, lows, 'high'), 'high', False),
                'candidate_valleys': points(_pending(highs, lows, 'low'), 'low', False),
            }}
