#!/usr/bin/env python3
"""Build MACD signal dataset — 二次金叉/金叉转强/背离1次/背离2次/背离多次."""

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

from app.search.index import DEFAULT_DATASET_DIR, load_rps_rows

DEFAULT_TDX_DIR = "/mnt/c/new_tdx64"
DEFAULT_OUTPUT = DEFAULT_DATASET_DIR / "dataset_macd_signals_current.json"
DIVERGENCE_WINDOW = 90  # 背离检测回溯窗口


def _ema(values: list[float], period: int) -> list[float]:
    """计算指数移动平均"""
    if len(values) < period:
        return [0.0] * len(values)
    k = 2.0 / (period + 1)
    result = [0.0] * len(values)
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _compute_macd(closes: list[float]):
    """计算 MACD: (dif, dea, histogram)"""
    if len(closes) < 26:
        return None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = _ema(dif, 9)
    histogram = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]
    return dif, dea, histogram


def _find_local_minima(values: list[float], window: int = 5) -> list[int]:
    """找到局部极小值点的索引"""
    minima = []
    n = len(values)
    for i in range(window, n - window):
        left = values[i - window:i]
        right = values[i + 1:i + 1 + window]
        if values[i] <= min(left) and values[i] <= min(right):
            minima.append(i)
    return minima


def detect_signals(
    closes: list[float],
    dif: list[float],
    dea: list[float],
    hist: list[float],
    volumes: list[float],
) -> str:
    """返回信号标签: '二次金叉'/'金叉转强'/'背离1次'/'背离2次'/'背离多次'/''"""
    n = len(closes)
    if n < 120:
        return ""

    ti = n - 1  # today index

    # ── 金叉检测 ──
    is_golden = dif[ti] > dea[ti] and dif[ti - 1] <= dea[ti - 1]

    # ── MA20 ──
    def _ma(vals, period, idx):
        if idx < period - 1:
            return None
        return sum(vals[idx - period + 1:idx + 1]) / period

    ma20 = _ma(closes, 20, ti)
    if ma20 is None:
        return ""

    dist_ma20 = (closes[ti] - ma20) / ma20 * 100.0

    # ── 均量 ──
    vol5 = sum(volumes[max(0, ti - 4):ti + 1]) / 5
    vol20 = sum(volumes[max(0, ti - 19):ti + 1]) / 20

    # ═══════════════════════════════════════
    # 二次金叉
    # ═══════════════════════════════════════
    if is_golden and dif[ti] > 0 and dea[ti] > 0:
        # 近20日内有过一次金叉后回调(DIF回落但未破0轴)
        had_prev_golden = False
        for i in range(ti - 20, ti - 1):
            if i < 1:
                continue
            if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
                had_prev_golden = True
                break
        if had_prev_golden:
            # 辅助: 现价距MA20 >2%且<5%
            if 2.0 < abs(dist_ma20) < 5.0:
                # 缩量回调+放量上涨
                if vol5 < vol20 and volumes[ti] > vol5:
                    return "二次金叉"

    # ═══════════════════════════════════════
    # 金叉转强
    # ═══════════════════════════════════════
    if is_golden:
        # DIF从0轴下方上穿，金叉时DIF在-0.5~+0.5
        dif_near_zero = -0.5 <= dif[ti] <= 0.5
        was_below = any(dif[i] < 0 for i in range(max(0, ti - 10), ti))
        if dif_near_zero and was_below:
            # 现价>MA20
            if closes[ti] > ma20:
                # 今日放量
                if volumes[ti] > vol5:
                    # 近5日最高接近20日最高
                    high5 = max(closes[max(0, ti - 4):ti + 1])
                    high20 = max(closes[max(0, ti - 19):ti + 1])
                    if high5 >= high20 * 0.95:
                        return "金叉转强"

    # ═══════════════════════════════════════
    # 背离检测 (90日窗口)
    # ═══════════════════════════════════════
    window_start = max(0, ti - DIVERGENCE_WINDOW)
    window_closes = closes[window_start:ti + 1]
    window_dif = dif[window_start:ti + 1]
    window_hist = hist[window_start:ti + 1]

    # 找局部低点（宽窗口避免重复计数）
    minima_idx = _find_local_minima(window_closes, window=8)

    if len(minima_idx) >= 2:
        # 检测每对相邻低点的背离
        divergence_count = 0
        for j in range(1, len(minima_idx)):
            prev = minima_idx[j - 1]
            curr = minima_idx[j]
            # 股价创新低，DIF未创新低
            price_new_low = window_closes[curr] < window_closes[prev]
            dif_higher = window_dif[curr] > window_dif[prev]
            # 绿柱缩短
            hist_shorter = abs(window_hist[curr]) < abs(window_hist[prev]) * 0.8

            if price_new_low and dif_higher and hist_shorter:
                divergence_count += 1

        # 最近的低点必须是背离（才输出信号）
        if divergence_count >= 1:
            last_curr = minima_idx[-1]
            last_prev = minima_idx[-2]
            last_is_div = (
                window_closes[last_curr] < window_closes[last_prev]
                and window_dif[last_curr] > window_dif[last_prev]
                and abs(window_hist[last_curr]) < abs(window_hist[last_prev]) * 0.8
            )
            if last_is_div:
                # 辅助: 缩量跌+现价上穿MA20
                if vol5 < vol20 and closes[ti] > ma20:
                    if divergence_count == 1:
                        return "背离1次"
                    elif divergence_count == 2:
                        return "背离2次"
                    else:
                        return "背离多次"

    return ""


def build_macd_signals(*, tdxdir: str = DEFAULT_TDX_DIR) -> list[dict[str, Any]]:
    reader = Reader.factory(market="std", tdxdir=tdxdir)
    rps_rows = load_rps_rows()
    results: list[dict[str, Any]] = []
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    for row in rps_rows:
        market_val = str(row.get("market", "")).strip().lower()
        symbol_val = str(row.get("symbol", "")).strip()
        if not market_val or not symbol_val:
            continue

        try:
            daily = reader.daily(symbol=symbol_val)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()

        closes = daily["close"].astype(float).tolist()
        volumes = daily["volume"].astype(float).tolist()

        macd_data = _compute_macd(closes)
        if macd_data is None:
            continue
        dif, dea, hist = macd_data

        signal = detect_signals(closes, dif, dea, hist, volumes)
        if signal:
            results.append({
                "market": market_val,
                "symbol": symbol_val,
                "macd_signal": signal,
                "generated_at": generated_at,
                "data_source": "local_tongdaxin_daily",
            })

    results.sort(key=lambda r: (r["macd_signal"], r["market"], r["symbol"]))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MACD signal dataset")
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    output = Path(args.output)
    rows = build_macd_signals(tdxdir=args.tdxdir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    by_signal = {}
    for r in rows:
        by_signal[r["macd_signal"]] = by_signal.get(r["macd_signal"], 0) + 1

    print(json.dumps({
        "ok": True, "total": len(rows),
        "by_signal": by_signal,
        "output": str(output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
