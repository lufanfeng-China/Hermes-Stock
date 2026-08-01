#!/usr/bin/env python3
"""Exact RPS-first CSI300 strict-MTM backtest (RPS coverage begins 2013-01-15).

The script deliberately reuses app.strategy.macd_backtest_engine.simulate_portfolio
for cash accounting, T+1 execution, and its stateful >20% arm / MACD dead-cross or
<15% exit.  It does not modify application code or enable replenishment.
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

RPS_PATH = ROOT / "data/derived/datasets/final/dataset_stock_rps_history.parquet"
CSI_PATH = ROOT / "data/derived/datasets/final/csi300_constituents_current_20260728.json"
DEFAULT_TDX = "/home/lufanfeng/tdx_data"
STEM = "RPS首次_CSI300_极值金叉退出_严格MTM_2013起_20260729_v1"


def normalize_market(value: object) -> str:
    text = str(value).lower()
    return "sz" if text in {"0", "sz"} else "sh"


def load_universe() -> list[str]:
    codes = sorted({str(x).zfill(6) for x in json.loads(CSI_PATH.read_text(encoding="utf-8"))})
    if len(codes) != 300:
        raise RuntimeError(f"Expected 300 current CSI300 codes, found {len(codes)}")
    return codes


def macd_columns(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    golden = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    dead = (dif < dea) & (dif.shift(1) >= dea.shift(1))
    return dif, dea, golden.fillna(False), dead.fillna(False)


def load_price_bars(codes: list[str], tdx_dir: str) -> tuple[dict[tuple[str, str], pd.DataFrame], dict[str, int]]:
    reader = Reader.factory(market="std", tdxdir=tdx_dir)
    data: dict[tuple[str, str], pd.DataFrame] = {}
    stats = {"requested": len(codes), "loaded": 0, "failed": 0, "short_history": 0}
    for code in codes:
        try:
            frame = reader.daily(code)
        except Exception:
            stats["failed"] += 1
            continue
        if frame is None or frame.empty:
            stats["failed"] += 1
            continue
        frame = frame.sort_index().copy()
        frame.index = pd.to_datetime(frame.index)
        required = {"open", "close"}
        if not required.issubset(frame.columns) or len(frame) < 65:
            stats["short_history"] += 1
            continue
        frame = frame[["open", "close"]].astype(float)
        market = "sh" if code.startswith("6") else "sz"
        data[(market, code)] = frame
        stats["loaded"] += 1
    return data, stats


def price_conditions(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    close = out["close"]
    out["ma5"] = close.rolling(5).mean()
    out["ma10"] = close.rolling(10).mean()
    out["ma20"] = close.rolling(20).mean()
    out["ma60"] = close.rolling(60).mean()
    out["close_10d_high"] = close.eq(close.rolling(10).max())
    _, _, out["golden_cross"], out["dead_cross"] = macd_columns(close)
    out["eligible_history"] = np.arange(len(out)) + 1 >= 65
    return out


def make_rps_maps(codes: set[str]) -> tuple[list[pd.Timestamp], dict[pd.Timestamp, dict[tuple[str, str], tuple[float, float, float, float]]], dict[str, str], tuple[str, str]]:
    rps = pd.read_parquet(RPS_PATH)
    rps["trading_day"] = pd.to_datetime(rps["trading_day"])
    source_coverage = (str(rps["trading_day"].min().date()), str(rps["trading_day"].max().date()))
    rps["symbol"] = rps["symbol"].astype(str).str.zfill(6)
    rps["market"] = rps["market"].map(normalize_market)
    rps = rps[rps["symbol"].isin(codes)].copy()
    dates = sorted(pd.Timestamp(d) for d in rps["trading_day"].unique())
    daily: dict[pd.Timestamp, dict[tuple[str, str], tuple[float, float, float, float]]] = {}
    market_by_code: dict[str, str] = {}
    for day, grp in rps.groupby("trading_day", sort=True):
        values: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        for row in grp.itertuples(index=False):
            key = (row.market, row.symbol)
            values[key] = (float(row.rps_20), float(row.rps_50), float(row.rps_120), float(row.rps_250))
            market_by_code[row.symbol] = row.market
        daily[pd.Timestamp(day)] = values
    return dates, daily, market_by_code, source_coverage


def build_signals(price_data: dict[tuple[str, str], pd.DataFrame], rps_dates: list[pd.Timestamp], rps_daily: dict[pd.Timestamp, dict[tuple[str, str], tuple[float, float, float, float]]]) -> tuple[dict[tuple[str, str], pd.DataFrame], dict[str, Any]]:
    enriched = {key: price_conditions(frame) for key, frame in price_data.items()}
    funnel = defaultdict(int)
    actual_signals: list[dict[str, Any]] = []
    last_actual_index: dict[tuple[str, str], int] = {}
    prev: dict[tuple[str, str], float] = {}
    # Every RPS date is a trading-day index for the exact 60-trading-day dedup rule.
    for day_index, day in enumerate(rps_dates):
        today = rps_daily[day]
        for key, vals in today.items():
            total = sum(vals)
            old_total = prev.get(key)
            if not all(value >= 80 for value in vals):
                continue
            funnel["rps_all_four_ge_80"] += 1
            if not (total > 365 and old_total is not None and old_total <= 365):
                continue
            funnel["rps_strict_cross_above_365"] += 1
            prior_index = last_actual_index.get(key)
            if prior_index is not None and day_index - prior_index <= 60:
                funnel["blocked_by_prior_actual_signal_60_trading_days"] += 1
                continue
            frame = enriched.get(key)
            if frame is None or day not in frame.index:
                funnel["missing_price_bar"] += 1
                continue
            row = frame.loc[day]
            if not bool(row["eligible_history"]):
                funnel["fails_minimum_65_daily_history"] += 1
                continue
            funnel["has_minimum_65_daily_history"] += 1
            if not (row["close"] > row["ma20"] and row["ma20"] > row["ma60"]):
                funnel["fails_close_gt_ma20_gt_ma60"] += 1
                continue
            funnel["close_gt_ma20_gt_ma60"] += 1
            if not row["ma5"] > row["ma10"]:
                funnel["fails_ma5_gt_ma10"] += 1
                continue
            funnel["ma5_gt_ma10"] += 1
            if not abs(row["close"] - row["ma10"]) / row["ma10"] < 0.10:
                funnel["fails_distance_to_ma10_lt_10pct"] += 1
                continue
            funnel["distance_to_ma10_lt_10pct"] += 1
            if not bool(row["close_10d_high"]):
                funnel["fails_close_equals_including_current_10d_high"] += 1
                continue
            funnel["close_equals_including_current_10d_high"] += 1
            last_actual_index[key] = day_index
            actual_signals.append({"key": key, "date": day, "rps_total": total})
            funnel["actual_rps_first_signals"] += 1
        prev = {key: sum(vals) for key, vals in today.items()}

    # A signal waits for the first strictly subsequent golden cross, with a maximum
    # of 60 trading bars for that stock. Once an entry has been assigned for a stock,
    # later signals are ignored: a stock may be bought only once in the entire test.
    # Evaluate the delayed-GC contract independently for *every* actual signal.
    # Afterwards retain at most one (the chronologically first) candidate per stock,
    # which enforces the user-required no-reentry / one-buy-total policy.
    delayed_entries: list[dict[str, Any]] = []
    expired = 0
    for signal in actual_signals:
        key, signal_day = signal["key"], signal["date"]
        frame = enriched.get(key)
        later = frame.loc[frame.index > signal_day]
        wait = later.iloc[:60]
        gc = wait[wait["golden_cross"]]
        if gc.empty:
            expired += 1
            continue
        golden_day = gc.index[0]
        delayed_entries.append({**signal, "golden_cross_date": golden_day, "wait_trading_days": int(wait.index.get_loc(golden_day)) + 1})
    entries: list[dict[str, Any]] = []
    used_codes: set[tuple[str, str]] = set()
    for entry in delayed_entries:
        if entry["key"] not in used_codes:
            entries.append(entry)
            used_codes.add(entry["key"])
    funnel["delayed_golden_cross_entries_all_actual_signals"] = len(delayed_entries)
    funnel["expired_waits_no_subsequent_gc_within_60_trading_days"] = expired
    funnel["one_buy_total_unique_stock_entry_candidates"] = len(entries)
    funnel["delayed_gc_candidates_removed_by_one_buy_total_rule"] = len(delayed_entries) - len(entries)

    bars_by_code: dict[tuple[str, str], pd.DataFrame] = {}
    entry_by_key = {entry["key"]: entry for entry in entries}
    for key, frame in enriched.items():
        bars = frame[["open", "close", "dead_cross"]].copy()
        bars["buy_signal"] = False
        bars["replenish_signal"] = False
        bars["ndif"] = 0.0
        entry = entry_by_key.get(key)
        if entry is not None:
            bars.loc[entry["golden_cross_date"], "buy_signal"] = True
        bars_by_code[key] = bars
    metadata = {"funnel": dict(funnel), "actual_signals": actual_signals, "entries": entries}
    return bars_by_code, metadata


def annual_mtm(daily_equity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(daily_equity)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date")
    yearly = frame.resample("YE").last()
    previous = None
    final_year = frame.index[-1].year
    output = []
    for day, row in yearly.iterrows():
        equity = float(row.equity)
        output.append({"year": int(day.year), "equity": round(equity, 2), "cash": round(float(row.cash), 2), "market_value": round(float(row.market_value), 2), "return_pct": None if previous is None else round((equity / previous - 1) * 100, 2), "partial": day.year == final_year})
        previous = equity
    return output


def summarize(result: dict[str, Any], initial: float, candidate_entries: int) -> dict[str, Any]:
    s = result["summary"]
    first = pd.Timestamp(result["daily_equity"][0]["date"])
    last = pd.Timestamp(result["daily_equity"][-1]["date"])
    years = max((last - first).days / 365.25, 1 / 365.25)
    equity = float(s["equity"])
    cash, mv = float(s["cash"]), float(s["market_value"])
    return {"initial_capital": initial, "candidate_delayed_gc_entries": candidate_entries, "opened_positions": len(result["history"]) + len(result["positions"]), "closed_positions": len(result["history"]), "open_positions": len(result["positions"]), "orders_executed": int(result["executed"]), "orders_rejected_cash_or_price": int(result["rejected"]), "cash": round(cash, 2), "market_value": round(mv, 2), "equity": round(equity, 2), "equity_equals_cash_plus_market_value": abs(equity - cash - mv) <= 0.01, "total_return_pct": round((equity / initial - 1) * 100, 2), "annualized_return_pct": round(((equity / initial) ** (1 / years) - 1) * 100, 2), "annual_strict_mtm": annual_mtm(result["daily_equity"])}


def report_text(payload: dict[str, Any]) -> str:
    lines = ["RPS首次 · CSI300 · 极值金叉退出 · 严格MTM 回测（v1）", "=" * 64,
             f"RPS 数据覆盖：{payload['data']['rps_coverage_start']} 至 {payload['data']['rps_coverage_end']}；因此不能产生 2012 年信号。",
             f"价格数据期末：{payload['data']['price_last_day']}。", f"股票池：2026-07-28 当前 CSI300 成分股，价格/RPS 均加载 {payload['universe']['loaded_count']}/300；存在当前成分股幸存者偏差。",
             "入场条件：四项 RPS 各≥80；总分严格上穿365（当日>365、前交易日≤365）；实际信号前60交易日不重复；close>MA20>MA60；MA5>MA10；距MA10<10%；收盘=含当日10日最高；日线历史≥65。",
             "延迟执行：每个实际信号仅等待其后（不同日）首个 MACD(12,26,9) 金叉，最多60个交易日；金叉收盘确认，T+1下一开盘买入。每只股票最多买入一次，退出后不再入场。",
             "退出：复用 macd_backtest_engine.py：收盘PnL>20%后武装；随后MACD死叉或PnL<15%触发，T+1开盘全卖。补仓明确关闭（replenish_signal=false）。",
             "记账：严格现金约束、逐日收盘MTM；无手续费、印花税、滑点或其他交易成本。", "", "精确漏斗："]
    for k, v in payload["funnel"].items(): lines.append(f"  {k}: {v}")
    for result in payload["results"]:
        lines += ["", f"初始资金 {result['initial_capital']:,.0f}：期末权益 {result['equity']:,.2f}，总收益 {result['total_return_pct']:+.2f}%，年化 {result['annualized_return_pct']:+.2f}%；现金 {result['cash']:,.2f} + 持仓市值 {result['market_value']:,.2f}。", f"  延迟金叉候选 {result['candidate_delayed_gc_entries']}；实际开仓 {result['opened_positions']}，平仓 {result['closed_positions']}，未平仓 {result['open_positions']}；拒单 {result['orders_rejected_cash_or_price']}。", "  年度严格MTM："]
        for row in result["annual_strict_mtm"]:
            ret = "起始年" if row["return_pct"] is None else f"{row['return_pct']:+.2f}%"
            suffix = " (YTD)" if row["partial"] else ""
            lines.append(f"    {row['year']}{suffix}: 权益 {row['equity']:,.2f}，收益 {ret}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tdx-dir", default=DEFAULT_TDX)
    ap.add_argument("--output-dir", default="/mnt/c/Users/Sky.Lu/Desktop/output")
    ap.add_argument("--lot", type=float, default=50_000)
    ap.add_argument("--capitals", type=float, nargs="+", default=[3_000_000, 6_000_000, 10_000_000])
    args = ap.parse_args()
    codes = load_universe()
    price_data, load_stats = load_price_bars(codes, args.tdx_dir)
    rps_dates, rps_daily, rps_market_by_code, source_coverage = make_rps_maps(set(codes))
    # Retain only the price-market key that actually occurs in RPS history.
    remapped_prices = {}
    rps_start = rps_dates[0]
    for (_, code), frame in price_data.items():
        market = rps_market_by_code.get(code, "sh" if code.startswith("6") else "sz")
        # Preserve pre-2013 history for indicator construction in build_signals,
        # then restrict simulator bars below to the earliest RPS date. This makes
        # the portfolio period 2013+ while retaining valid MA/MACD warm-up data.
        remapped_prices[(market, code)] = frame
    bars, meta = build_signals(remapped_prices, rps_dates, rps_daily)
    bars = {key: frame.loc[frame.index >= rps_start].copy() for key, frame in bars.items()}
    last_price_day = max(str(frame.index[-1].date()) for frame in remapped_prices.values())
    candidate_entries = len(meta["entries"])
    results = [summarize(simulate_portfolio({code: frame for (_, code), frame in bars.items()}, initial_capital=capital, lot_cash=args.lot), capital, candidate_entries) for capital in args.capitals]
    payload = {"version": "v1", "strategy": "exact_rps_first_csi300_strict_mtm", "data": {"rps_path": str(RPS_PATH), "rps_coverage_start": source_coverage[0], "rps_coverage_end": source_coverage[1], "price_source": args.tdx_dir, "price_last_day": last_price_day}, "universe": {"source": str(CSI_PATH), "type": "current CSI300 constituents as of 2026-07-28", "requested_count": 300, "loaded_count": len(remapped_prices), "load_stats": load_stats, "survivorship_bias": True}, "contracts": {"rps_each_component_gte_80": True, "total_strict_cross_above_365": "today > 365 and prior RPS trading day <= 365", "actual_signal_dedup": "no actual signal within prior 60 RPS trading days", "minimum_daily_history": 65, "ten_day_high": "close equals maximum close including current day", "delayed_gc": "first strictly subsequent MACD(12,26,9) golden cross within 60 trading days", "entry_execution": "signal golden-cross close -> T+1 next available open", "one_purchase_per_stock_total": True, "exit": "close PnL >20% arms; then MACD dead cross or PnL <15%; T+1 open full exit", "replenishment": False, "transaction_costs_included": False, "strict_mtm": True}, "funnel": meta["funnel"], "lot_cash": args.lot, "results": results}
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    json_path, txt_path = out / f"{STEM}.json", out / f"{STEM}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(report_text(payload), encoding="utf-8")
    print(json.dumps({"script": str(Path(__file__).resolve()), "json": str(json_path), "text": str(txt_path), "funnel": payload["funnel"], "results": results}, ensure_ascii=False))

if __name__ == "__main__": main()
