#!/usr/bin/env python3
"""CSI300 VCP/pullback breakout backtest with strict MTM and MACD-extreme exits.

All entries/signals are evaluated at close and routed to the unmodified shared
engine, which executes at the next global trading day's open with real cash.
TDX daily bars are raw/unadjusted, so the experiment is intentionally disclosed
as a current-constituent (survivorship-biased) proxy.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from mootdx.reader import Reader

ROOT = Path("/home/lufanfeng/Project-Hermes-Stock")
sys.path.insert(0, str(ROOT))
from app.strategy.macd_backtest_engine import simulate_portfolio

CSI_PATH = ROOT / "data/derived/datasets/final/csi300_constituents_current_20260728.json"
DEFAULT_TDX = "/home/lufanfeng/tdx_data"
STEM = "VCP横盘收窄突破_无高位回撤限制_CSI300_极值金叉退出_严格MTM_2012起_20260730_v2"


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
        if frame is None or frame.empty or not {"open", "high", "low", "close", "volume"}.issubset(frame.columns):
            failed.append(code)
            continue
        frame = frame.sort_index().copy()
        frame.index = pd.to_datetime(frame.index)
        prices[code] = frame[["open", "high", "low", "close", "volume"]].astype(float)
    if len(prices) != 300:
        raise RuntimeError(f"Strict universe requires 300 usable daily histories; loaded {len(prices)}, failed={failed}")
    common_end = min(frame.index.max() for frame in prices.values())
    data_start = min(frame.index.min() for frame in prices.values())
    prices = {code: frame[frame.index <= common_end].copy() for code, frame in prices.items()}
    return prices, {
        "requested": 300, "loaded": len(prices), "failed_codes": failed,
        "common_start": str(data_start.date()), "common_end": str(common_end.date()),
        "min_bars_through_common_end": min(len(frame) for frame in prices.values()),
        "max_bars_through_common_end": max(len(frame) for frame in prices.values()),
    }


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    close, high, low, volume = out.close, out.high, out.low, out.volume
    out["ma60"] = close.rolling(60, min_periods=60).mean()
    out["ma250"] = close.rolling(250, min_periods=250).mean()
    out["vma5"] = volume.rolling(5, min_periods=5).mean()
    out["vma20"] = volume.rolling(20, min_periods=20).mean()
    out["vma60"] = volume.rolling(60, min_periods=60).mean()
    out["vma120"] = volume.rolling(120, min_periods=120).mean()
    out["llv20"] = low.rolling(20, min_periods=20).min()
    out["llv60"] = low.rolling(60, min_periods=60).min()
    out["prior20high"] = high.shift(1).rolling(20, min_periods=20).max()
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    out["ndif"] = np.where(close != 0, dif / close * 100.0, np.nan)
    out["gold_cross"] = ((dif > dea) & (dif.shift(1) <= dea.shift(1))).fillna(False)
    out["dead_cross"] = ((dif < dea) & (dif.shift(1) >= dea.shift(1))).fillna(False)
    prev_close = close.shift(1)
    long_bearish_vol = ((close / prev_close - 1.0) < -0.05) & (volume > 2.0 * out.vma20)
    out["no_long_bearish_vol_40"] = ~long_bearish_vol.rolling(40, min_periods=40).max().fillna(1).astype(bool)
    out["breakout_buy_point"] = (close > out.prior20high) & (volume > out.vma5 * 1.5)
    out["macd_buy_point"] = out.gold_cross & out.ndif.between(-1.0, 1.0, inclusive="neither")
    out["buy_point"] = (out.breakout_buy_point | out.macd_buy_point).fillna(False)
    return out


def build_bars(prices: dict[str, pd.DataFrame], start: str) -> tuple[dict[str, pd.DataFrame], dict[str, int], dict[str, int]]:
    funnel: defaultdict[str, int] = defaultdict(int)
    bars_by_code: dict[str, pd.DataFrame] = {}
    per_code_entry: dict[str, int] = {}
    start_ts = pd.Timestamp(start)
    for code, raw in prices.items():
        frame = enrich(raw)
        eligible = frame.index >= start_ts
        ready = (frame.ma60.notna() & frame.ma250.notna() & frame.vma120.notna() &
                 frame.llv20.shift(20).notna() & frame.llv60.shift(1).notna() & frame.prior20high.notna() &
                 frame.no_long_bearish_vol_40.notna())
        stage = eligible & ready
        funnel["daily_bars_since_2012_with_all_required_lookbacks"] += int(stage.sum())
        conditions = [
            ("ma60_gte_ma60_10_trading_days_ago", frame.ma60 >= frame.ma60.shift(10)),
            ("close_gte_ma250_x_0_95", frame.close >= frame.ma250 * 0.95),
            ("vcp_hhv40_div_llv40_strictly_lt_1_20", high_low_ratio(frame.high, frame.low, 40) < 1.20),
            ("vcp_hhv20_div_llv20_strictly_lt_1_12", high_low_ratio(frame.high, frame.low, 20) < 1.12),
            ("vcp_hhv10_div_llv10_strictly_lt_1_06", high_low_ratio(frame.high, frame.low, 10) < 1.06),
            ("vma20_strictly_lt_vma60_strictly_lt_vma120", (frame.vma20 < frame.vma60) & (frame.vma60 < frame.vma120)),
            ("llv20_strictly_gt_llv20_20_trading_days_ago", frame.llv20 > frame.llv20.shift(20)),
            ("llv60_strictly_gt_llv60_1_trading_day_ago", frame.llv60 > frame.llv60.shift(1)),
            ("no_long_bearish_volume_bar_in_current_or_prior_39_days", frame.no_long_bearish_vol_40),
            ("buy_point_breakout_or_normalized_macd_golden_cross", frame.buy_point),
        ]
        for name, condition in conditions:
            stage = stage & condition.fillna(False)
            funnel[name] += int(stage.sum())
        bars = frame.loc[eligible, ["open", "close", "dead_cross", "ndif"]].copy()
        bars["buy_signal"] = stage.loc[eligible].fillna(False)
        # The engine adds the required state condition: existing holding and close PnL < -20%.
        bars["replenish_signal"] = frame.loc[eligible, "buy_point"].fillna(False)
        bars_by_code[code] = bars
        per_code_entry[code] = int(bars.buy_signal.sum())
    funnel["final_buy_signals"] = sum(per_code_entry.values())
    funnel["replenishment_buy_point_candidates_before_engine_position_and_pnl_gate"] = sum(int(frame.replenish_signal.sum()) for frame in bars_by_code.values())
    return bars_by_code, dict(funnel), per_code_entry


def high_low_ratio(high: pd.Series, low: pd.Series, window: int) -> pd.Series:
    return high.rolling(window, min_periods=window).max() / low.rolling(window, min_periods=window).min()


def annual_mtm(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(daily)
    frame["date"] = pd.to_datetime(frame.date)
    frame = frame.set_index("date")
    annual = frame.resample("YE").last()
    previous: float | None = None
    last_year = frame.index[-1].year
    output = []
    for day, row in annual.iterrows():
        equity, cash, market_value = float(row.equity), float(row.cash), float(row.market_value)
        output.append({
            "year": int(day.year), "equity": round(equity, 2), "cash": round(cash, 2), "market_value": round(market_value, 2),
            "return_pct": None if previous is None else round((equity / previous - 1.0) * 100.0, 2),
            "partial": int(day.year) == last_year,
            "equity_equals_cash_plus_market_value": abs(equity - cash - market_value) <= 0.01,
        })
        previous = equity
    return output


def summarize(result: dict[str, Any], capital: float, entry_signals: int, replenish_candidates: int) -> dict[str, Any]:
    summary = result["summary"]
    equity, cash, market_value = float(summary["equity"]), float(summary["cash"]), float(summary["market_value"])
    history, positions = result["history"], result["positions"]
    entry_executions = len(history) + len(positions)
    replenish_executions = int(result["executed"]) - len(history) - entry_executions
    daily = result["daily_equity"]
    first, last = pd.Timestamp(daily[0]["date"]), pd.Timestamp(daily[-1]["date"])
    years = max((last - first).days / 365.25, 1 / 365.25)
    all_daily_ok = all(abs(float(x["equity"]) - float(x["cash"]) - float(x["market_value"])) <= 0.01 for x in daily)
    return {
        "initial_capital": capital, "signal_count": entry_signals, "replenish_buy_point_candidates": replenish_candidates,
        "entry_executions": entry_executions, "replenishment_executions": replenish_executions,
        "closed_positions": len(history), "open_positions": len(positions), "orders_executed": int(result["executed"]),
        "orders_rejected_cash_or_price": int(result["rejected"]), "cash": round(cash, 2), "market_value": round(market_value, 2),
        "equity": round(equity, 2), "equity_equals_cash_plus_market_value": abs(equity - cash - market_value) <= 0.01,
        "all_daily_equity_equals_cash_plus_market_value": all_daily_ok, "total_return_pct": round((equity / capital - 1.0) * 100.0, 2),
        "annualized_return_pct": round(((equity / capital) ** (1.0 / years) - 1.0) * 100.0, 2),
        "annual_strict_mtm": annual_mtm(daily),
    }


def text_report(payload: dict[str, Any]) -> str:
    lines = ["VCP 横盘收窄突破（无高位回撤限制）· CSI300 · 极值金叉退出/补仓 · 严格 MTM（v2）", "=" * 76,
             f"股票池：2026-07-28 当前 CSI300 300 成分股（当前成分股幸存者偏差）。数据：{payload['data']['price_source']} 本地 TDX 原始/未复权日线；公共末日 {payload['data']['common_end']}。",
             "执行：收盘确认信号，未修改 app/strategy/macd_backtest_engine.py；该引擎使用全市场下一交易日 T+1 开盘、严格现金、单笔 50,000 元、无费税/滑点，并逐日按收盘市值 MTM。",
             "入场：不设距250日高点回撤限制；MA60>=10日前；close>=MA250*0.95；HHV/LLV 40/20/10日分别<1.20/<1.12/<1.06；VMA20<VMA60<VMA120；LLV20>20日前且LLV60>1日前；近40日（含当日）无跌幅<-5%且量>2×VMA20长阴量柱；买点为放量突破前20日high或 DIF 金叉且 DIF/close*100 严格(-1,+1)。",
             "退出：持仓收盘浮盈严格>20%后武装；武装后 MACD 死叉或收盘浮盈严格<15%，T+1 开盘卖出。补仓：持仓收盘 PnL<-20%时，每个 buy-point 收盘都会由引擎安排 T+1 固定50,000元补仓（无次数上限，受真实现金约束）。", "", "完整顺序漏斗："]
    lines.extend(f"  {key}: {value}" for key, value in payload["funnel"].items())
    for row in payload["results"]:
        lines.extend(["", f"初始资金 {row['initial_capital']:,.0f}：期末权益 {row['equity']:,.2f}，总收益 {row['total_return_pct']:+.2f}%，年化 {row['annualized_return_pct']:+.2f}%；现金 {row['cash']:,.2f} + 市值 {row['market_value']:,.2f}。",
                      f"  入场信号 {row['signal_count']}；实际开仓 {row['entry_executions']}；补仓执行 {row['replenishment_executions']}；已平 {row['closed_positions']}，未平 {row['open_positions']}；拒单 {row['orders_rejected_cash_or_price']}；每日权益校验={row['all_daily_equity_equals_cash_plus_market_value']}。", "  年度严格 MTM："])
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
    bars, funnel, per_code_entry = build_bars(prices, args.start)
    entry_signals = funnel["final_buy_signals"]
    replenish_candidates = funnel["replenishment_buy_point_candidates_before_engine_position_and_pnl_gate"]
    results = [summarize(simulate_portfolio(bars, initial_capital=capital, lot_cash=args.lot), capital, entry_signals, replenish_candidates) for capital in args.capitals]
    payload = {
        "version": "v2", "strategy": "vcp_contraction_breakout_no_high_drawdown_limit_csi300_strict_mtm_macd_extreme_exit_replenishment", "period": {"start": args.start, "end": data["common_end"]},
        "data": {"constituents_path": str(CSI_PATH), "price_source": args.tdx_dir, "raw_unadjusted_daily_bars": True, **data},
        "universe": {"type": "current CSI300 constituents as of 2026-07-28", "requested_count": 300, "loaded_count": len(bars), "survivorship_bias": True},
        "contracts": {"entry_execution": "close signal -> T+1 next global trading-day open via macd_backtest_engine", "lot_cash": args.lot, "replenishment": True,
                      "replenishment_rule": "while holding and close PnL < -20%, each subsequent buy-point schedules T+1 fixed-50,000 replenish; no count cap; strict-cash constrained",
                      "transaction_costs_included": False, "strict_mtm": True, "ma250_definition": "close >= MA250 * 0.95", "macd": "EMA(12,26) DIF, EMA(9) DEA; normalized DIF = DIF / close * 100"},
        "funnel": funnel, "signal_counts": {"entry_signals": entry_signals, "replenish_signals_emitted": replenish_candidates, "per_code_entry_signals": per_code_entry}, "results": results,
    }
    output_dir = Path(args.output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    json_path, text_path = output_dir / f"{STEM}.json", output_dir / f"{STEM}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    text_path.write_text(text_report(payload), encoding="utf-8")
    print(json.dumps({"script": str(Path(__file__).resolve()), "json": str(json_path), "text": str(text_path), "funnel": funnel, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
