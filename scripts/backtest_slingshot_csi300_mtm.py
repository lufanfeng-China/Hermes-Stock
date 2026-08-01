#!/usr/bin/env python3
"""CSI300 slingshot-trend backtest using the MACD extreme-GC exit and strict MTM."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from mootdx.reader import Reader

ROOT = Path("/home/lufanfeng/Project-Hermes-Stock")
sys.path.insert(0, str(ROOT))
from app.strategy.macd_backtest_engine import simulate_portfolio

TDX_DIR = "/mnt/c/new_tdx64"
CONSTITUENTS = ROOT / "data/derived/datasets/final/csi300_constituents_current_20260728.json"


def load_codes() -> list[str]:
    codes = sorted({str(code).zfill(6) for code in json.loads(CONSTITUENTS.read_text(encoding="utf-8"))})
    if len(codes) != 300:
        raise ValueError(f"expected 300 CSI300 codes, got {len(codes)}")
    return codes


def build_slingshot_bars(daily: pd.DataFrame) -> pd.DataFrame:
    """Replicate stock-screener slingshot v5 conditions for every historical bar."""
    bars = daily[["open", "close", "volume"]].copy().sort_index()
    close = bars["close"].astype(float)
    open_ = bars["open"].astype(float)
    volume = bars["volume"].astype(float)
    low_body = pd.concat([open_, close], axis=1).min(axis=1)

    ma10 = close.rolling(10).mean()
    ma60 = close.rolling(60).mean()
    slope = ma10 - ma10.shift(3)
    cond1 = (
        (slope > 0)
        & (ma10.shift(2) < ma10.shift(3) + slope * 0.33)
        & (ma10.shift(1) < ma10.shift(3) + slope * 0.67)
    )
    cond2 = (low_body.shift(3) < low_body.shift(2)) & (low_body.shift(2) < low_body.shift(1)) & (low_body.shift(1) < low_body)
    cond3 = close < close.shift(10) * 1.30

    min_prior_10 = volume.shift(4).rolling(10).min()
    vol_ma50 = volume.rolling(50).mean()
    cond4 = (
        (volume > min_prior_10 * 3.0)
        & (volume.shift(1) > min_prior_10 * 3.0)
        & (volume.shift(2) > min_prior_10 * 3.0)
        & (volume > vol_ma50)
        & (volume.shift(1) > vol_ma50)
        & (volume.shift(2) > vol_ma50)
    )

    above_ma10 = low_body > ma10
    gap_component = ((low_body - ma10) * (10.0 / close)).where(above_ma10, 0.0)
    prior_component = gap_component.shift(1).fillna(0.0)
    prior_above = above_ma10.shift(1).fillna(False)
    run_id = (~prior_above).cumsum()
    run_gap = prior_component.groupby(run_id).cumsum()
    run_len = prior_above.astype(int).groupby(run_id).cumsum()
    gap_last_119 = prior_component.rolling(119, min_periods=1).sum()
    gap_total = run_gap.where(run_len <= 119, gap_last_119)
    cond5 = gap_total < 4.0

    bearish = close <= open_
    bear_large = bearish & (((open_ - close) / open_.replace(0, np.nan)) * 100 >= 2.0)
    cond6 = (bearish.astype(int).rolling(4).sum() <= 1) & (bear_large.astype(int).rolling(4).sum() == 0)
    cond7 = ma10 > ma60

    base = (cond1 & cond2 & cond3 & cond4 & cond5 & cond6 & cond7).fillna(False)
    prior_hits = base.shift(1).rolling(59, min_periods=1).max().fillna(0).astype(bool)
    buy = base & ~prior_hits

    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    ndif = np.where(close != 0, dif / close * 100, 0.0)
    ndea = np.where(close != 0, dea / close * 100, 0.0)
    dead_cross = (ndif < ndea) & (pd.Series(ndif, index=bars.index).shift(1) >= pd.Series(ndea, index=bars.index).shift(1))

    result = bars[["open", "close"]].copy()
    result["buy_signal"] = buy
    result["replenish_signal"] = False  # user requested only the extreme-GC sell logic, not its add-on rule
    result["dead_cross"] = dead_cross.fillna(False)
    result["ndif"] = ndif
    result["base_signal"] = base
    return result


def load_bars(start: str, end: str) -> tuple[dict[str, pd.DataFrame], dict[str, int], str]:
    lookback = f"{int(start[:4]) - 1}-07-01"
    reader = Reader.factory(market="std", tdxdir=TDX_DIR)
    bars_by_code: dict[str, pd.DataFrame] = {}
    signal_counts: dict[str, int] = {}
    last_day = ""
    for code in load_codes():
        try:
            daily = reader.daily(code)
        except Exception:
            continue
        if daily is None or len(daily) < 120:
            continue
        daily = daily.sort_index()
        daily = daily[(daily.index >= lookback) & (daily.index <= end)]
        if len(daily) < 120:
            continue
        bars = build_slingshot_bars(daily)
        bars = bars[bars.index >= pd.Timestamp(start)]
        if len(bars) < 2:
            continue
        bars_by_code[code] = bars
        signal_counts[code] = int(bars["buy_signal"].sum())
        last_day = max(last_day, str(bars.index[-1].date()))
    return bars_by_code, signal_counts, last_day


def annual_mtm(daily_equity: list[dict]) -> list[dict]:
    frame = pd.DataFrame(daily_equity)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date")
    yearly = frame.resample("YE").last()
    previous_equity: float | None = None
    rows: list[dict] = []
    final_date = frame.index[-1]
    for day, row in yearly.iterrows():
        equity = float(row["equity"])
        ret = None if previous_equity is None else equity / previous_equity - 1.0
        rows.append({
            "year": int(day.year),
            "equity": round(equity, 2),
            "return_pct": None if ret is None else round(ret * 100, 2),
            "partial": bool(day.year == final_date.year),
        })
        previous_equity = equity
    return rows


def summarize(result: dict, initial: float, signals: int) -> dict:
    summary = result["summary"]
    history = result["history"]
    equity_curve = result["daily_equity"]
    first_day = pd.Timestamp(equity_curve[0]["date"])
    last_day = pd.Timestamp(equity_curve[-1]["date"])
    elapsed_years = max((last_day - first_day).days / 365.25, 1 / 365.25)
    annualized = (float(summary["equity"]) / initial) ** (1 / elapsed_years) - 1
    realized_wins = sum(1 for row in history if float(row["pnl"]) > 0)
    return {
        "initial_capital": initial,
        "ending_equity": round(float(summary["equity"]), 2),
        "total_return_pct": round((float(summary["equity"]) / initial - 1) * 100, 2),
        "annualized_return_pct": round(annualized * 100, 2),
        "cash": round(float(summary["cash"]), 2),
        "market_value": round(float(summary["market_value"]), 2),
        "signal_count": signals,
        "opened_positions": len(history) + len(result["positions"]),
        "closed_positions": len(history),
        "open_positions": len(result["positions"]),
        "closed_win_rate_pct": round(realized_wins / len(history) * 100, 2) if history else None,
        "orders_executed": int(result["executed"]),
        "orders_rejected_cash_or_price": int(result["rejected"]),
        "annual_mtm": annual_mtm(result["daily_equity"]),
    }


def write_report(path: Path, *, start: str, end: str, universe_loaded: int, signals: int, results: list[dict]) -> None:
    lines = [
        "弹弓趋势 v5 · CSI300 · 严格 MTM 回测",
        "=" * 50,
        f"回测区间：{start} 至 {end}",
        f"股票池：当前 CSI300 成分股（加载 {universe_loaded}/300；存在幸存者偏差）",
        "信号：收盘满足股票筛选页弹弓趋势 v5；首个信号 60 日去重。",
        "执行：信号日收盘确认，T+1 开盘买入；每份 50,000 元，现金不透支。",
        "卖出：沿用极值金叉的卖出逻辑——收盘盈利超过 20% 后进入待机；随后 MACD 死叉或盈利跌破 15%，T+1 开盘全卖。",
        "补仓：未启用（用户只指定沿用极值金叉卖出逻辑）。",
        "记账：逐日真实现金 + 收盘持仓市值，严格 MTM。",
        "价格与成本：复用极值金叉引擎的本地 TDX 日线口径；未额外计入手续费、印花税、滑点。",
        "提示：因只在盈利超过 20% 后才允许退出，未平仓仓位不能计入已平仓胜率；应以期末严格 MTM 权益为准。",
        "",
        f"全周期原始信号：{signals}",
    ]
    for row in results:
        lines.extend([
            "",
            f"资金 {row['initial_capital']:,.0f}：期末权益 {row['ending_equity']:,.2f}，总收益 {row['total_return_pct']:+.2f}%，年化 {row['annualized_return_pct']:+.2f}%",
            f"  已开仓 {row['opened_positions']}，已平仓 {row['closed_positions']}，未平仓 {row['open_positions']}，"
            f"已平仓胜率 {row['closed_win_rate_pct'] if row['closed_win_rate_pct'] is not None else '—'}%，拒单 {row['orders_rejected_cash_or_price']}",
            "  逐年 MTM：",
        ])
        for annual in row["annual_mtm"]:
            mark = " (YTD)" if annual["partial"] else ""
            ret = "建仓年" if annual["return_pct"] is None else f"{annual['return_pct']:+.2f}%"
            lines.append(f"    {annual['year']}{mark}: 权益 {annual['equity']:,.2f}，年度收益 {ret}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2012-01-01")
    parser.add_argument("--end", default="2026-07-24")
    parser.add_argument("--lot", type=float, default=50_000)
    parser.add_argument("--capitals", type=float, nargs="+", default=[3_000_000, 6_000_000, 10_000_000])
    parser.add_argument("--output-dir", default="/mnt/c/Users/Sky.Lu/Desktop/output")
    args = parser.parse_args()

    bars_by_code, per_code_signals, last_day = load_bars(args.start, args.end)
    end = min(args.end, last_day) if last_day else args.end
    total_signals = sum(per_code_signals.values())
    results = []
    for capital in args.capitals:
        result = simulate_portfolio(bars_by_code, initial_capital=capital, lot_cash=args.lot)
        results.append(summarize(result, capital, total_signals))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = "弹弓趋势_CSI300_极值金叉退出_严格MTM_2012起_20260729_v2"
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"
    payload = {
        "strategy": "slingshot_trend_v5",
        "period": {"start": args.start, "end": end, "last_loaded_day": last_day},
        "universe": {"type": "current CSI300 constituents", "loaded": len(bars_by_code), "survivorship_bias": True},
        "entry": "Signal on close, T+1 open purchase",
        "exit": "Arm after close profit >20%; then MACD dead cross or profit <15%; T+1 open full exit",
        "replenishment": "disabled",
        "lot_cash": args.lot,
        "raw_signal_count": total_signals,
        "per_code_signal_count": per_code_signals,
        "results": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(text_path, start=args.start, end=end, universe_loaded=len(bars_by_code), signals=total_signals, results=results)
    print(json.dumps({"text": str(text_path), "json": str(json_path), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
