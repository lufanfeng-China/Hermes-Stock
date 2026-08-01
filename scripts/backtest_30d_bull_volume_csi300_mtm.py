#!/usr/bin/env python3
"""30-day bull-candle volume-dominance CSI300 strict-MTM backtest.

Signals are decided at the close and passed unchanged to the shared MACD engine:
normal entries execute T+1 open; while held, the identical signal can replenish
only when close PnL is strictly below -20%.  Local TDX bars are raw/unadjusted.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from mootdx.reader import Reader

ROOT = Path("/home/lufanfeng/Project-Hermes-Stock")
sys.path.insert(0, str(ROOT))
from app.strategy.macd_backtest_engine import simulate_portfolio

CSI_PATH = ROOT / "data/derived/datasets/final/csi300_constituents_current_20260728.json"
DEFAULT_TDX = "/home/lufanfeng/tdx_data"
STEM = "30日阳量优势_CSI300_极值金叉退出补仓_严格MTM_2012起_20260730_v1"


def load_universe() -> list[str]:
    codes = sorted({str(code).zfill(6) for code in json.loads(CSI_PATH.read_text(encoding="utf-8"))})
    if len(codes) != 300:
        raise RuntimeError(f"Expected exactly 300 current CSI300 constituents, got {len(codes)}")
    return codes


def load_prices(codes: list[str], tdx_dir: str) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    reader = Reader.factory(market="std", tdxdir=tdx_dir)
    prices: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for code in codes:
        try:
            frame = reader.daily(code)
        except Exception:
            frame = None
        if frame is None or frame.empty or not {"open", "close", "volume"}.issubset(frame.columns):
            failed.append(code)
            continue
        frame = frame.sort_index().copy()
        frame.index = pd.to_datetime(frame.index)
        prices[code] = frame[["open", "close", "volume"]].astype(float)
    if len(prices) != 300:
        raise RuntimeError(f"Strict universe requires 300 usable daily histories; loaded {len(prices)}, failed={failed}")
    common_end = min(frame.index.max() for frame in prices.values())
    prices = {code: frame.loc[frame.index <= common_end].copy() for code, frame in prices.items()}
    return prices, {
        "requested": 300, "loaded": len(prices), "failed_codes": failed,
        "common_start": str(min(frame.index.min() for frame in prices.values()).date()),
        "common_end": str(common_end.date()),
        "min_bars_through_common_end": min(len(frame) for frame in prices.values()),
        "max_bars_through_common_end": max(len(frame) for frame in prices.values()),
    }


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    close = out["close"]
    # Exact rolling 30 trading-day contract, including the signal-close bar.
    out["window_max_close"] = close.rolling(30, min_periods=30).max()
    out["window_min_close"] = close.rolling(30, min_periods=30).min()
    out["bull"] = close > out["open"]
    out["bear"] = ~out["bull"]  # close <= open, including doji candles.
    out["bull_volume_30"] = out["volume"].where(out["bull"], 0.0).rolling(30, min_periods=30).sum()
    out["bear_volume_30"] = out["volume"].where(out["bear"], 0.0).rolling(30, min_periods=30).sum()
    out["bull_count_30"] = out["bull"].astype(int).rolling(30, min_periods=30).sum()
    out["bear_count_30"] = out["bear"].astype(int).rolling(30, min_periods=30).sum()
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    out["dead_cross"] = ((dif < dea) & (dif.shift(1) >= dea.shift(1))).fillna(False)
    out["ndif"] = dif / close * 100.0
    return out


def build_bars(prices: dict[str, pd.DataFrame], start: str) -> tuple[dict[str, pd.DataFrame], dict[str, int], dict[str, int]]:
    funnel: defaultdict[str, int] = defaultdict(int)
    bars_by_code: dict[str, pd.DataFrame] = {}
    per_code_signals: dict[str, int] = {}
    start_ts = pd.Timestamp(start)
    for code, raw in prices.items():
        frame = enrich(raw)
        eligible = frame.index >= start_ts
        ready = frame["window_min_close"].notna() & (frame["window_min_close"] > 0)
        stage = eligible & ready
        funnel["daily_bars_since_2012_with_30_trading_day_window"] += int(stage.sum())
        range_ok = (frame["window_max_close"] / frame["window_min_close"] - 1.0) < 0.15
        stage &= range_ok.fillna(False)
        funnel["30d_max_close_div_min_close_minus_1_strictly_lt_15pct"] += int(stage.sum())
        volume_ok = frame["bull_volume_30"] >= 2.0 * frame["bear_volume_30"]
        stage &= volume_ok.fillna(False)
        funnel["bull_volume_sum_gte_2x_bear_volume_sum"] += int(stage.sum())
        count_ok = frame["bull_count_30"] > 2.0 * frame["bear_count_30"]
        stage &= count_ok.fillna(False)
        funnel["bull_candle_count_strictly_gt_2x_bear_count"] += int(stage.sum())
        signals = stage.loc[eligible].fillna(False)
        bars = frame.loc[eligible, ["open", "close", "dead_cross", "ndif"]].copy()
        bars["buy_signal"] = signals
        # Shared engine imposes the holding + strictly <-20% PnL gate.
        bars["replenish_signal"] = signals
        bars_by_code[code] = bars
        per_code_signals[code] = int(signals.sum())
    funnel["final_entry_signals"] = sum(per_code_signals.values())
    funnel["replenish_signals_emitted_same_30d_condition_before_engine_holding_pnl_gate"] = sum(
        int(frame["replenish_signal"].sum()) for frame in bars_by_code.values()
    )
    return bars_by_code, dict(funnel), per_code_signals


def annual_mtm(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(daily)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date")
    annual = frame.resample("YE").last()
    previous: float | None = None
    final_year = frame.index[-1].year
    rows = []
    for day, row in annual.iterrows():
        equity, cash, market_value = float(row.equity), float(row.cash), float(row.market_value)
        rows.append({"year": int(day.year), "equity": round(equity, 2), "cash": round(cash, 2),
                     "market_value": round(market_value, 2), "return_pct": None if previous is None else round((equity / previous - 1.0) * 100.0, 2),
                     "partial": int(day.year) == final_year,
                     "equity_equals_cash_plus_market_value": abs(equity - cash - market_value) <= 0.01})
        previous = equity
    return rows


def summarize(result: dict[str, Any], capital: float, entry_signals: int, replenish_signals: int) -> dict[str, Any]:
    summary, daily = result["summary"], result["daily_equity"]
    cash, market_value, equity = float(summary["cash"]), float(summary["market_value"]), float(summary["equity"])
    history, positions = result["history"], result["positions"]
    entry_executions = len(history) + len(positions)
    exit_executions = len(history)
    replenish_executions = int(result["executed"]) - entry_executions - exit_executions
    first, last = pd.Timestamp(daily[0]["date"]), pd.Timestamp(daily[-1]["date"])
    years = max((last - first).days / 365.25, 1.0 / 365.25)
    daily_ok = all(abs(float(x["equity"]) - float(x["cash"]) - float(x["market_value"])) <= 0.01 for x in daily)
    return {"initial_capital": capital, "entry_signals": entry_signals, "replenish_signals_emitted": replenish_signals,
            "entry_executions": entry_executions, "replenishment_executions": replenish_executions,
            "exit_executions": exit_executions, "closed_positions": len(history), "open_positions": len(positions),
            "orders_executed": int(result["executed"]), "orders_rejected_cash_or_price": int(result["rejected"]),
            "cash": round(cash, 2), "market_value": round(market_value, 2), "equity": round(equity, 2),
            "equity_equals_cash_plus_market_value": abs(equity - cash - market_value) <= 0.01,
            "all_daily_equity_equals_cash_plus_market_value": daily_ok,
            "total_return_pct": round((equity / capital - 1.0) * 100.0, 2),
            "annualized_return_pct": round(((equity / capital) ** (1.0 / years) - 1.0) * 100.0, 2),
            "annual_strict_mtm": annual_mtm(daily)}


def text_report(payload: dict[str, Any]) -> str:
    lines = ["30日阳量优势 · CSI300 · 极值MACD退出/补仓 · 严格MTM（v1）", "=" * 76,
             f"股票池：2026-07-28当前CSI300成分股300只（存在当前成分股幸存者偏差）。数据：{payload['data']['price_source']}本地TDX原始/未复权日线；公共末日 {payload['period']['end']}。",
             "信号（均含信号日收盘的当前滚动30个交易日）：max(close)/min(close)-1 严格<15%；阳线=close>open、阴线/十字=close<=open；阳线volume之和≥2×阴线volume之和；阳线根数严格>2×阴线根数。收盘确认，T+1下一可用交易日开盘执行。",
             "退出/补仓：复用未修改的 macd_backtest_engine.py。持仓收盘PnL严格>20%后武装，武装后MACD死叉或PnL严格<15%则T+1开盘全卖；相同30日信号在持仓且收盘PnL严格<-20%时T+1固定50,000元补仓，无次数上限、受真实现金约束。",
             "严格现金、逐日收盘MTM；无手续费、印花税或滑点。", "", "完整顺序漏斗："]
    lines.extend(f"  {key}: {value}" for key, value in payload["funnel"].items())
    for row in payload["results"]:
        lines.extend(["", f"初始资金 {row['initial_capital']:,.0f}：期末权益 {row['equity']:,.2f}，总收益 {row['total_return_pct']:+.2f}%，年化 {row['annualized_return_pct']:+.2f}%；现金 {row['cash']:,.2f} + 市值 {row['market_value']:,.2f}。",
                      f"  入场信号 {row['entry_signals']}；补仓信号发出 {row['replenish_signals_emitted']}；实际开仓 {row['entry_executions']}；补仓执行 {row['replenishment_executions']}；已平 {row['closed_positions']}，未平 {row['open_positions']}；拒单 {row['orders_rejected_cash_or_price']}；每日权益校验={row['all_daily_equity_equals_cash_plus_market_value']}。", "  年度严格MTM："])
        for annual in row["annual_strict_mtm"]:
            ret = "起始年" if annual["return_pct"] is None else f"{annual['return_pct']:+.2f}%"
            lines.append(f"    {annual['year']}{' (YTD)' if annual['partial'] else ''}: 权益 {annual['equity']:,.2f}，收益 {ret}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tdx-dir", default=DEFAULT_TDX)
    parser.add_argument("--start", default="2012-01-01")
    parser.add_argument("--output-dir", default="/mnt/c/Users/Sky.Lu/Desktop/output")
    parser.add_argument("--lot", type=float, default=50_000)
    parser.add_argument("--capitals", type=float, nargs="+", default=[3_000_000, 6_000_000, 10_000_000])
    args = parser.parse_args()
    codes = load_universe()
    prices, data = load_prices(codes, args.tdx_dir)
    bars, funnel, per_code = build_bars(prices, args.start)
    entry_signals = funnel["final_entry_signals"]
    replenish_signals = funnel["replenish_signals_emitted_same_30d_condition_before_engine_holding_pnl_gate"]
    results = [summarize(simulate_portfolio(bars, initial_capital=capital, lot_cash=args.lot), capital, entry_signals, replenish_signals) for capital in args.capitals]
    payload = {"version": "v1", "strategy": "30d_bull_candle_volume_dominance_csi300_strict_mtm_macd_extreme_exit_replenishment",
               "period": {"start": args.start, "end": data["common_end"]},
               "data": {"constituents_path": str(CSI_PATH), "price_source": args.tdx_dir, "raw_unadjusted_daily_bars": True, **data},
               "universe": {"type": "current CSI300 constituents as of 2026-07-28", "requested_count": 300, "loaded_count": len(bars), "survivorship_bias": True},
               "contracts": {"signal_window": "current rolling 30 trading-day window including signal close", "range": "max(close)/min(close)-1 < 0.15", "bull": "close > open", "bear": "close <= open", "bull_volume": "sum(volume where bull) >= 2 * sum(volume where bear)", "bull_count": "bull_count > 2 * bear_count", "entry_execution": "signal close -> T+1 next available open via macd_backtest_engine", "exit": "close PnL >20% arms; then MACD dead cross or PnL <15%; T+1 open full exit", "replenishment": True, "replenishment_rule": "same 30d condition while holding and close PnL < -20%; T+1 fixed 50,000; no count cap; strict-cash constrained", "lot_cash": args.lot, "transaction_costs_included": False, "strict_mtm": True},
               "funnel": funnel, "signal_counts": {"entry_signals": entry_signals, "replenish_signals_emitted": replenish_signals, "per_code_entry_signals": per_code}, "results": results}
    output_dir = Path(args.output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    json_path, text_path = output_dir / f"{STEM}.json", output_dir / f"{STEM}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(text_report(payload), encoding="utf-8")
    print(json.dumps({"script": str(Path(__file__).resolve()), "json": str(json_path), "text": str(text_path), "funnel": funnel, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
