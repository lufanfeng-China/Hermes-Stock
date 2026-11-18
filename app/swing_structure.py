"""Causal 5+5 QFQ swing classification (independent research main-state v5).

Input must already be front-adjusted. This module never fetches or adjusts prices.
A point is visible only on its fifth subsequent *valid trading bar*; re-run on
historical prefixes rather than backfilling today's canonical chain into history.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from app.wyckoff_events import clean_wyckoff_bars


def _pivots(high, low):
    if len(high) < 11:
        return [], [], 0
    hw, lw = sliding_window_view(high, 11), sliding_window_view(low, 11)
    hp = (hw[:, 5] > hw[:, :5].max(axis=1)) & (hw[:, 5] >= hw[:, 6:].max(axis=1))
    vp = (lw[:, 5] < lw[:, :5].min(axis=1)) & (lw[:, 5] <= lw[:, 6:].min(axis=1))
    ambiguous = hp & vp
    return (np.flatnonzero(hp & ~ambiguous) + 5).tolist(), (np.flatnonzero(vp & ~ambiguous) + 5).tolist(), int(ambiguous.sum())


def _canonical(peaks, valleys, high, low):
    kept, removed = [], []
    for i, kind in sorted([(i, 'P') for i in peaks] + [(i, 'V') for i in valleys]):
        if not kept or kept[-1][1] != kind:
            kept.append((i, kind))
            continue
        old, _ = kept[-1]
        stronger = high[i] > high[old] if kind == 'P' else low[i] < low[old]
        if stronger:
            removed.append((old, kind, i, 'replaced_by_stronger'))
            kept[-1] = (i, kind)
        else:
            removed.append((i, kind, old, 'weaker_or_equal_kept_earlier'))
    return [i for i, kind in kept if kind == 'P'], [i for i, kind in kept if kind == 'V'], removed


def _pending(high, low, kind):
    values = low if kind == 'low' else high
    points = []
    for i in range(max(5, len(values)-5), len(values)-1):
        before, after = values[i-5:i], values[i+1:]
        if kind == 'low' and values[i] < min(before) and values[i] <= min(after):
            points.append(i)
        if kind == 'high' and values[i] > max(before) and values[i] >= max(after):
            points.append(i)
    return points


def _old_decision(high, low, close, peaks, valleys):
    """Unmodified canonical v2 decision and box evidence; later v5 overrides it."""
    last = float(close[-1])
    evidence = {'box_test': 'not_evaluated'}
    if len(peaks) < 10 or len(valleys) < 10:
        return '证据不足', f'已确认峰{len(peaks)}个/谷{len(valleys)}个，要求各10个', evidence
    p, v = peaks[-3:], valleys[-3:]
    hp, lv = [float(high[i]) for i in p], [float(low[i]) for i in v]
    up = hp[0] < hp[1] < hp[2] and lv[0] < lv[1] < lv[2]
    down = hp[0] > hp[1] > hp[2] and lv[0] > lv[1] > lv[2]
    if up:
        if last < lv[-1]:
            return '结构转换／混合', '上行结构被收盘跌破最近确认谷', evidence
        if last > hp[-1]:
            return '上涨突破', '三峰三谷齐升且收盘突破最近确认峰', evidence
        if v[-1] > p[-1]:
            return '较高波谷已确认（待突破）', '较高确认谷比最近确认峰更新，收盘未突破峰', evidence
        points = [i for i in _pending(high, low, 'low') if i > p[-1] and low[i] > lv[-1]]
        if points:
            i = points[-1]
            evidence['pending_index'] = i
            evidence['pending_price'] = float(low[i])
            evidence['pending_age'] = len(high)-1-i
            return '上涨止跌待确认', f'候选较高谷已等待{len(high)-1-i}根，未满5根', evidence
        return '上涨回撤', '三峰三谷齐升，谷未破，未出现更晚待确认谷', evidence
    if down:
        if last > hp[-1]:
            return '结构转换／混合', '下行结构被收盘突破最近确认峰', evidence
        if last < lv[-1]:
            return '下跌破位', '三峰三谷齐降且收盘跌破最近确认谷', evidence
        if p[-1] > v[-1]:
            return '较低波峰已确认（待破位）', '较低确认峰比最近确认谷更新，收盘未跌破谷', evidence
        points = [i for i in _pending(high, low, 'high') if i > v[-1] and high[i] < hp[-1]]
        if points:
            i = points[-1]
            evidence['pending_index'] = i
            evidence['pending_price'] = float(high[i])
            evidence['pending_age'] = len(high)-1-i
            return '下跌反弹见顶待确认', f'候选较低峰已等待{len(high)-1-i}根，未满5根', evidence
        return '下跌反弹', '三峰三谷齐降，峰未破，未出现更晚待确认峰', evidence
    points = sorted([(i, 'P', float(high[i])) for i in peaks[-10:]] +
                    [(i, 'V', float(low[i])) for i in valleys[-10:]])
    tail = points[-8:]
    if len(tail) < 8 or any(tail[i][1] == tail[i-1][1] for i in range(1, 8)):
        evidence['box_test'] = 'four_pairs_not_alternating'
        return '结构转换／混合', '峰谷方向冲突或最近四组不连续交替', evidence
    old, check = tail[:6], tail[6:]
    old_p = [x[2] for x in old if x[1] == 'P']
    old_v = [x[2] for x in old if x[1] == 'V']
    trending = ((old_p[0] < old_p[1] < old_p[2] and old_v[0] < old_v[1] < old_v[2]) or
                (old_p[0] > old_p[1] > old_p[2] and old_v[0] > old_v[1] > old_v[2]))
    upper, lower = max(old_p), min(old_v)
    evidence.update(box_lower=lower, box_upper=upper, box_width_pct=100*(upper/lower-1),
                    box_prior_three_trending=trending, box_fourth_first_index=check[0][0],
                    box_fourth_prices=[x[2] for x in check])
    if trending:
        evidence['box_test'] = 'prior_three_were_trending'
        return '结构转换／混合', '前三组是单边趋势，不能将一次停顿当作箱体', evidence
    if any(x[2] > upper if x[1] == 'P' else x[2] < lower for x in check):
        evidence['box_test'] = 'fourth_breached_boundary'
        return '结构转换／混合', '第四组峰谷突破前三组边界', evidence
    if not lower <= last <= upper:
        evidence['box_test'] = 'current_close_outside_boundary'
        return '结构转换／混合', '当前收盘已离开前三组边界', evidence
    evidence['box_test'] = 'passed'
    return '区间震荡', '前三组边界由第四组峰谷验证且当前收盘仍在区间内', evidence


def _shape(values):
    a, b, c = values
    return 'up' if a < b < c else 'down' if a > b > c else 'nonmonotone'


def classify_decision(*, peak_shape: str, valley_shape: str, close: float,
                      peak: float, valley: float, highest_recent_peak: float,
                      old_state: str) -> str:
    """v2 asymmetric → four directions → v3/v4/v5 promotions, direction-first."""
    pd, vd = peak_shape, valley_shape
    relative = 'above_peak' if close > peak else 'below_valley' if close < valley else 'within_last_pair'
    state = old_state
    if pd == vd == 'up' or pd == vd == 'down':
        pass
    elif pd == 'down' and vd == 'up' and relative == 'within_last_pair':
        state = '收敛／方向待确认'
    elif vd == 'up' and pd == 'nonmonotone' and relative != 'below_valley':
        state = '低点抬升型上行'
    elif pd == 'down' and vd == 'nonmonotone' and relative != 'above_peak':
        state = '高点降低型下行'
    if pd == 'up' and vd == 'nonmonotone' and relative != 'below_valley':
        state = '高点上移型上行'
    elif vd == 'down' and pd == 'nonmonotone' and relative != 'above_peak':
        state = '低点下移型下行'
    # Promoted reversal states preempt old boxes and mixed; equal is never a break.
    if pd == 'down' and vd == 'up':
        if peak <= valley:
            if close < peak:
                return '收敛／破位下行'
            if close > valley:
                return '收敛／突破上行'
        elif close < valley:
            return '收敛／破位下行'
        elif close > peak:
            return '收敛／突破上行'
    if pd == 'down' and vd == 'down' and peak < close <= highest_recent_peak:
        return '原正统下行／突破最近峰（反转候选）'
    if pd == 'down' and vd == 'nonmonotone' and close > peak:
        return '原高点降低型下行形状／突破最近峰（反转候选）'
    if pd == 'up' and vd == 'up' and close < valley:
        return '原正统上行／跌破最近谷（反转候选）'
    if pd == 'nonmonotone' and vd == 'up' and close < valley:
        return '原低点抬升型上行形状／跌破最近谷（反转候选）'
    return state


def _pressure_line(high, low, close, dates, raw_peaks, raw_valleys):
    """Replay confirmations once, never using a peak before occurrence + five bars."""
    events = sorted([(i + 5, i, 'P') for i in raw_peaks] +
                    [(i + 5, i, 'V') for i in raw_valleys])
    chain = []
    peak_count = valley_count = 0
    event_index = 0
    identity = None
    candidate = None
    day = lambda i: str(dates[i].date()) if hasattr(dates[i], 'date') else str(dates[i])
    for t in range(len(high)):
        while event_index < len(events) and events[event_index][0] == t:
            _, i, kind = events[event_index]
            event_index += 1
            if chain and chain[-1][1] == kind:
                old = chain[-1][0]
                if (high[i] > high[old] if kind == 'P' else low[i] < low[old]):
                    chain[-1] = (i, kind)
            else:
                chain.append((i, kind))
                if kind == 'P':
                    peak_count += 1
                else:
                    valley_count += 1
        peaks = [i for i, kind in chain[-6:] if kind == 'P'][-3:]
        valleys = [i for i, kind in chain[-6:] if kind == 'V'][-3:]
        next_identity = tuple(peaks) if len(peaks) == 3 else None
        if next_identity != identity:
            candidate = None
            identity = next_identity
        if len(peaks) != 3 or len(valleys) != 3:
            candidate = None
            continue
        a, b, c = peaks
        shape = ('orthodox_down' if low[valleys[0]] > low[valleys[1]] > low[valleys[2]]
                 else 'weak_down' if not low[valleys[0]] < low[valleys[1]] < low[valleys[2]] else None)
        if not (high[a] > high[b] > high[c]) or shape is None:
            candidate = None
            continue
        # The main classifier requires ten canonical points of each kind.
        if peak_count < 10 or valley_count < 10:
            candidate = None
            continue
        age = t - (c + 5)
        if candidate is not None:
            # An early observation is no longer current after losing its frozen
            # price, even if five-bar continuation had already been established.
            if close[t] <= candidate['key_price'] or close[t] > high[c]:
                candidate = None
                continue  # The failed/over-C bar cannot retrigger the old line.
            if candidate['status'] == 'triggered':
                candidate['days_above_after_trigger'] += 1
                if candidate['days_above_after_trigger'] == 5:
                    candidate['status'] = 'sustained'
            candidate['latest_close'] = round(float(close[t]), 4)
            candidate['as_of'] = day(t)
            continue
        if not 1 <= age <= 30 or close[t] > high[c]:
            continue
        lines = {name: float(high[x] + (high[y] - high[x]) * (t-x) / (y-x))
                 for name, x, y in (('AB', a, b), ('AC', a, c), ('BC', b, c))}
        key = max(lines.values())
        previous_key = max(float(high[x] + (high[y] - high[x]) * (t-1-x) / (y-x))
                           for x, y in ((a, b), (a, c), (b, c)))
        if (not math.isfinite(key) or key <= 0 or
                not all(math.isfinite(v) for v in lines.values()) or
                not math.isfinite(previous_key)):
            continue
        # A first crossing requires the preceding valid close not to have
        # already stood above that day's line; a descending line alone is no proof.
        if float(close[t]) > key and float(close[t-1]) <= previous_key:
            candidate = {
                'status': 'triggered', 'shape': shape,
                'peaks': [{'date': day(i), 'confirmed': day(i+5), 'high': round(float(high[i]), 4)}
                          for i in (a, b, c)],
                'lines': lines,
                'key_price': key, 'trigger_date': day(t),
                'trigger_close': round(float(close[t]), 4), 'c_confirmed': day(c+5),
                'trigger_age': age, 'days_above_after_trigger': 0,
                'latest_close': round(float(close[t]), 4), 'as_of': day(t),
                'line_points': {name: [{'date': day(x), 'high': round(float(high[x]), 4)},
                                       {'date': day(y), 'high': round(float(high[y]), 4)}]
                                for name, x, y in (('AB', a, b), ('AC', a, c), ('BC', b, c))},
            }
    return candidate


def classify(bars: pd.DataFrame) -> dict:
    """Return one v5 state and JSON-safe evidence at the last valid QFQ bar.

    Each call uses only the supplied prefix. No reference CSV or current date is read.
    Missing/stale source policy belongs to the caller; no alternative price basis.
    """
    if not isinstance(bars, pd.DataFrame):
        raise TypeError('QFQ bars must be a pandas DataFrame')
    clean = clean_wyckoff_bars(bars)
    if clean.empty:
        raise ValueError('no valid QFQ OHLCV bars')
    high, low, close = (clean[k].to_numpy(dtype=float) for k in ('high', 'low', 'close'))
    dates = clean.index
    day = lambda i: str(dates[i].date()) if hasattr(dates[i], 'date') else str(dates[i])
    raw_p, raw_v, ambiguous = _pivots(high, low)
    peaks, valleys, removed = _canonical(raw_p, raw_v, high, low)
    old, reason, evidence = _old_decision(high, low, close, peaks, valleys)
    result = {'state': old, 'reason': reason, 'price_basis': 'tdx_qfq_export',
              'as_of': day(-1), 'bars': len(clean), 'close': round(float(close[-1]), 4),
              'raw_confirmed_peaks': len(raw_p), 'raw_confirmed_valleys': len(raw_v),
              'selected_peaks': len(peaks), 'selected_valleys': len(valleys),
              'ambiguous_bars': ambiguous, 'discarded_same_type': len(removed),
              'box_test': evidence['box_test'],
              'box_lower': round(evidence['box_lower'], 4) if 'box_lower' in evidence else None,
              'box_upper': round(evidence['box_upper'], 4) if 'box_upper' in evidence else None,
              'box_width_pct': round(evidence['box_width_pct'], 4) if 'box_width_pct' in evidence else None,
              'box_audit': {k: v for k, v in evidence.items() if k.startswith('box_')},
              'pending': None, 'new_low_risk': None, 'pressure_line': None, 'peak_shape': '', 'valley_shape': '',
              'structure': '', 'relative_to_last_pair': '', 'old_state': old}
    result['last_10_peaks'] = [{'date': day(i), 'confirmed': day(i+5), 'high': round(float(high[i]), 4)} for i in peaks[-10:]]
    result['last_10_valleys'] = [{'date': day(i), 'confirmed': day(i+5), 'low': round(float(low[i]), 4)} for i in valleys[-10:]]
    result['discarded_recent'] = [{'date': day(i), 'kind': kind, 'price': round(float(high[i] if kind == 'P' else low[i]), 4),
                                    'retained_date': day(j), 'cause': cause} for i, kind, j, cause in removed[-20:]]
    result['raw_last_10_peaks'] = [{'date': day(i), 'confirmed': day(i+5), 'high': round(float(high[i]), 4)} for i in raw_p[-10:]]
    result['raw_last_10_valleys'] = [{'date': day(i), 'confirmed': day(i+5), 'low': round(float(low[i]), 4)} for i in raw_v[-10:]]
    result['candidate_peaks'] = [{'date': day(i), 'high': round(float(high[i]), 4),
                                  'waiting_bars': len(clean)-1-i} for i in _pending(high, low, 'high')]
    result['candidate_valleys'] = [{'date': day(i), 'low': round(float(low[i]), 4),
                                    'waiting_bars': len(clean)-1-i} for i in _pending(high, low, 'low')]
    if 'pending_index' in evidence:
        i = evidence['pending_index']
        result['pending'] = {'date': day(i), 'price': round(evidence['pending_price'], 4), 'age': evidence['pending_age']}
    if peaks:
        result['latest_peak'] = result['last_10_peaks'][-1]
    if valleys:
        result['latest_valley'] = result['last_10_valleys'][-1]
    if len(peaks) < 10 or len(valleys) < 10:
        result.update(peak_shape='insufficient', valley_shape='insufficient', structure='',
                      relative_to_last_pair='')
    else:
        peak_shape = _shape([float(high[i]) for i in peaks[-3:]])
        vd = _shape([float(low[i]) for i in valleys[-3:]])
        p, v, last = float(high[peaks[-1]]), float(low[valleys[-1]]), float(close[-1])
        relative = 'above_peak' if last > p else 'below_valley' if last < v else 'within_last_pair'
        structure = ('orthodox_up' if peak_shape == vd == 'up' else 'orthodox_down' if peak_shape == vd == 'down'
                     else 'contracting' if peak_shape == 'down' and vd == 'up' else 'weak_up' if vd == 'up' and peak_shape == 'nonmonotone'
                     else 'weak_down' if peak_shape == 'down' and vd == 'nonmonotone' else 'expanding' if peak_shape == 'up' and vd == 'down' else 'other')
        result.update(peak_shape=peak_shape, valley_shape=vd, structure=structure, relative_to_last_pair=relative,
                      state=classify_decision(peak_shape=peak_shape, valley_shape=vd, close=last, peak=p, valley=v,
                                              highest_recent_peak=max(float(high[i]) for i in peaks[-3:]), old_state=old))
        if result['state'] != old:
            result['reason'] = f'v5主状态：{peak_shape}峰/{vd}谷，收盘{last:g}，最近确认峰{p:g}/谷{v:g}；原状态{old}'
        # Keep the confirmed main state intact.  A lower intraday low after its
        # latest confirmed valley is a separate observation, even if close rebounds.
        # Search from that valley (not a rolling five-bar window): otherwise a
        # pending break could silently disappear before the confirmed chain updates.
        if vd == 'up' and peak_shape in ('up', 'nonmonotone') and valleys[-1] + 1 < len(low):
            i = int(np.argmin(low[valleys[-1] + 1:])) + valleys[-1] + 1
            if float(low[i]) < v:
                result['new_low_risk'] = {
                    'date': day(i), 'low': round(float(low[i]), 4),
                    'confirmed_valley_date': day(valleys[-1]),
                    'confirmed_valley_low': round(v, 4),
                    'waiting_bars': len(low) - 1 - i,
                    'close_below_confirmed_valley': last < v,
                    'break_day_close_below_confirmed_valley': float(close[i]) < v,
                }
    result['pressure_line'] = _pressure_line(high, low, close, dates, raw_p, raw_v)
    if result['state'] == '区间震荡' and evidence.get('box_test') == 'passed':
        chain = sorted([(i, 'peak', float(high[i])) for i in peaks[-10:]] +
                       [(i, 'valley', float(low[i])) for i in valleys[-10:]])[-8:]
        result['box_audit']['old_three_pairs'] = [
            {'date': day(i), 'kind': kind, 'price': round(price, 4)} for i, kind, price in chain[:6]]
        result['box_audit']['fourth_check'] = [
            {'date': day(i), 'kind': kind, 'price': round(price, 4)} for i, kind, price in chain[6:]]
        result['box_audit']['price_position'] = (
            '最近谷下' if float(close[-1]) < float(low[valleys[-1]]) else
            '最近峰上' if float(close[-1]) > float(high[peaks[-1]]) else '最近峰谷间')
    return result
