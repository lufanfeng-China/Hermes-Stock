"""Precomputed QFQ relative strength against the daily equal-weight A-share market."""
from __future__ import annotations
from typing import Any
import json
from functools import lru_cache
from pathlib import Path
import pandas as pd

PRICE_BASIS = "tdx_export_qfq"
BENCHMARK_METHOD = "all_a_daily_equal_weight_rps_universe"
WINDOWS = (5, 20, 50, 120, 250)
MRS_WEIGHTS = {20: .4, 50: .3, 120: .2, 250: .1}
MIN_ANTIFALL_DAYS = 5
FINAL = Path(__file__).resolve().parent.parent / "data" / "derived" / "datasets" / "final"
CURRENT_SNAPSHOT = FINAL / "market_relative_strength_current.json"

def mrs_label(score: float | None) -> str:
    if score is None: return "数据不足"
    if score >= 85: return "显著强势"
    if score >= 70: return "强势"
    if score >= 45: return "中性"
    if score >= 30: return "弱势"
    return "显著弱势"

def classify_relative_strength_state(score: float | None, excess_return_20_pp: float | None) -> str:
    if score is None or excess_return_20_pp is None: return "unavailable"
    if score >= 70 and excess_return_20_pp < 0: return "high_level_weakening"
    if score <= 45 and excess_return_20_pp > 0: return "low_level_strengthening"
    return "trend_aligned"

def relative_strength_state_label(value: str) -> str:
    return {"high_level_weakening": "高位转弱", "low_level_strengthening": "低位转强", "trend_aligned": "趋势一致", "unavailable": "数据不足"}.get(value, "数据不足")

def _compound_return(values: pd.Series, days: int) -> float | None:
    values = pd.to_numeric(values, errors="coerce").dropna().tail(days)
    return (float((1 + values).prod()) - 1) * 100 if len(values) == days else None

def _rank_percentiles(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    return {key: round((len(ordered) - rank + 1) / len(ordered) * 100, 2) for rank, (key, _) in enumerate(ordered, 1)}

def build_market_relative_strength(frame: pd.DataFrame, *, min_eligible_universe: int = 100) -> dict[str, Any]:
    """Build current snapshot; daily benchmark rebalances across RPS-eligible QFQ stocks."""
    required = {"date", "market", "symbol", "close"}
    missing = required.difference(frame.columns)
    if missing: raise ValueError(f"missing columns: {sorted(missing)}")
    bars = frame.loc[:, ["date", "market", "symbol", "close"]].copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="coerce")
    bars["market"] = bars["market"].astype(str).str.lower()
    bars["symbol"] = bars["symbol"].astype(str).str.zfill(6)
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars = bars.dropna(subset=["date", "close"])
    bars = bars[bars.close > 0].sort_values(["market", "symbol", "date"], kind="stable")
    if bars.empty: raise ValueError("no valid QFQ daily bars")
    bars["key"] = bars.market + ":" + bars.symbol
    grouped = bars.groupby("key", sort=False)["close"]
    bars["position"] = grouped.cumcount()
    bars["prior_250"] = grouped.shift(250)
    bars["daily_return"] = grouped.pct_change(fill_method=None)
    bars["eligible"] = (bars.position >= 250) & bars.prior_250.gt(0) & bars.daily_return.notna()
    eligible = bars[bars.eligible].copy()
    counts = eligible.groupby("date").key.nunique()
    eligible = eligible[eligible.date.map(counts).ge(min_eligible_universe)]
    if eligible.empty: raise ValueError("no dates meet the RPS eligible-universe requirement")
    benchmark_daily = eligible.groupby("date", sort=True).daily_return.mean().sort_index()
    as_of = benchmark_daily.index.max()
    current = eligible[eligible.date == as_of]
    benchmark_returns = {days: _compound_return(benchmark_daily.loc[:as_of], days) for days in WINDOWS}
    benchmark_daily_20 = benchmark_daily.loc[:as_of].tail(20)
    window_returns: dict[int, dict[str, float]] = {days: {} for days in MRS_WEIGHTS}
    stocks: dict[str, dict[str, Any]] = {}
    for item in current.itertuples(index=False):
        key = str(item.key)
        group = bars[bars.key == key].sort_values("date", kind="stable")
        position, close = int(group.position.iloc[-1]), float(group.close.iloc[-1])
        if position < 250: continue
        record: dict[str, Any] = {"market": item.market, "symbol": item.symbol, "as_of_date": str(as_of.date()), "price_basis": PRICE_BASIS, "benchmark_method": BENCHMARK_METHOD, "benchmark_universe_size": int(len(current))}
        daily_by_date = group.set_index("date").daily_return
        for days in WINDOWS:
            stock_return = (close / float(group.close.iloc[position-days]) - 1) * 100 if position >= days else None
            benchmark_return = benchmark_returns[days]
            excess = stock_return - benchmark_return if stock_return is not None and benchmark_return is not None else None
            record[f"return_{days}_pct"] = round(stock_return, 4) if stock_return is not None else None
            record[f"benchmark_return_{days}_pct"] = round(benchmark_return, 4) if benchmark_return is not None else None
            record[f"excess_return_{days}_pp"] = round(excess, 4) if excess is not None else None
            if days in window_returns and stock_return is not None: window_returns[days][key] = stock_return
        down_dates = benchmark_daily_20[benchmark_daily_20 < 0].index
        stock_down = daily_by_date.reindex(down_dates).dropna()
        excess_daily = stock_down - benchmark_daily.reindex(stock_down.index)
        down_market_detail = [
            {
                "date": str(date.date()),
                "market_return_pct": round(float(benchmark_daily.loc[date]) * 100, 4),
                "stock_return_pct": round(float(stock_down.loc[date]) * 100, 4),
                "excess_return_pp": round(float(excess_daily.loc[date]) * 100, 4),
            }
            for date in excess_daily.index
        ]
        down_days = len(excess_daily)
        record.update({"down_market_days_20": int(down_days), "down_market_outperform_days_20": int((excess_daily > 0).sum()), "down_market_win_rate_20": round(float((excess_daily > 0).mean() * 100), 2) if down_days else None, "down_market_total_excess_pp_20": round(float(excess_daily.sum()) * 100, 4) if down_days else None, "down_market_detail_20": down_market_detail, "anti_fall_status": "available" if down_days >= MIN_ANTIFALL_DAYS else "sample_insufficient"})
        stocks[key] = record
    ranks = {days: _rank_percentiles(values) for days, values in window_returns.items()}
    for key, record in stocks.items():
        parts = []
        for days, weight in MRS_WEIGHTS.items():
            value = ranks[days].get(key); record[f"rps_{days}"] = value
            if value is not None: parts.append((weight, value))
        record["mrs_score"] = round(sum(weight * value for weight, value in parts), 2) if len(parts) == len(MRS_WEIGHTS) else None
        record["mrs_label"] = mrs_label(record["mrs_score"])
        record["relative_strength_state"] = classify_relative_strength_state(record["mrs_score"], record.get("excess_return_20_pp"))
        record["relative_strength_state_label"] = relative_strength_state_label(record["relative_strength_state"])
    return {"schema_version": "market-relative-strength-v1", "as_of_date": str(as_of.date()), "price_basis": PRICE_BASIS, "benchmark_method": BENCHMARK_METHOD, "benchmark_universe_size": int(len(current)), "benchmark_daily_returns": {str(date.date()): round(float(value) * 100, 6) for date, value in benchmark_daily.tail(250).items()}, "stocks": stocks}


@lru_cache(maxsize=1)
def load_current_snapshot() -> dict[str, Any]:
    try:
        payload = json.loads(CURRENT_SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) and isinstance(payload.get("stocks"), dict) else {}


def stock_response(market: str, symbol: str) -> dict[str, Any]:
    payload = load_current_snapshot()
    key = f"{market.lower()}:{str(symbol).zfill(6)}"
    row = (payload.get("stocks") or {}).get(key)
    if not isinstance(row, dict):
        return {"ok": False, "error": {"code": "relative_strength_unavailable", "message": "相对大盘强弱快照尚未生成或该股票不在RPS成分池"}}
    return {"ok": True, "as_of_date": payload.get("as_of_date"), "benchmark_method": payload.get("benchmark_method"), "benchmark_universe_size": payload.get("benchmark_universe_size"), "relative_strength": row}
