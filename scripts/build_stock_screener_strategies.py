#!/usr/bin/env python3
"""Build stock screener preset-strategy signal datasets from local Tongdaxin daily data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mootdx.reader import Reader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.search.index import (
    DEFAULT_DATASET_DIR,
    load_industry_valuation_rows,
    load_rps_rows,
)

DEFAULT_TDX_DIR = "/home/lufanfeng/tdx_data"
DEFAULT_OUTPUT = DEFAULT_DATASET_DIR / "dataset_stock_screener_strategies_current.json"
STRATEGY_FIRST = "rps_first"
STRATEGY_SLINGSHOT = "slingshot_trend"
STRATEGY_FIRST_MACD = "rps_first_macd"
STRATEGY_DUOTOU = "duotou"
STRATEGY_ATH = "ath_rps360"
STRATEGY_METADATA = {
    STRATEGY_FIRST: {
        "label": "RPS首次",
    },
    STRATEGY_SLINGSHOT: {
        "label": "弹弓趋势",
    },
    STRATEGY_FIRST_MACD: {
        "label": "RPS首次+金叉",
    },
    STRATEGY_DUOTOU: {
        "label": "多头",
    },
    STRATEGY_ATH: {
        "label": "历史新高",
    },
}


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _return_pct(closes: list[float], end_index: int, window: int) -> float | None:
    start_index = end_index - window
    if start_index < 0 or end_index < 0 or end_index >= len(closes):
        return None
    base = closes[start_index]
    if base == 0:
        return None
    return (closes[end_index] - base) / base * 100.0


def _compute_past_days_rps(reader, rps_rows, ndays=5, as_of: str = ""):
    """Compute cross-sectional RPS for the past N trading days.
    
    Uses the pre-computed RPS history dataset to look up RPS values for prior days.
    When as_of is provided, only considers trading days up to that date.
    Returns a list of dicts, one per past day (index 0 = yesterday relative to as_of).
    Each dict maps (market, symbol) → {rps_20, rps_50, rps_120, rps_250}.
    """
    import json as _json
    
    history_path = PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_rps_history.json"
    if not history_path.exists():
        return []
    
    all_history = _json.loads(history_path.read_text(encoding="utf-8"))
    
    # Get unique trading days sorted
    trading_days = sorted(set(str(h.get("trading_day", "")) for h in all_history if h.get("trading_day")))
    if not trading_days:
        return []
    
    # When as_of is set, find its index and only use days up to it
    if as_of:
        as_of_idx = None
        for i, td in enumerate(trading_days):
            if td == as_of:
                as_of_idx = i
                break
        if as_of_idx is None:
            # Find closest day <= as_of
            for i in range(len(trading_days) - 1, -1, -1):
                if trading_days[i] <= as_of:
                    as_of_idx = i
                    break
        if as_of_idx is not None:
            trading_days = trading_days[:as_of_idx + 1]
    
    # Build lookup: trading_day → {(market, symbol): {rps_20, rps_50, rps_120, rps_250}}
    rps_by_day: dict[str, dict[tuple[str, str], dict[str, float | None]]] = {}
    for h in all_history:
        td = str(h.get("trading_day", ""))
        if td not in rps_by_day:
            rps_by_day[td] = {}
        key = (str(h.get("market", "")).strip().lower(), str(h.get("symbol", "")).strip())
        rps_by_day[td][key] = {
            "rps_20": h.get("rps_20"),
            "rps_50": h.get("rps_50"),
            "rps_120": h.get("rps_120"),
            "rps_250": h.get("rps_250"),
        }
    
    # Latest day is index -1. Yesterday = -2, 2 days ago = -3, etc.
    result = []
    for i in range(2, min(2 + ndays, len(trading_days) + 1)):
        td = trading_days[-i] if i <= len(trading_days) else None
        if td and td in rps_by_day:
            result.append(rps_by_day[td])
    
    return result


def _load_past_rps_first_signals(trading_day: str, ndays: int = 60) -> set[tuple[str, str]]:
    """Return set of (market, symbol) that had a passed RPS首次 signal in the past ndays trading days.
    
    Reads strategy history files to check for actual signals (not just RPS>360 crossings).
    If a strategy file doesn't exist for a past day, that day is skipped (no signal assumed).
    """
    import pandas as pd

    parquet_path = PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"
    if not parquet_path.exists():
        return set()

    df = pd.read_parquet(parquet_path, columns=['trading_day'])
    all_td = sorted(df['trading_day'].unique())

    # Find the index of trading_day and go back ndays
    try:
        td_idx = all_td.index(trading_day)
    except ValueError:
        # trading_day not found — find closest before it
        for i in range(len(all_td) - 1, -1, -1):
            if all_td[i] <= trading_day:
                td_idx = i
                break
        else:
            return set()

    start_idx = max(0, td_idx - ndays)
    past_days = all_td[start_idx:td_idx]  # exclude today itself

    signaled: set[tuple[str, str]] = set()
    final_dir = PROJECT_ROOT / "data/derived/datasets/final"

    for pd_day in past_days:
        strat_path = final_dir / f"dataset_stock_screener_strategies_{pd_day}.json"
        if not strat_path.exists():
            continue
        try:
            with open(strat_path, 'r', encoding='utf-8') as fh:
                rows = json.load(fh)
        except Exception:
            continue
        for r in rows:
            if r.get('strategy') == STRATEGY_FIRST and r.get('passed'):
                signaled.add((str(r.get('market', '')).strip().lower(),
                              str(r.get('symbol', '')).strip()))

    return signaled


def _rps_first_candidates(rps_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find stocks where RPS total (rps20+rps50+rps120+rps250) crosses above 360 today."""
    candidates: list[dict[str, Any]] = []
    for row in rps_rows:
        rps20 = _coerce_float(row.get("rps_20"))
        rps50 = _coerce_float(row.get("rps_50"))
        rps120 = _coerce_float(row.get("rps_120"))
        rps250 = _coerce_float(row.get("rps_250"))
        if None in (rps20, rps50, rps120, rps250):
            continue
        rps_total = rps20 + rps50 + rps120 + rps250
        if rps_total > 360:
            candidates.append(row)
    return candidates

def build_rps_first_rows(*, tdxdir: str = DEFAULT_TDX_DIR, trading_day: str = "") -> list[dict[str, Any]]:
    """RPS首次：RPS总分上穿360+趋势多头/强多头+短趋势多头/强多头+距MA10<10%+收盘价10日最高, 过去60日首次."""
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    if trading_day:
        from app.search.index import load_rps_rows_as_of
        rps_rows = load_rps_rows_as_of(trading_day)
    else:
        rps_rows = load_rps_rows()
    candidates = _rps_first_candidates(rps_rows)
    if not candidates:
        return []

    # Load tech eval for trend/short_trend filtering
    from app.search.index import _load_technical_eval
    tech_eval = _load_technical_eval(as_of_date=trading_day or "")

    # Load past 60-day RPS首次 signals for dedup (actual signals, not just RPS>360)
    past_signals = _load_past_rps_first_signals(trading_day or "", ndays=60)

    # Compute cross-sectional RPS for past days (needed for yesterday_total)
    past_rps_by_day = _compute_past_days_rps(reader, rps_rows, ndays=60, as_of=trading_day)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    results: list[dict[str, Any]] = []
    for row in candidates:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        key = (market_val, symbol_val)

        # ── Condition 2: 趋势多头/强多头 ──
        te = tech_eval.get(symbol_val, {})
        trend = str(te.get("trend", "")).lower()
        if trend not in ("bullish", "strong_bullish"):
            continue

        # ── Condition 3: 短趋势多头/强多头 ──
        short_trend = str(te.get("short_trend", "")).lower()
        if short_trend not in ("bullish", "strong_bullish"):
            continue

        # ── Condition 4: 距MA10 < 10% ──
        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        opens = daily["open"].astype(float)
        if len(closes) < 15:
            continue
        ti = len(closes) - 1
        close_t = closes[ti]
        ma10 = sum(closes[max(0, ti - 9):ti + 1]) / 10
        dist_ma10 = abs(close_t - ma10) / ma10 * 100.0
        if dist_ma10 >= 10:
            continue

        # ── Condition 5: 收盘价10日最高 ──
        recent_closes = closes[max(0, ti - 9):ti + 1]
        if close_t < max(recent_closes) - 1e-9:
            continue

        # ── Condition 1: RPS首次 (same as before) ──
        rps20_t = _coerce_float(row.get("rps_20")) or 0
        rps50_t = _coerce_float(row.get("rps_50")) or 0
        rps120_t = _coerce_float(row.get("rps_120")) or 0
        rps250_t = _coerce_float(row.get("rps_250")) or 0
        total_today = rps20_t + rps50_t + rps120_t + rps250_t

        ever_met = False
        yesterday_total = None
        for day_idx, day_rps in enumerate(past_rps_by_day):
            rps = day_rps.get(key, {})
            r20 = rps.get("rps_20")
            r50 = rps.get("rps_50")
            r120 = rps.get("rps_120")
            r250 = rps.get("rps_250")
            if None in (r20, r50, r120, r250):
                continue
            day_total = r20 + r50 + r120 + r250
            if day_idx == 0:
                yesterday_total = day_total
            if day_total > 360:
                ever_met = True
                break

        is_first = not ever_met  # based on RPS>360 history (informational)
        crossed = yesterday_total is not None and yesterday_total <= 360
        # True first signal: crossed AND no actual RPS首次 signal in past 60 trading days
        is_true_first = key not in past_signals

        conditions: dict[str, object] = {
            "rps_total": round(total_today, 2),
            "rps20": round(rps20_t, 2),
            "rps50": round(rps50_t, 2),
            "rps120": round(rps120_t, 2),
            "rps250": round(rps250_t, 2),
            "cross_above_360": crossed,
            "yesterday_total": round(yesterday_total, 2) if yesterday_total is not None else None,
            "first_in_60d": is_true_first,
            "trend": trend,
            "short_trend": short_trend,
            "dist_ma10_pct": round(dist_ma10, 2),
            "is_10d_high": bool(close_t >= max(recent_closes) - 1e-9),
        }

        results.append({
            "trading_day": row.get("trading_day"),
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_FIRST,
            "strategy_label": STRATEGY_METADATA[STRATEGY_FIRST]["label"],
            "passed": crossed and is_true_first,
            "conditions": conditions,
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+dataset_stock_rps_current+dataset_stock_rps_history+dataset_technical_eval",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_rps_first_macd_rows(*, tdxdir: str = DEFAULT_TDX_DIR, trading_day: str = "") -> list[dict[str, Any]]:
    """RPS首次+MACD金叉(延迟): 过去60日内有RPS首次信号 + 当日MACD金叉(DIF上穿DEA)."""
    # Get today's RPS首次 results (for condition details)
    rps_first_results = build_rps_first_rows(tdxdir=tdxdir, trading_day=trading_day)

    # Build lookup: symbol -> RPS首次 item (for condition details)
    rps_first_by_symbol: dict[str, dict[str, Any]] = {}
    for item in rps_first_results:
        symbol = str(item.get("symbol", "")).strip()
        if symbol:
            rps_first_by_symbol[symbol] = item

    # Get past 60-day RPS首次 signaled stocks
    past_signals = _load_past_rps_first_signals(trading_day or "", ndays=60)

    # Collect all candidates: past-signaled + today's passed
    all_candidates: dict[str, dict[str, str]] = {}  # symbol -> {market, symbol}

    for market, symbol in past_signals:
        all_candidates[symbol] = {"market": market, "symbol": symbol}

    # Add today's passed RPS首次 (in case not in past signals)
    for item in rps_first_results:
        if item.get("passed"):
            symbol = str(item.get("symbol", "")).strip()
            market = str(item.get("market", "")).strip().lower()
            if symbol and symbol not in all_candidates:
                all_candidates[symbol] = {"market": market, "symbol": symbol}

    if not all_candidates:
        return []

    # Check MACD for each candidate
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    from scripts.build_macd_signals import _compute_macd

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for symbol in sorted(all_candidates):
        info = all_candidates[symbol]
        market_val = info["market"]

        # Get condition details from today's RPS首次 if available
        rps_item = rps_first_by_symbol.get(symbol, {})
        conditions = dict(rps_item.get("conditions", {}))
        from_past = symbol not in {str(i.get("symbol", "")).strip() for i in rps_first_results if i.get("passed")}
        conditions["from_past_signal"] = from_past

        try:
            daily = reader.daily(symbol=symbol)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue

        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        if len(closes) < 40:
            continue

        macd_data = _compute_macd(closes)
        if macd_data is None:
            continue

        dif, dea, _hist = macd_data
        ti = len(closes) - 1

        # MACD golden cross: DIF(t) > DEA(t) AND DIF(t-1) <= DEA(t-1)
        is_golden = dif[ti] > dea[ti] and dif[ti - 1] <= dea[ti - 1]

        conditions["macd_golden_cross"] = is_golden
        conditions["dif"] = round(dif[ti], 4)
        conditions["dea"] = round(dea[ti], 4)

        results.append({
            "trading_day": rps_item.get("trading_day") or trading_day,
            "market": market_val,
            "symbol": symbol,
            "strategy": STRATEGY_FIRST_MACD,
            "strategy_label": STRATEGY_METADATA[STRATEGY_FIRST_MACD]["label"],
            "passed": is_golden,
            "conditions": conditions,
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily+dataset_stock_rps_current+dataset_stock_rps_history+dataset_technical_eval",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results

def build_slingshot_trend_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """弹弓趋势v5：MA10加速上弯(4日) + min(开,收)3日连涨 + 10日涨幅<30% + 近3日放量 + GAP<4。"""
    import pandas as pd
    from app.search.index import load_security_rows
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    securities = load_security_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for sec in securities:
        symbol_val = str(sec.get("symbol", "")).strip()
        if not symbol_val:
            continue
        market_val = str(sec.get("market", "")).strip().lower()

        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        if len(daily) < 60:
            continue

        closes = daily["close"].astype(float)
        opens = daily["open"].astype(float)
        volumes = daily["volume"].astype(float)
        n = len(closes)

        ma10 = closes.rolling(10).mean()
        if pd.isna(ma10.iloc[-1]) or pd.isna(ma10.iloc[-4]):
            continue

        ma10_t = float(ma10.iloc[-1])
        ma10_t1 = float(ma10.iloc[-2])
        ma10_t2 = float(ma10.iloc[-3])
        ma10_t3 = float(ma10.iloc[-4])

        # Condition 1: Slingshot bend — MA10 rising, 4-day span
        diff = ma10_t - ma10_t3
        if diff <= 0:
            continue
        a1 = ma10_t3 + diff * 0.33
        a2 = ma10_t3 + diff * 0.67
        if not (ma10_t2 < a1 and ma10_t1 < a2):
            continue

        # Condition 2: min(open,close) rising 3 consecutive days
        if n < 4:
            continue
        close_t = float(closes.iloc[-1])
        open_t3 = float(opens.iloc[-4])
        open_t2 = float(opens.iloc[-3])
        open_t1 = float(opens.iloc[-2])
        open_t = float(opens.iloc[-1])
        close_t3 = float(closes.iloc[-4])
        close_t2 = float(closes.iloc[-3])
        close_t1 = float(closes.iloc[-2])
        low_t3 = min(open_t3, close_t3)
        low_t2 = min(open_t2, close_t2)
        low_t1 = min(open_t1, close_t1)
        low_t = min(open_t, close_t)
        if not (low_t3 < low_t2 < low_t1 < low_t):
            continue

        # Condition 3: 10-day gain < 30%
        if n < 11:
            continue
        close_t10 = float(closes.iloc[-11])
        if close_t >= close_t10 * 1.30:
            continue

        gain_10d_pct = round((close_t / close_t10 - 1) * 100, 2)

        # Condition 4: Volume amplification — last 3 days
        if n < 14:
            continue
        vol_window = volumes.iloc[-14:-4]
        if len(vol_window) < 10:
            continue
        vol_min_10d = float(vol_window.min())
        if vol_min_10d <= 0:
            continue
        vol_threshold = vol_min_10d * 3.0
        vol_ma50 = volumes.rolling(50).mean()
        if pd.isna(vol_ma50.iloc[-1]):
            continue
        vol_ma50_val = float(vol_ma50.iloc[-1])

        vol_ok = True
        for i in range(3):
            v = float(volumes.iloc[-(i+1)])
            if v <= vol_threshold or v <= vol_ma50_val:
                vol_ok = False
                break
        if not vol_ok:
            continue

        # Condition 5: Cumulative MA10 deviation < 4
        gap_total = 0.0
        gap_days = 0
        for j in range(1, min(n, 120)):
            idx = -(j + 1)
            if pd.isna(ma10.iloc[idx]):
                break
            price_low = float(min(opens.iloc[idx], closes.iloc[idx]))
            ma10_val = float(ma10.iloc[idx])
            if price_low <= ma10_val:
                break
            c = float(closes.iloc[idx])
            if c <= 0:
                break
            gap_total += (price_low - ma10_val) * (10.0 / c)
            gap_days += 1
        if gap_total >= 4.0:
            continue

        # Condition ⑥: Last 4 days at most 1 bearish candle, decline < 2%
        bearish_count = 0
        bearish_ok = True
        for i in range(4):
            o = float(opens.iloc[-(i+1)])
            c = float(closes.iloc[-(i+1)])
            if c <= o:
                bearish_count += 1
                if bearish_count > 1:
                    bearish_ok = False
                    break
                decline_pct = (o - c) / o * 100 if o > 0 else 0
                if decline_pct >= 2.0:
                    bearish_ok = False
                    break
        if not bearish_ok:
            continue

        # Condition ⑦: MA10 > MA60
        if n < 60:
            continue
        ma60_val = float(closes.rolling(60).mean().iloc[-1])
        if pd.isna(ma60_val):
            continue
        if not (ma10_t > ma60_val):
            continue

        # Condition ⑧: First time in 60 days satisfying all conditions ①-⑦
        # Check each of the prior 59 days; if any also passed, skip this stock.
        def _check_day(idx: int) -> bool:
            """Check if day at index `idx` satisfies conditions ①-⑦."""
            if idx < 60:
                return False
            c_vals = closes.iloc[:idx+1]
            o_vals = opens.iloc[:idx+1]
            v_vals = volumes.iloc[:idx+1]
            m10 = c_vals.rolling(10).mean()
            if pd.isna(m10.iloc[-1]) or pd.isna(m10.iloc[-4]):
                return False
            # ① MA10 slingshot bend
            m_t = float(m10.iloc[-1])
            m_t1 = float(m10.iloc[-2])
            m_t2 = float(m10.iloc[-3])
            m_t3 = float(m10.iloc[-4])
            d = m_t - m_t3
            if d <= 0:
                return False
            b1 = m_t3 + d * 0.33
            b2 = m_t3 + d * 0.67
            if not (m_t2 < b1 and m_t1 < b2):
                return False
            # ② min(open,close) rising 3 consecutive days
            ct = float(c_vals.iloc[-1])
            ot3, ot2, ot1, ot = [float(o_vals.iloc[-i]) for i in range(4, 0, -1)]
            ct3, ct2, ct1 = [float(c_vals.iloc[-i]) for i in range(4, 1, -1)]
            lt3, lt2, lt1, lt = [min(o, c) for o, c in [(ot3,ct3), (ot2,ct2), (ot1,ct1), (ot,ct)]]
            if not (lt3 < lt2 < lt1 < lt):
                return False
            # ③ 10-day gain < 30%
            ct10 = float(c_vals.iloc[-11])
            if ct >= ct10 * 1.30:
                return False
            # ④ Volume amplification last 3 days
            vw = v_vals.iloc[-14:-4]
            if len(vw) < 10:
                return False
            vmin = float(vw.min())
            if vmin <= 0:
                return False
            vth = vmin * 3.0
            vm50 = float(v_vals.rolling(50).mean().iloc[-1])
            if pd.isna(vm50):
                return False
            for k in range(3):
                if float(v_vals.iloc[-(k+1)]) <= vth or float(v_vals.iloc[-(k+1)]) <= vm50:
                    return False
            # ⑤ GAP < 4
            gp = 0.0
            for j in range(1, min(len(c_vals), 120)):
                ix = -(j + 1)
                if pd.isna(m10.iloc[ix]):
                    break
                pl = float(min(o_vals.iloc[ix], c_vals.iloc[ix]))
                mv = float(m10.iloc[ix])
                if pl <= mv:
                    break
                cc = float(c_vals.iloc[ix])
                if cc <= 0:
                    break
                gp += (pl - mv) * (10.0 / cc)
            if gp >= 4.0:
                return False
            # ⑥ at most 1 bearish candle in 4 days, decline < 2%
            bc = 0
            for k in range(4):
                oo = float(o_vals.iloc[-(k+1)])
                cc = float(c_vals.iloc[-(k+1)])
                if cc <= oo:
                    bc += 1
                    if bc > 1:
                        return False
                    dp = (oo - cc) / oo * 100 if oo > 0 else 0
                    if dp >= 2.0:
                        return False
            # ⑦ MA10 > MA60
            m60 = float(c_vals.rolling(60).mean().iloc[-1])
            if pd.isna(m60):
                return False
            if not (m_t > m60):
                return False
            return True

        lookback = min(60, n - 1)
        first_time = True
        for back in range(1, lookback):
            if _check_day(n - 1 - back):
                first_time = False
                break
        if not first_time:
            continue

        results.append({
            "trading_day": str(daily.index[-1])[:10],
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_SLINGSHOT,
            "strategy_label": STRATEGY_METADATA[STRATEGY_SLINGSHOT]["label"],
            "passed": True,
            "conditions": {
                "ma10_t": round(ma10_t, 2),
                "ma10_t3": round(ma10_t3, 2),
                "diff": round(diff, 2),
                "a1": round(a1, 2), "a2": round(a2, 2),
                "ma10_t1": round(ma10_t1, 2), "ma10_t2": round(ma10_t2, 2),
                "close_pct_10d": gain_10d_pct,
                "low_t3": round(low_t3, 2),
                "low_t2": round(low_t2, 2),
                "low_t1": round(low_t1, 2),
                "low_t": round(low_t, 2),
                "vol_min_10d": round(vol_min_10d, 0),
                "vol_threshold": round(vol_threshold, 0),
                "vol_ma50": round(vol_ma50_val, 0),
                "gap_total": round(gap_total, 2),
                "gap_days": gap_days,
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_ath_rps360_rows(*, tdxdir: str = DEFAULT_TDX_DIR, trading_day: str = "") -> list[dict[str, Any]]:
    """历史新高 + RPS>360 策略：昨日创历史新高 + RPS总分>360."""
    import numpy as np

    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    securities = __import__("app.search.index", fromlist=["load_security_rows"]).load_security_rows()

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for sec in securities:
        symbol_val = str(sec.get("symbol", "")).strip()
        if not symbol_val:
            continue
        market_val = str(sec.get("market", "")).strip().lower()
        name_val = str(sec.get("stock_name", "")).strip()

        # RPS check: must have RPS data and total > 360
        rps_match = next((r for r in rps_rows if str(r.get("symbol", "")).strip() == symbol_val), None)
        if not rps_match:
            continue
        rps20 = _coerce_float(rps_match.get("rps_20"))
        rps50 = _coerce_float(rps_match.get("rps_50"))
        rps120 = _coerce_float(rps_match.get("rps_120"))
        rps250 = _coerce_float(rps_match.get("rps_250"))
        trading_day_rps = str(rps_match.get("trading_day", ""))
        if any(v is None for v in [rps20, rps50, rps120, rps250]):
            continue
        rps_total = rps20 + rps50 + rps120 + rps250
        if rps_total <= 360:
            continue

        # ATH check: read daily bars
        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = daily["close"].astype(float).values
        n = len(closes)
        if n < 2:
            continue

        # Check if today's close (the as_of date) is an all-time high.
        # closes[-1] = the trading day itself (after monkey-patch truncation).
        today_close = closes[-1]
        ath_before = np.max(closes[:-1]) if n > 1 else 0
        is_ath = bool(today_close >= ath_before)

        # 计算距离上次ATH的天数（查全部历史，O(n)）
        cummax = np.maximum.accumulate(closes)
        days_since_last_ath = n - 1
        for k in range(2, n):
            idx = -k
            prev_close = closes[idx]
            prev_max = cummax[idx - 1] if idx + n > 1 else 0
            if prev_close >= prev_max:
                days_since_last_ath = k - 1
                break

        conditions = {
            "is_ath": is_ath,
            "ath_close": round(float(today_close), 2),
            "days_since_last_ath": days_since_last_ath,
            "rps_total": round(rps_total, 1),
            "rps_20": round(rps20, 1),
            "rps_50": round(rps50, 1),
            "rps_120": round(rps120, 1),
            "rps_250": round(rps250, 1),
            "trading_day": trading_day_rps,
        }

        results.append({
            "trading_day": trading_day_rps,
            "market": market_val,
            "symbol": symbol_val,
            "name": name_val,
            "strategy": STRATEGY_ATH,
            "strategy_label": STRATEGY_METADATA[STRATEGY_ATH]["label"],
            "passed": is_ath,
            "conditions": conditions,
            "days_since_last_ath": days_since_last_ath,
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def build_duotou_rows(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    """多头策略：MA10/20/30 > MA60 + MA60近60日单调(至多1次例外，前后10日干净) + 最近3日MA10连续上升。"""
    import pandas as pd
    from app.search.index import load_security_rows
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    securities = load_security_rows()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for sec in securities:
        symbol_val = str(sec.get("symbol", "")).strip()
        if not symbol_val:
            continue
        market_val = str(sec.get("market", "")).strip().lower()
        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        if len(daily) < 120:
            continue
        closes = daily["close"].astype(float)
        n = len(closes)

        ma10 = closes.rolling(10).mean()
        ma20 = closes.rolling(20).mean()
        ma30 = closes.rolling(30).mean()
        ma60 = closes.rolling(60).mean()
        if pd.isna(ma60.iloc[-1]) or pd.isna(ma60.iloc[-61]):
            continue

        # Cond 1: MA10, MA20, MA30 > MA60
        ma10_now = float(ma10.iloc[-1])
        ma20_now = float(ma20.iloc[-1])
        ma30_now = float(ma30.iloc[-1])
        ma60_now = float(ma60.iloc[-1])
        if not (ma10_now > ma60_now and ma20_now > ma60_now and ma30_now > ma60_now):
            continue

        # Cond 2: MA60 monotonic non-decreasing, at most 1 exception with ±10 buffer
        violations = []
        for i in range(-60, 0):
            if float(ma60.iloc[i]) < float(ma60.iloc[i-1]):
                violations.append(i)
        ok = False
        if len(violations) == 0:
            ok = True
        elif len(violations) == 1:
            v = violations[0]
            # Check 10 days before
            before_ok = all(
                float(ma60.iloc[j]) >= float(ma60.iloc[j-1])
                for j in range(v - 10, v) if j >= -60
            )
            # Check 10 days after
            after_ok = all(
                float(ma60.iloc[j]) >= float(ma60.iloc[j-1])
                for j in range(v + 1, min(v + 11, 0))
            )
            ok = before_ok and after_ok
        if not ok:
            continue

        # Cond 3: 最近3日MA10连续上升 (ma10[-3] < ma10[-2] < ma10[-1])
        if pd.isna(ma10.iloc[-3]):
            continue
        ma10_d3 = float(ma10.iloc[-3])
        ma10_d2 = float(ma10.iloc[-2])
        ma10_d1 = float(ma10.iloc[-1])
        if not (ma10_d3 < ma10_d2 < ma10_d1):
            continue

        # Cond 4 (meta): 计算连续满足多头条件的天数（从当天往回数）
        consecutive = 1
        for i in range(-2, -n, -1):
            # Check Cond 1
            if not (float(ma10.iloc[i]) > float(ma60.iloc[i])
                    and float(ma20.iloc[i]) > float(ma60.iloc[i])
                    and float(ma30.iloc[i]) > float(ma60.iloc[i])):
                break
            # Check Cond 2 (MA60 monotonic, 60-day window ending at i)
            i_start = max(i - 59, -n)
            violations_i = []
            for j in range(i_start + 1, i + 1):
                if float(ma60.iloc[j]) < float(ma60.iloc[j-1]):
                    violations_i.append(j)
            ok_i = False
            if len(violations_i) == 0:
                ok_i = True
            elif len(violations_i) == 1:
                v = violations_i[0]
                before_ok_i = all(
                    float(ma60.iloc[j]) >= float(ma60.iloc[j-1])
                    for j in range(v - 10, v) if j > i_start
                )
                after_ok_i = all(
                    float(ma60.iloc[j]) >= float(ma60.iloc[j-1])
                    for j in range(v + 1, min(v + 11, i + 1))
                )
                ok_i = before_ok_i and after_ok_i
            if not ok_i:
                break
            # Check Cond 3 (MA10 3-day rise ending at i)
            if pd.isna(ma10.iloc[i-2]):
                break
            if not (float(ma10.iloc[i-2]) < float(ma10.iloc[i-1]) < float(ma10.iloc[i])):
                break
            consecutive += 1

        results.append({
            "trading_day": str(daily.index[-1])[:10],
            "market": market_val,
            "symbol": symbol_val,
            "strategy": STRATEGY_DUOTOU,
            "strategy_label": STRATEGY_METADATA[STRATEGY_DUOTOU]["label"],
            "passed": True,
            "conditions": {
                "ma10": round(ma10_now, 2),
                "ma20": round(ma20_now, 2),
                "ma30": round(ma30_now, 2),
                "ma60": round(ma60_now, 2),
                "ma60_violations": len(violations),
                "ma10_rise_3d": True,
                "duotou_days": consecutive,
            },
            "generated_at": generated_at,
            "data_source": "local_tongdaxin_daily",
        })

    results.sort(key=lambda item: (not bool(item.get("passed")), item.get("market", ""), item.get("symbol", "")))
    return results


def merge_strategy_rows_for_output(output: Path, strategy: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_rows: list[dict[str, Any]] = []
    if output.exists():
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                existing_rows = [row for row in payload if isinstance(row, dict)]
            elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
                existing_rows = [row for row in payload["rows"] if isinstance(row, dict)]
        except Exception:
            existing_rows = []
    merged = [row for row in existing_rows if str(row.get("strategy", "")).strip() != strategy]
    if rows:
        merged.extend(rows)
    else:
        # Sentinel row: marks this strategy as "built with 0 results" so the API
        # can distinguish from "not yet built" and show 0 results instead of all.
        merged.append({
            "trading_day": "",
            "market": "__sentinel__",
            "symbol": "000000",
            "strategy": strategy,
            "strategy_label": STRATEGY_METADATA.get(strategy, {}).get("label", strategy),
            "passed": False,
            "conditions": {},
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "data_source": "sentinel",
        })
    merged.sort(key=lambda item: (str(item.get("strategy", "")), not bool(item.get("passed")), str(item.get("market", "")), str(item.get("symbol", ""))))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stock screener strategy datasets")
    parser.add_argument("--strategy", default=STRATEGY_FIRST, choices=sorted(STRATEGY_METADATA))
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--trading-day", default=None, help="Build as of historical date (YYYY-MM-DD)")
    args = parser.parse_args()

    trading_day = args.trading_day

    # When trading_day is set, use date-specific output
    if trading_day:
        output = DEFAULT_DATASET_DIR / f"dataset_stock_screener_strategies_{trading_day}.json"
    else:
        output = Path(args.output)

    # Monkey-patch load_rps_rows to use historical RPS when trading_day is set
    if trading_day:
        from app.search.index import load_rps_rows_as_of
        import app.search.index as _idx

        _orig_load_rps_rows = _idx.load_rps_rows
        _idx.load_rps_rows = lambda **kw: load_rps_rows_as_of(trading_day)

        # Also monkey-patch rps_pullback / rps_first which read history directly
        _orig_Reader_factory = Reader.factory

        def _patched_factory(*fa, **kw):
            reader = _orig_Reader_factory(*fa, **kw)
            _orig_daily = reader.daily

            def _daily_wrapper(**dkw):
                result = _orig_daily(**dkw)
                if result is not None and not result.empty and trading_day:
                    result = result.sort_index()
                    mask = result.index <= trading_day
                    result = result.loc[mask]
                return result

            reader.daily = _daily_wrapper
            return reader

        Reader.factory = staticmethod(_patched_factory)

    try:
        if args.strategy == STRATEGY_FIRST:
            rows = build_rps_first_rows(tdxdir=args.tdxdir, trading_day=trading_day or "")
        elif args.strategy == STRATEGY_SLINGSHOT:
            rows = build_slingshot_trend_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_FIRST_MACD:
            rows = build_rps_first_macd_rows(tdxdir=args.tdxdir, trading_day=trading_day or "")
        elif args.strategy == STRATEGY_DUOTOU:
            rows = build_duotou_rows(tdxdir=args.tdxdir)
        elif args.strategy == STRATEGY_ATH:
            rows = build_ath_rps360_rows(tdxdir=args.tdxdir, trading_day=trading_day or "")
        else:
            rows = build_rps_first_rows(tdxdir=args.tdxdir, trading_day=trading_day or "")
    finally:
        # Restore monkey-patches
        if trading_day:
            _idx.load_rps_rows = _orig_load_rps_rows
            Reader.factory = staticmethod(_orig_Reader_factory)

    output.parent.mkdir(parents=True, exist_ok=True)
    output_rows = merge_strategy_rows_for_output(output, args.strategy, rows)
    output.write_text(json.dumps(output_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    passed_count = sum(1 for row in rows if row.get("passed"))
    print(json.dumps({"ok": True, "strategy": args.strategy, "rows": len(rows), "passed": passed_count, "output": str(output), "output_rows": len(output_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
