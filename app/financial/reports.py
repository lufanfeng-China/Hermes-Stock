"""Recent 3-year financial report loading."""
import importlib
import json
import re

def load_recent_three_year_financial_reports(market: str, symbol: str) -> dict[str, object]:
    search_index = importlib.import_module("app.search.index")

    market = str(market or "").strip().lower()
    symbol = str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"}:
        raise ValueError("market must be sh, sz or bj")
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    def row_matches(row_symbol: str) -> bool:
        row_symbol = str(row_symbol).strip()
        if row_symbol != symbol:
            return False
        if market == "sh":
            return row_symbol.startswith(("5", "6", "9"))
        if market == "sz":
            return row_symbol.startswith(("0", "1", "2", "3", "4", "8"))
        return row_symbol.startswith(("4", "8", "9"))

    matched_reports: list[dict[str, object]] = []
    stock_name = search_index._stock_name_lookup().get((market, symbol), "")
    latest_year: int | None = None
    earliest_year: int | None = None

    for report_date, fp in search_index._all_financial_files():
        report_year = int(str(report_date or "0")[:4] or "0")
        if earliest_year is not None and report_year < earliest_year:
            break
        loaded = search_index._load_file(fp)
        if loaded is None:
            continue
        _date_str, df = loaded

        matched_row = None
        for row_symbol, row in df.iterrows():
            if row_matches(str(row_symbol)):
                matched_row = row
                break
        if matched_row is None:
            continue

        period_label = _report_date_to_period_label(str(report_date))
        announce_raw = matched_row.get("announce_date") if hasattr(matched_row, "get") else None
        announce_date = ""
        try:
            picked_announce = search_index._pick(announce_raw)
            if picked_announce is not None:
                announce_date = str(int(picked_announce))
        except (TypeError, ValueError):
            announce_date = str(announce_raw or "").strip()

        matched_reports.append(
            {
                "report_date": str(report_date),
                "announce_date": announce_date,
                "year": str(report_date)[:4],
                "period": period_label,
                "row": matched_row,
            }
        )
        if latest_year is None:
            latest_year = report_year
            earliest_year = latest_year - 2

    if not matched_reports:
        raise ValueError(f"no recent financial reports found for {market}:{symbol}")

    matched_reports.sort(key=lambda row: str(row.get("report_date") or ""), reverse=True)
    latest_report_seed = matched_reports[0]
    latest_period_label = str(latest_report_seed.get("period") or "")
    latest_year = int(str(latest_report_seed.get("year") or "0")[:4] or "0")
    earliest_year = latest_year - 2 if latest_year else 0
    filtered_rows = [
        row for row in matched_reports
        if int(str(row.get("year") or "0")[:4] or "0") >= earliest_year
    ]
    reports = [_materialize_financial_report(search_index, row) for row in filtered_rows]
    reports.sort(key=lambda row: str(row.get("report_date") or ""))
    latest_report = reports[-1] if reports else None

    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name or symbol,
        "latest_report": latest_report,
        "latest_period_label": latest_period_label,
        "reports": reports,
    }



def _report_date_to_period_label(report_date: str) -> str:
    text = str(report_date or "").strip()
    if len(text) != 8 or not text.isdigit():
        return text
    year = text[:4]
    month_day = text[4:]
    mapping = {
        "0331": "Q1",
        "0630": "Q2",
        "0930": "Q3",
        "1231": "A",
    }
    suffix = mapping.get(month_day)
    if not suffix:
        return text
    return f"{year}{suffix}"



def _extract_period_quarter(period_label: str) -> str:
    text = str(period_label or "").strip().upper()
    match = re.match(r"^\d{4}(Q[1-4]|A)$", text)
    return match.group(1) if match else ""


def _materialize_financial_report(search_index, seed: dict[str, object]) -> dict[str, object]:
    matched_row = seed.get("row")
    derived = search_index._derive_sub_fields(matched_row, None)
    metrics = {
        "revenue": search_index._pick(matched_row.get("营业收入")),
        "net_profit": search_index._pick(matched_row.get("归属于母公司所有者的净利润")),
        "ex_net_profit": search_index._pick(matched_row.get("扣除非经常性损益后的净利润")),
        "ocf": search_index._pick(matched_row.get("经营活动产生的现金流量净额")),
        "roe_ex": derived.get("roe_ex"),
        "debt_ratio": derived.get("debt_ratio"),
        "current_ratio": derived.get("current_ratio"),
        "quick_ratio": derived.get("quick_ratio"),
        "profit_growth": derived.get("profit_growth"),
        "revenue_growth": derived.get("revenue_growth"),
        "ex_profit_growth": derived.get("ex_profit_growth"),
        "ocf_to_profit": derived.get("ocf_to_profit"),
        "free_cf": derived.get("free_cf"),
    }
    return {
        "report_date": seed.get("report_date"),
        "announce_date": seed.get("announce_date"),
        "year": seed.get("year"),
        "period": seed.get("period"),
        "metrics": metrics,
    }

