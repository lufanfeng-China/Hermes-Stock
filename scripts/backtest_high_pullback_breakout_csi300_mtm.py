#!/usr/bin/env python3
"""Reusable CSI300 strict-MTM test: high-pullback consolidation breakout.

Signal is known at close and entered at T+1 open.  The unmodified application
MACD engine provides strict cash, daily MTM, and the stateful exit contract.
TDX prices are raw/unadjusted daily bars.  ATR here means the *simple rolling
mean* of True Range, not Wilder-smoothed ATR.
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
STEM = "高位回调横盘突破_CSI300_极值金叉退出_严格MTM_2012起_20260729_v1"


def load_universe() -> list[str]:
    codes = sorted({str(x).zfill(6) for x in json.loads(CSI_PATH.read_text(encoding="utf-8"))})
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
        frame = frame[["open", "high", "low", "close", "volume"]].astype(float)
        prices[code] = frame
    if len(prices) != 300:
        raise RuntimeError(f"Strict universe requires 300 usable daily histories; loaded {len(prices)}, failed={failed}")
    # The experiment ends at the earliest final bar among all current components.
    # "Last common price date" defines the common end only.  Do not truncate all
    # histories to the newest constituent's IPO date: that would discard 2012+
    # history and eliminate valid old signals.  Recent IPOs simply have no signals
    # until their individual lookbacks are available.
    data_start = min(frame.index.min() for frame in prices.values())
    common_end = min(frame.index.max() for frame in prices.values())
    prices = {code: frame[frame.index <= common_end].copy() for code, frame in prices.items()}
    return prices, {"requested": 300, "loaded": len(prices), "failed_codes": failed,
                    "common_start": str(data_start.date()), "common_end": str(common_end.date()),
                    "min_bars_through_common_end": min(len(f) for f in prices.values()), "max_bars_through_common_end": max(len(f) for f in prices.values())}


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    close, high, low, volume = out.close, out.high, out.low, out.volume
    out["prior_250_high"] = high.shift(1).rolling(250, min_periods=250).max()
    out["drawdown"] = close / out.prior_250_high - 1
    out["amplitude_40"] = (high.rolling(40).max() - low.rolling(40).min()) / low.rolling(40).min()
    out["vma20"] = volume.rolling(20).mean()
    out["vma120"] = volume.rolling(120).mean()
    out["ma20"] = close.rolling(20).mean()
    out["ma60"] = close.rolling(60).mean()
    out["ma60_10d_ago"] = out.ma60.shift(10)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    out["atr20_simple_tr"] = tr.rolling(20).mean()
    out["atr120_simple_tr"] = tr.rolling(120).mean()
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    out["ndif"] = np.where(close != 0, dif / close * 100, np.nan)
    out["dead_cross"] = ((dif < dea) & (dif.shift(1) >= dea.shift(1))).fillna(False)
    # This is intentionally excluding the current bar, as required for an event breakout.
    out["prior_20_high"] = high.shift(1).rolling(20, min_periods=20).max()
    return out


def build_bars(prices: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    funnel: defaultdict[str, int] = defaultdict(int)
    bars_by_code: dict[str, pd.DataFrame] = {}
    for code, raw in prices.items():
        frame = enrich(raw)
        ready = frame.prior_250_high.notna() & frame.vma120.notna() & frame.ma60_10d_ago.notna() & frame.atr120_simple_tr.notna() & frame.prior_20_high.notna()
        stage = ready
        funnel["daily_bars_with_all_required_lookbacks"] += int(stage.sum())
        conditions = [
            ("drawdown_close_vs_prior_250_high_inclusive_minus45_to_minus20", frame.drawdown.between(-0.45, -0.20, inclusive="both")),
            ("last_40_days_amplitude_strictly_lt_20pct", frame.amplitude_40 < 0.20),
            ("vma20_strictly_lt_vma120_x_0_70", frame.vma20 < frame.vma120 * 0.70),
            ("abs_ma20_div_ma60_minus1_strictly_lt_5pct", (frame.ma20 / frame.ma60 - 1).abs() < 0.05),
            ("ma60_gte_its_10_trading_days_ago", frame.ma60 >= frame.ma60_10d_ago),
            ("atr20_simple_true_range_mean_strictly_lt_atr120", frame.atr20_simple_tr < frame.atr120_simple_tr),
            ("normalized_dif_inclusive_minus1_to_plus1", frame.ndif.between(-1.0, 1.0, inclusive="both")),
            ("volume_gte_vma20_x_1_5", frame.volume >= frame.vma20 * 1.5),
            ("bullish_close_strictly_gt_open", frame.close > frame.open),
            ("close_strictly_gt_prior_20_trading_day_high_max", frame.close > frame.prior_20_high),
        ]
        for name, cond in conditions:
            stage = stage & cond.fillna(False)
            funnel[name] += int(stage.sum())
        bars = frame[["open", "close", "dead_cross", "ndif"]].copy()
        bars["buy_signal"] = stage
        bars["replenish_signal"] = False
        bars_by_code[code] = bars
    funnel["final_buy_signals"] = sum(int(frame.buy_signal.sum()) for frame in bars_by_code.values())
    funnel["replenish_signals"] = 0
    return bars_by_code, dict(funnel)


def annual_mtm(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(daily)
    frame["date"] = pd.to_datetime(frame.date)
    frame = frame.set_index("date")
    annual = frame.resample("YE").last()
    previous = None
    last_year = frame.index[-1].year
    output = []
    for date, row in annual.iterrows():
        equity, cash, mv = float(row.equity), float(row.cash), float(row.market_value)
        output.append({"year": int(date.year), "equity": round(equity, 2), "cash": round(cash, 2), "market_value": round(mv, 2),
                       "return_pct": None if previous is None else round((equity / previous - 1) * 100, 2),
                       "partial": int(date.year) == last_year, "equity_equals_cash_plus_market_value": abs(equity - cash - mv) <= 0.01})
        previous = equity
    return output


def summarize(result: dict[str, Any], capital: float, signals: int) -> dict[str, Any]:
    s = result["summary"]
    equity, cash, mv = float(s["equity"]), float(s["cash"]), float(s["market_value"])
    all_daily_ok = all(abs(float(x["equity"]) - float(x["cash"]) - float(x["market_value"])) <= 0.01 for x in result["daily_equity"])
    first, last = pd.Timestamp(result["daily_equity"][0]["date"]), pd.Timestamp(result["daily_equity"][-1]["date"])
    years = max((last - first).days / 365.25, 1 / 365.25)
    return {"initial_capital": capital, "signal_count": signals, "opened_positions": len(result["history"]) + len(result["positions"]),
            "closed_positions": len(result["history"]), "open_positions": len(result["positions"]), "orders_executed": int(result["executed"]), "orders_rejected_cash_or_price": int(result["rejected"]),
            "cash": round(cash, 2), "market_value": round(mv, 2), "equity": round(equity, 2), "equity_equals_cash_plus_market_value": abs(equity-cash-mv) <= .01,
            "all_daily_equity_equals_cash_plus_market_value": all_daily_ok, "total_return_pct": round((equity/capital-1)*100, 2),
            "annualized_return_pct": round(((equity/capital)**(1/years)-1)*100, 2), "annual_strict_mtm": annual_mtm(result["daily_equity"])}


def text_report(payload: dict[str, Any]) -> str:
    lines = ["高位回调横盘突破 · CSI300 · 极值金叉退出 · 严格MTM 回测（v1）", "=" * 72,
             f"股票池：2026-07-28 当前 CSI300 300 成分股（存在当前成分股幸存者偏差）。本地 TDX 原始/未复权日线，公共区间 {payload['data']['common_start']} 至 {payload['data']['common_end']}。",
             "信号于收盘确认，按原样复用 app/strategy/macd_backtest_engine.py：T+1 全市场下一交易日开盘买入/卖出；严格现金、50,000 元单笔目标、无费税滑点；补仓关闭。",
             "退出：收盘浮盈严格>20%后武装；武装后 MACD(12,26,9) 死叉或收盘浮盈严格<15%，T+1 开盘全卖。ATR=TR 的简单滚动均值（非 Wilder ATR）。",
             "规则：close/prior_250_high-1 在[-45%,-20%]；40日振幅<20%；VMA20<VMA120*0.7；|MA20/MA60-1|<5%；MA60>=10交易日前MA60；ATR20<ATR120；DIF/close*100在[-1,+1]；volume>=VMA20*1.5；close>open；close>前20交易日（不含当日）最高high。", "", "完整顺序漏斗："]
    lines.extend(f"  {k}: {v}" for k, v in payload["funnel"].items())
    for r in payload["results"]:
        lines += ["", f"初始资金 {r['initial_capital']:,.0f}：期末权益 {r['equity']:,.2f}，总收益 {r['total_return_pct']:+.2f}%，年化 {r['annualized_return_pct']:+.2f}%；现金 {r['cash']:,.2f} + 市值 {r['market_value']:,.2f}。",
                  f"  信号 {r['signal_count']}；开仓 {r['opened_positions']}，已平 {r['closed_positions']}，未平 {r['open_positions']}；拒单 {r['orders_rejected_cash_or_price']}；每日权益校验={r['all_daily_equity_equals_cash_plus_market_value']}。", "  年度严格 MTM："]
        for row in r["annual_strict_mtm"]:
            ret = "起始年" if row["return_pct"] is None else f"{row['return_pct']:+.2f}%"
            lines.append(f"    {row['year']}{' (YTD)' if row['partial'] else ''}: 权益 {row['equity']:,.2f}，收益 {ret}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tdx-dir", default=DEFAULT_TDX); ap.add_argument("--output-dir", default="/mnt/c/Users/Sky.Lu/Desktop/output")
    ap.add_argument("--lot", type=float, default=50_000); ap.add_argument("--capitals", type=float, nargs="+", default=[3_000_000, 6_000_000, 10_000_000])
    args = ap.parse_args()
    codes = load_universe(); prices, data = load_prices(codes, args.tdx_dir); bars, funnel = build_bars(prices)
    signals = funnel["final_buy_signals"]
    results = [summarize(simulate_portfolio(bars, initial_capital=c, lot_cash=args.lot), c, signals) for c in args.capitals]
    payload = {"version": "v1", "strategy": "high_pullback_consolidation_breakout_csi300_strict_mtm", "data": {"constituents_path": str(CSI_PATH), "price_source": args.tdx_dir, **data},
               "universe": {"type": "current CSI300 constituents as of 2026-07-28", "requested_count": 300, "loaded_count": 300, "survivorship_bias": True},
               "contracts": {"entry_execution": "close signal -> T+1 next global trading-day open via macd_backtest_engine", "lot_cash": args.lot, "replenishment": False, "transaction_costs_included": False, "strict_mtm": True,
                             "atr": "simple rolling mean of True Range", "ma60_flat_slightly_up": "MA60[t] >= MA60[t-10 trading days]", "breakout": "close[t] > max(high[t-20:t])"},
               "funnel": funnel, "results": results}
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    json_path, txt_path = out / f"{STEM}.json", out / f"{STEM}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); txt_path.write_text(text_report(payload), encoding="utf-8")
    print(json.dumps({"script": str(Path(__file__).resolve()), "json": str(json_path), "text": str(txt_path), "funnel": funnel, "results": results}, ensure_ascii=False))

if __name__ == "__main__":
    main()
