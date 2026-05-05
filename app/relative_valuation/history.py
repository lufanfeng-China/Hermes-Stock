from __future__ import annotations

import importlib
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from .data_loader import (
    compute_market_cap_yi,
    compute_ttm_metric_from_rows,
    normalize_amount_to_yi,
    pick_free_float_shares,
    pick_total_shares,
)
from .industry_snapshot import build_industry_day_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINANCIAL_TS_DIR = PROJECT_ROOT / "data" / "derived" / "financial_ts" / "by_quarter"


def period_to_trading_day(period: str) -> str:
    text = str(period or "").strip()
    if len(text) < 5 or not text[:4].isdigit():
        return text
    year = text[:4]
    suffix = text[4:]
    mapping = {
        "Q1": "03-31",
        "Q2": "06-30",
        "Q3": "09-30",
        "A": "12-31",
    }
    return f"{year}-{mapping.get(suffix, '12-31')}"


def build_temperature_series_from_period_snapshots(period_snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in period_snapshots:
        weighted_pe = item.get("weighted_pe_ttm")
        if weighted_pe is None:
            continue
        if str(item.get("sample_status") or "") != "ok":
            continue
        rows.append(
            {
                "trading_day": str(item.get("trading_day") or ""),
                "weighted_pe_ttm": float(weighted_pe),
            }
        )
    rows.sort(key=lambda row: row["trading_day"])
    return rows


@lru_cache(maxsize=256)
def load_industry_temperature_history(industry_level_2_name: str) -> list[dict[str, object]]:
    search_index = _search_index_module()
    members = [
        row for row in search_index.load_industry_rows()
        if str(row.get("industry_level_2_name") or "").strip() == str(industry_level_2_name or "").strip()
    ]
    if not members:
        return []

    period_snapshots: list[dict[str, object]] = []
    for period in _historical_periods_since_2022():
        trading_day = period_to_trading_day(period)
        member_payloads = []
        for row in members:
            payload = _load_stock_inputs_for_period(
                str(row.get("market") or "").strip().lower(),
                str(row.get("symbol") or "").strip(),
                period,
                trading_day,
                row,
            )
            if payload:
                member_payloads.append(payload)
        if not member_payloads:
            continue
        first = member_payloads[0]
        snapshot = build_industry_day_snapshot(
            trading_day=trading_day,
            industry_level_1_name=str(first.get("industry_level_1_name") or ""),
            industry_level_2_code=str(first.get("industry_level_2_name") or industry_level_2_name),
            industry_level_2_name=str(first.get("industry_level_2_name") or industry_level_2_name),
            members=member_payloads,
            historical_weighted_pe_series=[],
        )
        period_snapshots.append(snapshot)
    return build_temperature_series_from_period_snapshots(period_snapshots)


@lru_cache(maxsize=1)
def _historical_periods_since_2022() -> tuple[str, ...]:
    periods = []
    for path in FINANCIAL_TS_DIR.glob("*.parquet"):
        period = path.stem
        if period[:4].isdigit() and int(period[:4]) >= 2022:
            periods.append(period)
    periods.sort(key=_period_sort_key)
    return tuple(periods)


def _period_sort_key(period: str) -> tuple[int, int]:
    year = int(period[:4]) if period[:4].isdigit() else 0
    suffix = period[4:]
    order = {"Q1": 1, "Q2": 2, "Q3": 3, "A": 4}
    return year, order.get(suffix, 99)


@lru_cache(maxsize=1)
def _search_index_module():
    return importlib.import_module("app.search.index")


@lru_cache(maxsize=4096)
def _load_daily_series(market: str, symbol: str) -> tuple[list[str], list[float]]:
    search_index = _search_index_module()
    try:
        from mootdx.reader import Reader
    except Exception:
        return [], []
    try:
        reader = Reader.factory(market="std", tdxdir=search_index._TDX_DIR)
        daily = reader.daily(symbol=symbol)
        if daily is None or daily.empty:
            return [], []
        daily = daily.sort_index()
        dates = [idx.strftime("%Y-%m-%d") for idx in daily.index]
        closes = [float(value) for value in daily["close"].astype(float).tolist()]
        return dates, closes
    except Exception:
        return [], []


def _load_close_and_listed_days_on_or_before(market: str, symbol: str, trading_day: str) -> tuple[float | None, int | None]:
    dates, closes = _load_daily_series(market, symbol)
    if not dates:
        return None, None
    idx = bisect_right(dates, trading_day) - 1
    if idx < 0:
        return None, None
    return closes[idx], idx + 1


def _load_stock_inputs_for_period(
    market: str,
    symbol: str,
    period: str,
    trading_day: str,
    industry_row: dict[str, object],
) -> dict[str, object] | None:
    if market not in {"sh", "sz", "bj"} or len(symbol) != 6:
        return None
    search_index = _search_index_module()
    current_row = search_index._load_financial_quarter_row(period, symbol)
    if current_row is None:
        return None
    year = int(period[:4]) if period[:4].isdigit() else None
    prev_annual_row = search_index._load_financial_quarter_row(f"{year - 1}A", symbol) if year else None
    prev_same_row = search_index._load_financial_quarter_row(f"{year - 1}{period[4:]}", symbol) if year else None
    previous_quarter_rows = [
        search_index._load_financial_quarter_row(previous_period, symbol)
        for previous_period in _latest_three_previous_periods(period)
    ]

    current_price, listed_days = _load_close_and_listed_days_on_or_before(market, symbol, trading_day)
    free_float_shares_raw = pick_free_float_shares(current_row)
    total_shares_raw = pick_total_shares(current_row)
    free_float_market_cap = None
    total_market_cap = None
    if current_price is not None and free_float_shares_raw is not None:
        free_float_market_cap = compute_market_cap_yi(current_price, free_float_shares_raw)
    if current_price is not None and total_shares_raw is not None:
        total_market_cap = compute_market_cap_yi(current_price, total_shares_raw)

    ttm_net_profit = normalize_amount_to_yi(compute_ttm_metric_from_rows(
        period=period,
        field_name="归属于母公司所有者的净利润",
        current_row=current_row,
        previous_quarter_rows=previous_quarter_rows,
        prev_annual_row=prev_annual_row,
        prev_same_row=prev_same_row,
    ))
    ttm_revenue = normalize_amount_to_yi(compute_ttm_metric_from_rows(
        period=period,
        field_name="营业收入",
        current_row=current_row,
        previous_quarter_rows=previous_quarter_rows,
        prev_annual_row=prev_annual_row,
        prev_same_row=prev_same_row,
    ))
    book_value_per_share = search_index._pick(current_row.get("每股净资产"))
    if book_value_per_share is None:
        book_value_per_share = search_index._pick(current_row.get("每股净资产(调整后)"))

    return {
        "market": market,
        "symbol": symbol,
        "stock_name": str(industry_row.get("stock_name") or "").strip(),
        "industry_level_1_name": str(industry_row.get("industry_level_1_name") or "").strip(),
        "industry_level_2_name": str(industry_row.get("industry_level_2_name") or "").strip(),
        "listed_days": listed_days,
        "current_price": current_price,
        "total_market_cap": total_market_cap,
        "free_float_market_cap": free_float_market_cap,
        "ttm_net_profit": ttm_net_profit,
        "ttm_revenue": ttm_revenue,
        "book_value_per_share": book_value_per_share,
        "is_suspended": False,
    }


def _latest_three_previous_periods(period: str) -> tuple[str, ...]:
    text = str(period or "").strip()
    if len(text) < 5 or not text[:4].isdigit():
        return tuple()
    year = int(text[:4])
    suffix = text[4:]
    if suffix == "Q1":
        return (f"{year - 1}A", f"{year - 1}Q3", f"{year - 1}Q2")
    if suffix == "Q2":
        return (f"{year}Q1", f"{year - 1}A", f"{year - 1}Q3")
    if suffix == "Q3":
        return (f"{year}Q2", f"{year}Q1", f"{year - 1}A")
    if suffix == "A":
        return (f"{year}Q3", f"{year}Q2", f"{year}Q1")
    return tuple()
