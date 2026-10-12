"""Recent 3-year financial report loading."""
import importlib
import json
import re

from app.financial.health import build_financial_health
from app.financial.quarterly_monitor import build_quarterly_financial_monitor
from app.financial.industry_position import build_industry_financial_position

def load_recent_three_year_financial_reports(market: str, symbol: str, years: int = 6) -> dict[str, object]:
    """Load annual/quarterly reports covering the most recent ``years`` fiscal years."""
    search_index = importlib.import_module("app.search.index")

    try:
        years = int(years)
    except (TypeError, ValueError) as exc:
        raise ValueError("years must be an integer") from exc
    if not 1 <= years <= 6:
        raise ValueError("years must be between 1 and 6")

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
            earliest_year = latest_year - years + 1

    if not matched_reports:
        raise ValueError(f"no recent financial reports found for {market}:{symbol}")

    matched_reports.sort(key=lambda row: str(row.get("report_date") or ""), reverse=True)
    latest_report_seed = matched_reports[0]
    latest_period_label = str(latest_report_seed.get("period") or "")
    latest_year = int(str(latest_report_seed.get("year") or "0")[:4] or "0")
    earliest_year = latest_year - years + 1 if latest_year else 0
    filtered_rows = [
        row for row in matched_reports
        if int(str(row.get("year") or "0")[:4] or "0") >= earliest_year
    ]
    reports = [_materialize_financial_report(search_index, row) for row in filtered_rows]
    reports.sort(key=lambda row: str(row.get("report_date") or ""))
    latest_report = reports[-1] if reports else None
    industry_row = next(
        (row for row in search_index.load_industry_rows() if str(row.get("market") or "").lower() == market and str(row.get("symbol") or "").zfill(6) == symbol),
        {},
    )
    industry = {
        "level_1": str(industry_row.get("industry_level_1_name") or "").strip() or None,
        "level_2": str(industry_row.get("industry_level_2_name") or "").strip() or None,
    }
    health = build_financial_health(
        reports,
        industry_level_1=industry["level_1"],
        industry_level_2=industry["level_2"],
    )

    quarterly_monitor = build_quarterly_financial_monitor(
        reports,
        industry_level_1=industry["level_1"],
    )
    industry_position = build_industry_financial_position(market, symbol, search_index._load_financial_snapshot() or {})

    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name or symbol,
        "latest_report": latest_report,
        "latest_period_label": latest_period_label,
        "reports": reports,
        "industry": industry,
        "health": health,
        "quarterly_monitor": quarterly_monitor,
        "industry_financial_position": industry_position,
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
    # TDX exposes ``营业收入`` as a period-only value in some reports (notably Q4),
    # while ``其中：营业收入`` is the cumulative statutory line comparable across years.
    getter = getattr(matched_row, "get", lambda _key: None)
    revenue = search_index._pick(getter("其中：营业收入"))
    if revenue is None:
        revenue = search_index._pick(getter("营业收入"))
    capex = search_index._pick(getter("购建固定资产、无形资产和其他长期资产支付的现金"))
    ocf = search_index._pick(getter("经营活动产生的现金流量净额"))
    metrics = {
        "revenue": revenue,
        "profit": search_index._pick(getter("净利润")),
        "net_profit": search_index._pick(getter("归属于母公司所有者的净利润")),
        "ex_net_profit": search_index._pick(getter("扣除非经常性损益后的净利润")),
        "gross_margin": search_index._pick(getter("销售毛利率(%)(非金融类指标)")),
        "net_margin": search_index._pick(getter("销售净利率(%)")),
        "roe_ex": derived.get("roe_ex"),
        "debt_ratio": search_index._pick(getter("资产负债率(%)")),
        "ocf": ocf,
        # Free cash flow uses the same report-period cumulative cash flows:
        # operating cash flow minus capital expenditure.
        "free_cf": ocf - capex if ocf is not None and capex is not None else None,
        "capex": capex,
        "goodwill": search_index._pick(getter("商誉")),
        "equity": search_index._pick(getter("归属于母公司股东权益(资产负债表)")),
        "total_assets": search_index._pick(getter("资产总计")),
        "accounts_receivable": search_index._pick(getter("应收账款")),
        "inventory": search_index._pick(getter("存货")),
    }
    return {
        "report_date": seed.get("report_date"),
        "announce_date": seed.get("announce_date"),
        "year": seed.get("year"),
        "period": seed.get("period"),
        "metrics": metrics,
    }

