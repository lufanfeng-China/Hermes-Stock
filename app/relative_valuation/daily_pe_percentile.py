"""Point-in-time daily PE-TTM rank, using disclosed earnings and raw daily closes.

Historical warehouse rows are latest known revisions, not an append-only as-published
ledger. Announcement-day data becomes effective from the next trading day (strict <).
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime
from functools import lru_cache
from math import isfinite
from pathlib import Path
import re


def _positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _announcement_day(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _five_year_cutoff(day: date) -> date:
    try:
        return day.replace(year=day.year - 5)
    except ValueError:  # February 29 -> February 28
        return day.replace(year=day.year - 5, day=28)


@lru_cache(maxsize=128)
def _read_disclosure_files(symbol: str, signatures: tuple[tuple[str, int, int], ...]) -> tuple[dict[str, object], ...]:
    import pyarrow.parquet as pq

    out = []
    for filename, _mtime, _size in signatures:
        path = Path(filename)
        schema = pq.ParquetFile(path).schema_arrow.names
        if "近一年归母净利润（万元）" not in schema or "总股本" not in schema:
            continue
        announcement_field = "announce_date" if "announce_date" in schema else "财报公告日期"
        if announcement_field not in schema:
            continue
        optional_fields = [
            field for field in ("归属于母公司所有者的净利润", "实收资本（或股本）")
            if field in schema
        ]
        rows = pq.read_table(
            path,
            columns=[announcement_field, "近一年归母净利润（万元）", "总股本", *optional_fields],
            filters=[("code", "==", symbol)],
            use_threads=False,
        ).to_pylist()
        for row in rows:
            raw_announcement = _number(row.get(announcement_field))
            if raw_announcement is not None and 100000 <= raw_announcement < 1000000:
                raw_announcement += 20000000  # 6-digit YYMMDD in older TDX files
            precomputed_wan = _number(row.get("近一年归母净利润（万元）"))
            total_shares = _positive(row.get("总股本"))
            if total_shares is None:
                total_shares = _positive(row.get("实收资本（或股本）"))
            out.append({
                "period": path.stem,
                "announce_date": str(int(raw_announcement)) if raw_announcement is not None else None,
                "ttm_profit_yi": precomputed_wan / 10000 if precomputed_wan not in (None, 0) else None,
                "ttm_profit_source": "precomputed_tdx" if precomputed_wan not in (None, 0) else None,
                "total_shares": total_shares,
                "financial_row": row,
            })
    by_period = {str(row["period"]): row for row in out}
    from app.relative_valuation.data_loader import normalize_amount_to_yi, resolve_ttm_metric_from_rows

    for disclosure in out:
        if disclosure["ttm_profit_yi"] is not None:
            continue
        period = str(disclosure["period"])
        if len(period) < 5 or not period[:4].isdigit():
            continue
        year = int(period[:4])
        suffix = period[4:]
        calculated, source = resolve_ttm_metric_from_rows(
            period=period,
            field_name="归属于母公司所有者的净利润",
            current_row=disclosure.get("financial_row"),
            prev_annual_row=by_period.get(f"{year - 1}A", {}).get("financial_row"),
            prev_same_row=by_period.get(f"{year - 1}{suffix}", {}).get("financial_row"),
            prev_q3_row=by_period.get(f"{year - 1}Q3", {}).get("financial_row"),
            current_q3_row=by_period.get(f"{year}Q3", {}).get("financial_row"),
        )
        if calculated is not None:
            disclosure["ttm_profit_yi"] = normalize_amount_to_yi(calculated)
            disclosure["ttm_profit_source"] = source
    for disclosure in out:
        disclosure.pop("financial_row", None)
    return tuple(out)


def read_stock_disclosures(
    warehouse_dir: Path, symbol: str, first_year: int, through_year: int,
) -> list[dict[str, object]]:
    """Filtered per-stock parquet reads; cache invalidates when a financial file changes."""
    signatures = []
    for path in Path(warehouse_dir).glob("*.parquet"):
        if not re.fullmatch(r"20\d{2}(?:Q[1-3]|A)", path.stem):
            continue
        if not first_year <= int(path.stem[:4]) <= through_year:
            continue
        stat = path.stat()
        signatures.append((str(path), stat.st_mtime_ns, stat.st_size))
    return list(_read_disclosure_files(symbol, tuple(sorted(signatures))))


def load_stock_daily_pe_percentile(
    market: str, symbol: str, *, current_price: float | None = None,
    warehouse_dir: Path | None = None, tdx_dir: str = "/mnt/c/new_tdx64",
    include_history: bool = False,
) -> dict[str, object]:
    """Build one stock's five-year daily history from raw TDX bars and report warehouse."""
    if market not in {"sh", "sz", "bj"} or not re.fullmatch(r"\d{6}", symbol):
        raise ValueError("invalid stock identifier")
    from mootdx.reader import Reader

    bars_frame = Reader.factory(market="std", tdxdir=tdx_dir).daily(symbol=symbol)
    if bars_frame is None or bars_frame.empty:
        return compute_daily_pe_percentile([], [])
    bars = [(index.date(), float(row["close"])) for index, row in bars_frame.iterrows()]
    end = bars[-1][0]
    first_year = _five_year_cutoff(end).year - 1
    warehouse_dir = warehouse_dir or Path(__file__).resolve().parents[2] / "data/derived/financial_ts/by_quarter"
    reports = read_stock_disclosures(warehouse_dir, symbol, first_year, end.year)
    result = compute_daily_pe_percentile(bars, reports, current_price=current_price,
                                         include_history=include_history)
    result["market"] = market
    result["symbol"] = symbol
    result["raw_close"] = bars[-1][1]
    result["price_source"] = "current_quote_time_unverified" if (
        current_price is not None and _positive(current_price) is not None
        and abs(current_price - bars[-1][1]) > 0.00001
    ) else "raw_daily_close"
    result["historical_shares_source"] = "latest_disclosed_report_shares_proxy"
    result["historical_reports_source"] = "current_warehouse_with_announcement_dates"
    return result


def compute_daily_pe_percentile(
    bars: list[tuple[date, float]],
    reports: list[dict[str, object]],
    *,
    current_price: float | None = None,
    include_history: bool = False,
) -> dict[str, object]:
    """Rank current cap/TTM parent profit against at most five calendar years of daily PEs.

    ``total_shares`` is the shares in each latest-disclosed financial record, not a
    reconstructed exchange-event share ledger. Invalid latest records are never
    replaced by an older positive report. Current_price can be a newer quote; its
    timestamp cannot be asserted from this calculation, so price_date stays the
    last observed raw daily-bar date and the caller must label quote time separately.
    """
    ordered_bars = sorted((day, _number(price)) for day, price in bars if isinstance(day, date))
    if not ordered_bars:
        return {"status": "missing_price_history", "current_pe": None, "percentile": None, "valid_days": 0}
    end_day = ordered_bars[-1][0]
    cutoff = _five_year_cutoff(end_day)
    window = [(day, price) for day, price in ordered_bars if day >= cutoff]
    eligible_reports = []
    for row in reports:
        announced = _announcement_day(row.get("announce_date"))
        period = str(row.get("period") or "")
        if announced and re.fullmatch(r"20\d{2}(?:Q[1-3]|A)", period) and announced < end_day:
            eligible_reports.append((announced, period, row))
    eligible_reports.sort(key=lambda x: (x[0], x[1]))
    days = [entry[0] for entry in eligible_reports]
    # Newer report periods win over a late revision to an older quarter.
    newest_by_day = []
    newest = None
    for entry in eligible_reports:
        if newest is None or (int(entry[1][:4]), {"Q1": 1, "Q2": 2, "Q3": 3, "A": 4}[entry[1][4:]]) >= (
            int(newest[1][:4]), {"Q1": 1, "Q2": 2, "Q3": 3, "A": 4}[newest[1][4:]]
        ):
            newest = entry
        newest_by_day.append(newest)
    values = []
    dated_values = []
    first_valid = None
    last_valid = None
    for day, price in window:
        ix = bisect_left(days, day) - 1
        # Even an announcement on the trading day itself is conservatively
        # unavailable before that day's close.
        if ix < 0 or _positive(price) is None:
            continue
        row = newest_by_day[ix][2]
        profit = _positive(row.get("ttm_profit_yi"))
        shares = _positive(row.get("total_shares"))
        if profit is None or shares is None:
            continue
        daily_pe = price * shares / 1e8 / profit
        values.append(daily_pe)
        if include_history:
            dated_values.append((day, daily_pe))
        first_valid = first_valid or day
        last_valid = day
    latest_ix = bisect_left(days, end_day) - 1
    latest = newest_by_day[latest_ix] if latest_ix >= 0 else None
    report = latest[2] if latest else {}
    profit = _positive(report.get("ttm_profit_yi"))
    shares = _positive(report.get("total_shares"))
    price = _positive(current_price if current_price is not None else ordered_bars[-1][1])
    status = "ok"
    if latest is None:
        status = "missing_announced_report"
    elif profit is None:
        status = "nonpositive_ttm_profit"
    elif shares is None:
        status = "missing_shares"
    elif price is None:
        status = "missing_current_price"
    elif not values:
        status = "no_valid_history"
    pe = price * shares / 1e8 / profit if status == "ok" else None
    result = {
        "status": status,
        "current_pe": round(pe, 6) if pe is not None else None,
        "percentile": round(100 * sum(value <= pe for value in values) / len(values), 2) if pe is not None else None,
        "valid_days": len(values),
        "basis": "five_years" if ordered_bars[0][0] < cutoff else "available_history",
        "window_start": cutoff.isoformat() if ordered_bars[0][0] < cutoff else ordered_bars[0][0].isoformat(),
        "window_end": end_day.isoformat(),
        "first_valid_date": first_valid.isoformat() if first_valid else None,
        "last_valid_date": last_valid.isoformat() if last_valid else None,
        "price_date": end_day.isoformat(),
        "latest_report_period": latest[1] if latest else None,
        "latest_announce_date": latest[0].isoformat() if latest else None,
    }
    if include_history:
        # Same fixed end-date sample as the current card; not a rolling five-year rank.
        result["history_basis"] = "fixed_current_window"
        result["history"] = [
            {"date": day.isoformat(), "pe": round(value, 6),
             "percentile": round(100 * sum(peer <= value for peer in values) / len(values), 2)}
            for day, value in dated_values
        ]
    return result
