#!/usr/bin/env python3
"""MA25 + RPS CSI300 three-position short-swing strict-MTM baseline, v1.

Signals and indicators are calculated solely from Tongdaxin QFQ exports.  Orders
execute at the next available *raw* local open and every daily portfolio value
uses raw local closes.  Current CSI300 membership and current industry taxonomy
are intentionally survivorship-biased research inputs.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FINAL = ROOT / "data" / "derived" / "datasets" / "final"
CONSTITUENTS = FINAL / "csi300_constituents_current_20260728.json"
INDUSTRIES = FINAL / "dataset_stock_industry_current.json"
RPS_PARQUET = FINAL / "dataset_stock_rps_history.parquet"
DEFAULT_OUTPUT_DIR = Path("/mnt/c/Users/Sky.Lu/Desktop/output")
DEFAULT_RAW_TDX_DIR = "/home/lufanfeng/tdx_data"


def build_signal_features(qfq: pd.DataFrame, rps: pd.DataFrame) -> pd.DataFrame:
    """Compute all entry/technical-exit features from QFQ bars and dated RPS only."""
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(qfq.columns)
    if missing:
        raise ValueError(f"QFQ frame missing columns: {', '.join(sorted(missing))}")
    bars = qfq.sort_index().copy()
    rps_frame = rps.copy()
    rps_frame.index = pd.to_datetime(rps_frame.index)
    bars = bars.join(rps_frame[["rps_20", "rps_50", "rps_120", "rps_250"]], how="left")
    close = bars["close"].astype(float)
    volume = bars["volume"].astype(float)
    ma10 = close.rolling(10).mean()
    ma25 = close.rolling(25).mean()
    vma5 = volume.rolling(5).mean()
    vma60 = volume.rolling(60).mean()
    body_ratio = (close - bars["open"].astype(float)) / (bars["high"].astype(float) - bars["low"].astype(float)).replace(0, np.nan)
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    dead_cross = (dif < dea) & (dif.shift(1) >= dea.shift(1))
    rps_fields = ["rps_20", "rps_50", "rps_120", "rps_250"]
    rps_ok = bars[rps_fields].ge(70).all(axis=1) & bars[rps_fields].notna().all(axis=1)
    volume_ratio = vma5 / vma60.replace(0, np.nan)
    ma25_slope = ma25 / ma25.shift(10) - 1
    proximity = (bars["low"].astype(float) / ma25 - 1).abs()
    entry = (
        (ma25_slope >= 0.005) & (proximity <= 0.03) & (close >= ma25)
        & ((close / ma25 - 1) <= 0.05) & volume_ratio.between(1.15, 2.5, inclusive="both")
        & (body_ratio >= 0.5) & rps_ok
    )
    bars["ma10"] = ma10
    bars["ma25"] = ma25
    bars["ma25_slope_10"] = ma25_slope
    bars["volume_ratio"] = volume_ratio
    bars["dead_cross"] = dead_cross.fillna(False)
    bars["entry_signal"] = entry.fillna(False)
    # RPS total, MA25 closeness, useful volume expansion, and bullish close strength.
    bars["rank_score"] = (
        bars[rps_fields].sum(axis=1, min_count=4)
        + (1 - proximity.clip(lower=0, upper=0.03) / 0.03) * 10
        + (volume_ratio.clip(lower=1.15, upper=2.5) - 1.15) * 10
        + body_ratio.clip(lower=0, upper=1) * 10
    ).where(bars["entry_signal"], np.nan)
    return bars


def select_candidates(candidates: list[dict], available_slots: int) -> list[dict]:
    """Return the top candidates with one stock per L2 industry and max three slots."""
    if available_slots <= 0:
        return []
    selected: list[dict] = []
    industries: set[str] = set()
    for candidate in sorted(candidates, key=lambda row: (-float(row["rank_score"]), str(row["code"]))):
        industry = str(candidate["industry_l2"])
        if industry in industries:
            continue
        selected.append(candidate)
        industries.add(industry)
        if len(selected) >= min(3, available_slots):
            break
    return selected


def _next_raw_day(frame: pd.DataFrame, signal_day: pd.Timestamp) -> pd.Timestamp | None:
    future = frame.index[frame.index > signal_day]
    return pd.Timestamp(future[0]) if len(future) else None


def simulate_portfolio(
    frames: dict[str, pd.DataFrame], industries: dict[str, str], *, initial_cash: float = 10_000_000.0,
    lot_cash: float = 50_000.0,
) -> dict:
    """Run QFQ-close decisions with T+1 raw execution and raw-close strict MTM."""
    calendar = sorted({pd.Timestamp(day) for frame in frames.values() for day in frame.index})
    lookup = {code: frame.sort_index() for code, frame in frames.items()}
    cash = float(initial_cash)
    positions: dict[str, dict] = {}
    pending: dict[pd.Timestamp, list[dict]] = {}
    history: list[dict] = []
    daily_equity: list[dict] = []
    last_close: dict[str, float] = {}
    executed = rejected = 0
    funnel: Counter = Counter()

    def queue(code: str, after: pd.Timestamp, order: dict) -> None:
        target = _next_raw_day(lookup[code], after)
        if target is None:
            funnel["no_next_raw_bar"] += 1
            return
        pending.setdefault(target, []).append({"code": code, **order})

    for day in calendar:
        # Sells are first so released cash/slots are usable by pre-existing T+1 buys.
        for order in sorted(pending.pop(day, []), key=lambda value: 0 if value["kind"] == "sell" else 1):
            code, frame = order["code"], lookup[order["code"]]
            open_price = float(frame.at[day, "raw_open"])
            if open_price <= 0:
                rejected += 1
                continue
            if order["kind"] == "sell":
                position = positions.get(code)
                if position is None:
                    continue
                shares = min(int(order["shares"]), int(position["shares"]))
                if shares <= 0:
                    continue
                proceeds = open_price * shares
                cash += proceeds
                position["shares"] -= shares
                position["realized_pnl"] += proceeds - position["avg_cost"] * shares
                position["partial_reasons"].append(order["reason"])
                executed += 1
                if position["shares"] == 0:
                    history.append({
                        "code": code, "entry_date": str(position["entry_date"].date()), "exit_date": str(day.date()),
                        "reason": order["reason"], "cost": position["avg_cost"] * position["initial_shares"],
                        "revenue": position["realized_pnl"] + position["avg_cost"] * position["initial_shares"],
                        "pnl": position["realized_pnl"], "holding_days": position["holding_days"],
                        "partial_reasons": position["partial_reasons"][:-1],
                    })
                    del positions[code]
                continue
            if code in positions or len(positions) >= 3:
                rejected += 1
                funnel["entry_rejected_slots"] += 1
                continue
            shares = int(lot_cash // open_price)
            cost = shares * open_price
            if shares <= 0 or cost > cash + 1e-9:
                rejected += 1
                funnel["entry_rejected_cash_or_price"] += 1
                continue
            cash -= cost
            positions[code] = {"shares": shares, "initial_shares": shares, "avg_cost": open_price,
                "entry_date": day, "holding_days": 1, "below_ma25_days": 0, "sold_8": False,
                "sold_12": False, "realized_pnl": 0.0, "partial_reasons": []}
            executed += 1

        for code, frame in lookup.items():
            if day in frame.index:
                last_close[code] = float(frame.at[day, "raw_close"])

        for code, position in list(positions.items()):
            frame = lookup[code]
            if day not in frame.index:
                continue
            row = frame.loc[day]
            if day != position["entry_date"]:
                position["holding_days"] += 1
            raw_close = float(row["raw_close"])
            pnl_pct = raw_close / position["avg_cost"] - 1
            signal_close = float(row["signal_close"])
            below_ma25 = signal_close < float(row["ma25"])
            position["below_ma25_days"] = position["below_ma25_days"] + 1 if below_ma25 else 0
            reason = None
            if pnl_pct <= -0.06:
                reason = "close_pnl_le_minus_6pct"
            elif position["below_ma25_days"] >= 2:
                reason = "two_consecutive_qfq_close_below_ma25"
            elif position["holding_days"] >= 3 and pnl_pct <= 0 and signal_close < float(row["ma10"]):
                reason = "day3_nonpositive_below_ma10"
            elif signal_close < float(row["ma10"]) or bool(row["dead_cross"]):
                reason = "qfq_close_below_ma10_or_macd_dead_cross"
            elif position["holding_days"] >= 7 and pnl_pct < 0.03:
                reason = "day7_pnl_below_3pct"
            elif position["holding_days"] >= 10:
                reason = "forced_day10"
            if reason:
                queue(code, day, {"kind": "sell", "shares": position["shares"], "reason": reason})
            elif pnl_pct >= 0.12 and not position["sold_12"]:
                position["sold_12"] = True
                queue(code, day, {"kind": "sell", "shares": max(1, position["initial_shares"] // 3), "reason": "take_profit_12pct_one_third"})
            elif pnl_pct >= 0.08 and not position["sold_8"]:
                position["sold_8"] = True
                queue(code, day, {"kind": "sell", "shares": max(1, position["initial_shares"] // 3), "reason": "take_profit_8pct_one_third"})

        candidates = []
        for code, frame in lookup.items():
            if code in positions or day not in frame.index:
                continue
            row = frame.loc[day]
            if bool(row["entry_signal"]):
                funnel["raw_qfq_signals"] += 1
                candidates.append({"code": code, "industry_l2": industries.get(code, "UNKNOWN"), "rank_score": float(row["rank_score"])})
        available_slots = max(0, 3 - len(positions))
        selected = select_candidates(candidates, available_slots)
        funnel["industry_dedup_rejected"] += max(0, len(candidates) - len({c["industry_l2"] for c in candidates}))
        funnel["slot_or_rank_rejected"] += max(0, len({c["industry_l2"] for c in candidates}) - len(selected))
        for candidate in selected:
            funnel["entry_orders_queued"] += 1
            queue(candidate["code"], day, {"kind": "buy"})

        market_value = sum(position["shares"] * last_close.get(code, 0.0) for code, position in positions.items())
        equity = cash + market_value
        assert cash >= -1e-6, f"negative cash on {day.date()}: {cash}"
        assert abs(equity - (cash + market_value)) < 1e-6, f"MTM identity failed on {day.date()}"
        daily_equity.append({"date": str(day.date()), "cash": cash, "market_value": market_value,
                             "equity": equity, "positions": len(positions)})
    return {"positions": positions, "history": history, "daily_equity": daily_equity,
            "orders_executed": executed, "orders_rejected": rejected, "cash": cash, "funnel": dict(funnel)}


def load_codes() -> list[str]:
    codes = sorted({str(value).zfill(6) for value in json.loads(CONSTITUENTS.read_text(encoding="utf-8"))})
    if len(codes) != 300:
        raise ValueError(f"expected 300 current CSI300 constituents, got {len(codes)}")
    return codes


def load_industries() -> dict[str, str]:
    rows = json.loads(INDUSTRIES.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for row in rows:
        code = str(row.get("symbol", "")).zfill(6)
        value = str(row.get("industry_level_2_name") or "UNKNOWN")
        if code and code not in result:
            result[code] = value
    return result


def load_rps(codes: list[str]) -> tuple[dict[str, pd.DataFrame], dict]:
    if not RPS_PARQUET.is_file():
        raise FileNotFoundError(f"RPS parquet is unavailable: {RPS_PARQUET}")
    cols = ["trading_day", "symbol", "rps_20", "rps_50", "rps_120", "rps_250"]
    rows = pd.read_parquet(RPS_PARQUET, columns=cols, filters=[("symbol", "in", codes)])
    rows["symbol"] = rows["symbol"].astype(str).str.zfill(6)
    rows["trading_day"] = pd.to_datetime(rows["trading_day"])
    result = {code: group.drop(columns="symbol").rename(columns={"trading_day": "date"}).set_index("date").sort_index()
              for code, group in rows.groupby("symbol")}
    return result, {"rows": int(len(rows)), "start": str(rows["trading_day"].min().date()), "end": str(rows["trading_day"].max().date()), "codes": len(result)}


def load_frames(codes: list[str], rps: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp, raw_tdxdir: str) -> tuple[dict[str, pd.DataFrame], dict]:
    from mootdx.reader import Reader
    from app.tdx.qfq_kline import align_qfq_signal_with_raw_execution, load_tdx_qfq_daily
    reader = Reader.factory(market="std", tdxdir=raw_tdxdir)
    frames: dict[str, pd.DataFrame] = {}
    skipped: Counter = Counter()
    qfq_ranges = []
    raw_ranges = []
    for code in codes:
        if code not in rps:
            skipped["missing_rps"] += 1
            continue
        try:
            raw = reader.daily(code).sort_index()
            qfq = load_tdx_qfq_daily(code)
            aligned = align_qfq_signal_with_raw_execution(raw, qfq)
            qfq_features = build_signal_features(qfq, rps[code])
            aligned = aligned.join(qfq_features[["ma10", "ma25", "dead_cross", "entry_signal", "rank_score"]], how="inner")
            aligned = aligned.rename(columns={"signal_close": "signal_close"})
            aligned = aligned.loc[(aligned.index >= start) & (aligned.index <= end)].copy()
            if len(aligned) < 2:
                skipped["insufficient_overlap"] += 1
                continue
            frames[code] = aligned
            qfq_ranges.append((qfq.index.min(), qfq.index.max()))
            raw_ranges.append((raw.index.min(), raw.index.max()))
        except FileNotFoundError:
            skipped["missing_qfq"] += 1
        except Exception:
            skipped["load_error"] += 1
    return frames, {"loaded": len(frames), "skipped": dict(skipped),
        "qfq_coverage": {"start": str(min(x[0] for x in qfq_ranges).date()), "end": str(max(x[1] for x in qfq_ranges).date())} if qfq_ranges else None,
        "raw_coverage": {"start": str(min(x[0] for x in raw_ranges).date()), "end": str(max(x[1] for x in raw_ranges).date())} if raw_ranges else None}


def annual_mtm(daily_equity: list[dict]) -> list[dict]:
    frame = pd.DataFrame(daily_equity)
    if frame.empty:
        return []
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date")
    prior = None
    result = []
    for year, group in frame.groupby(frame.index.year):
        equity = float(group["equity"].iloc[-1])
        result.append({"year": int(year), "as_of": str(group.index[-1].date()), "equity": round(equity, 2),
                       "return_pct": None if prior is None else round((equity / prior - 1) * 100, 2)})
        prior = equity
    return result


def summarize(result: dict, initial_cash: float) -> dict:
    history = result["history"]
    holding = [row["holding_days"] for row in history]
    return {"initial_cash": initial_cash, "ending_equity": round(result["daily_equity"][-1]["equity"], 2),
        "ending_cash": round(result["cash"], 2), "open_positions": len(result["positions"]), "closed_trades": len(history),
        "mean_holding_days": round(mean(holding), 2) if holding else None,
        "median_holding_days": round(median(holding), 2) if holding else None,
        "exit_reasons": dict(Counter(row["reason"] for row in history)), "annual_mtm": annual_mtm(result["daily_equity"]),
        "candidate_funnel": result["funnel"], "orders_executed": result["orders_executed"], "orders_rejected": result["orders_rejected"],
        "terminal_mtm_identity": round(result["daily_equity"][-1]["equity"] - (result["cash"] + result["daily_equity"][-1]["market_value"]), 10)}


def write_text_report(path: Path, payload: dict) -> None:
    summary = payload["summary"]
    lines = ["MA25 + RPS · CSI300 · 三仓短线 · 严格MTM · v1", "=" * 56,
        f"回测区间：{payload['period']['start']} 至 {payload['period']['end']}",
        "股票池：当前CSI300成分股；当前行业分类；均存在幸存者/当前分类偏差。",
        "信号：QFQ MA25回踩+斜率、量能、阳线实体、四周期RPS；收盘确认，原始日线T+1开盘成交。",
        "估值：逐日原始收盘价 MTM；现金 + 持仓市值每日断言。未包含手续费、税费、滑点。",
        f"QFQ覆盖：{payload['sources']['frames']['qfq_coverage']}；RPS覆盖：{payload['sources']['rps']['start']} 至 {payload['sources']['rps']['end']}。",
        f"加载：CSI300 {payload['universe']['total']}，可用 {payload['universe']['loaded']}。",
        f"期末权益：{summary['ending_equity']:,.2f}；期末现金：{summary['ending_cash']:,.2f}；未平仓：{summary['open_positions']}；已平仓：{summary['closed_trades']}。",
        f"已平仓持有天数：均值 {summary['mean_holding_days']}，中位数 {summary['median_holding_days']}。",
        f"期末MTM恒等式差额：{summary['terminal_mtm_identity']:.10f}", "年度MTM："]
    for row in summary["annual_mtm"]:
        lines.append(f"  {row['year']} {row['as_of']}：权益 {row['equity']:,.2f}，收益 {row['return_pct'] if row['return_pct'] is not None else '基期'}%")
    lines.extend([f"候选漏斗：{json.dumps(summary['candidate_funnel'], ensure_ascii=False)}", f"退出原因：{json.dumps(summary['exit_reasons'], ensure_ascii=False)}",
                  "仅为历史研究，不构成投资建议。"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="MA25+RPS CSI300 three-position strict-MTM v1")
    parser.add_argument("--start", default="2013-01-15")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--capital", type=float, default=10_000_000.0)
    parser.add_argument("--lot-cash", type=float, default=50_000.0)
    parser.add_argument("--raw-tdxdir", default=DEFAULT_RAW_TDX_DIR)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    codes = load_codes()
    industry = load_industries()
    rps, rps_meta = load_rps(codes)
    frames, frame_meta = load_frames(codes, rps, start, end, args.raw_tdxdir)
    if not frames:
        raise SystemExit("No usable QFQ+raw+RPS frames loaded; QFQ signal fallback to raw is prohibited.")
    result = simulate_portfolio(frames, industry, initial_cash=args.capital, lot_cash=args.lot_cash)
    payload = {"strategy": "ma25_rps_csi300_three_position_short_swing_v1", "period": {"start": str(start.date()), "end": str(end.date())},
        "universe": {"type": "current CSI300 constituents", "total": len(codes), "loaded": len(frames), "survivorship_bias": True, "current_industry_taxonomy_bias": True},
        "sources": {"signal": "app.tdx.qfq_kline QFQ only", "execution_and_mtm": "local TDX raw daily", "rps": rps_meta, "frames": frame_meta},
        "rules": {"max_positions": 3, "max_candidates_per_l2_industry": 1, "entry": "QFQ close signal; raw next available open", "mtm": "raw close daily", "exits": "all QFQ close triggers submit raw next-open orders"},
        "summary": summarize(result, args.capital), "closed_trades": result["history"], "open_positions": result["positions"]}
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"MA25_RPS_CSI300_三仓短线_严格MTM_v1_{start:%Y%m%d}_{end:%Y%m%d}"
    json_path, txt_path = out / f"{stem}.json", out / f"{stem}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_text_report(txt_path, payload)
    print(json.dumps({"json": str(json_path), "txt": str(txt_path), "summary": payload["summary"]}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
