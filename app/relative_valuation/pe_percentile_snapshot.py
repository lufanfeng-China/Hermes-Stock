"""Reusable raw-close daily PE-TTM percentile building blocks.

Warehouse rows are latest known revisions, not strict as-published historical records.
"""
from __future__ import annotations

from datetime import date, datetime
from collections import defaultdict
from math import isfinite
import re
from pathlib import Path

from app.relative_valuation.daily_pe_percentile import compute_daily_pe_percentile


def load_disclosures_bulk(warehouse_dir: Path, trading_day: str) -> dict[str, list[dict]]:
    """Scan relevant quarter files once, projecting only PE inputs for all symbols."""
    import pyarrow.parquet as pq

    end = date.fromisoformat(trading_day)
    cutoff_year = end.year - 5
    output: dict[str, list[dict]] = defaultdict(list)
    profit_field = "近一年归母净利润（万元）"
    for path in sorted(Path(warehouse_dir).glob("*.parquet")):
        if not re.fullmatch(r"20\d{2}(?:Q[1-3]|A)", path.stem):
            continue
        # The previous annual report may still be the latest disclosed at the
        # first day of the five-year window.
        if not cutoff_year - 1 <= int(path.stem[:4]) <= end.year:
            continue
        names = pq.ParquetFile(path).schema_arrow.names
        announce = "announce_date" if "announce_date" in names else "财报公告日期"
        if not all(field in names for field in ("code", announce, profit_field, "总股本")):
            continue
        table = pq.read_table(path, columns=["code", announce, profit_field, "总股本"])
        for row in table.to_pylist():
            symbol = str(row["code"] or "").zfill(6)
            if not re.fullmatch(r"\d{6}", symbol):
                continue
            raw = row[announce]
            digits = str(raw or "").strip().replace("-", "")
            if digits.endswith(".0"):
                digits = digits[:-2]
            if len(digits) == 6 and digits.isdigit():
                digits = "20" + digits
            try:
                announced = datetime.strptime(digits, "%Y%m%d").date()
            except ValueError:
                continue
            if announced >= end:
                continue
            try:
                profit = float(row[profit_field]) / 10000
                shares = float(row["总股本"])
            except (TypeError, ValueError):
                profit = shares = None
            output[symbol].append({
                "period": path.stem, "announce_date": announced.strftime("%Y%m%d"),
                "ttm_profit_yi": profit if profit is not None and isfinite(profit) else None,
                "total_shares": shares if shares is not None and isfinite(shares) else None,
            })
    return dict(output)


def compute_for_stock(
    bars: list[tuple[date, float]], reports: list[dict], trading_day: str,
) -> dict:
    """Rank today's raw daily-close PE against up to five years of disclosed daily PEs."""
    end = date.fromisoformat(trading_day)
    raw = compute_daily_pe_percentile(bars, reports)
    price_date = raw.get("price_date")
    status = raw["status"] if price_date == end.isoformat() else "stale_raw_price"
    if status == "ok" and raw["valid_days"] < 60:
        status = "insufficient_history"
    return {
        "pe_percentile_5y": raw.get("percentile") if status == "ok" else None,
        "pe_percentile_5y_basis": "five_years" if raw.get("basis") == "five_years" else "since_listing",
        "pe_percentile_5y_sample_count": raw.get("valid_days", 0),
        "pe_percentile_5y_window_start": raw.get("window_start"),
        "pe_percentile_5y_price_date": price_date,
        "pe_percentile_5y_latest_report_period": raw.get("latest_report_period"),
        "pe_percentile_5y_latest_announce_date": raw.get("latest_announce_date"),
        "pe_percentile_5y_current_pe": raw.get("current_pe") if status == "ok" else None,
        "pe_percentile_5y_status": status,
    }
