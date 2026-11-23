#!/usr/bin/env python3
"""Incrementally collect bank/securities regulatory fields from CNINFO reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pymupdf
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.financial.sector_external_update import (  # noqa: E402
    ExternalUpdateError,
    FinancialSectorStatusStore,
    extract_labeled_number,
    normalize_cninfo_pdf_url,
    run_symbol_updates,
    select_cninfo_reports,
)
from app.stock_filter import _universe  # noqa: E402

ROOT = PROJECT_ROOT / "data" / "derived" / "financial_sector"
STATUS_DIR = ROOT / "update_status"
RAW_DIR = ROOT / "raw"
EVIDENCE_DIR = ROOT / "evidence"
CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}

BANK_METRICS = {
    "npl_ratio": (("不良贷款率",), 0, 20),
    "provision_coverage_ratio": (("拨备覆盖率",), 0, 2000),
    "cet1_ratio": (("核心一级资本充足率",), 0, 100),
    "tier1_ratio": (("一级资本充足率",), 0, 100),
    "capital_adequacy_ratio": (("资本充足率",), 0, 100),
    "net_interest_margin": (("净利息收益率", "净息差"), -20, 20),
    "cost_income_ratio": (("成本收入比",), 0, 100),
    "liquidity_coverage_ratio": (("流动性覆盖率",), 0, 5000),
    "net_stable_funding_ratio": (("净稳定资金比例", "净稳定资金率"), 0, 5000),
}

SECURITIES_METRICS = {
    "net_capital": (("净资本",), 0, None),
    "risk_coverage_ratio": (("风险覆盖率",), 0, 5000),
    "capital_leverage_ratio": (("资本杠杆率",), 0, 100),
    "liquidity_coverage_ratio": (("流动性覆盖率",), 0, 5000),
    "net_stable_funding_ratio": (("净稳定资金率",), 0, 5000),
    "brokerage_net_revenue": (("证券经纪业务净收入",), 0, None),
    "investment_banking_net_revenue": (("投资银行业务手续费净收入", "投资银行业务净收入"), 0, None),
    "asset_management_net_revenue": ((
        "资产管理业务手续费净收入", "资产管理业务净收入", "资产管理及基金管理业务手续费净收入",
    ), 0, None),
    "margin_financing_balance": (("融出资金",), 0, None),
}

BANK_CORE = {"npl_ratio", "provision_coverage_ratio", "cet1_ratio", "capital_adequacy_ratio"}
SECURITIES_CORE = {"net_capital", "risk_coverage_ratio", "capital_leverage_ratio", "liquidity_coverage_ratio", "net_stable_funding_ratio"}


def _period_key(period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(20\d{2})(Q1|H1|Q2|Q3|A)", str(period))
    if not match:
        return (0, 0)
    rank = {"Q1": 1, "H1": 2, "Q2": 2, "Q3": 3, "A": 4}
    return int(match.group(1)), rank[match.group(2)]


def _cohort() -> list[dict[str, str]]:
    rows, _ = _universe()
    result: list[dict[str, str]] = []
    for row in rows:
        industry = str(row.get("industry_level_2_name") or "")
        if industry in {"地方性银行", "全国性银行"}:
            sector = "bank"
        elif industry == "证券":
            sector = "securities"
        else:
            continue
        result.append({
            "symbol": str(row.get("symbol") or ""),
            "name": str(row.get("stock_name") or row.get("symbol") or ""),
            "market": str(row.get("market") or ""),
            "sector_model": sector,
        })
    result.sort(key=lambda item: item["symbol"])
    counts = {sector: sum(item["sector_model"] == sector for item in result) for sector in ("bank", "securities")}
    if counts != {"bank": 42, "securities": 48}:
        raise RuntimeError(f"金融专用模型范围必须为银行42只、证券48只，当前为{counts}")
    return result


def _request_json(session: requests.Session, *, data: dict[str, str]) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.post(
                CNINFO_QUERY, data=data, headers=HEADERS, timeout=30, allow_redirects=False,
            )
            if response.is_redirect or response.is_permanent_redirect:
                raise ValueError("CNINFO公告查询不允许重定向")
            final_url = urlsplit(str(response.url or ""))
            if (final_url.scheme.lower() != "https"
                    or (final_url.hostname or "").lower() != "www.cninfo.com.cn"
                    or final_url.port not in (None, 443)):
                raise ValueError("CNINFO公告查询响应来源不是固定HTTPS主机")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("CNINFO response is not an object")
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise ExternalUpdateError("announcement_not_found", f"巨潮公告查询失败：{last_error}")


def _request_all_announcements(session: requests.Session, *, data: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    page = 1
    total_pages = 1
    while page <= min(total_pages, 20):
        payload = _request_json(session, data={**data, "pageNum": str(page)})
        announcements = payload.get("announcements") or []
        if isinstance(announcements, list):
            rows.extend(row for row in announcements if isinstance(row, dict))
        try:
            raw_total_pages = payload.get("totalpages")
            total_pages = max(page, int(str(raw_total_pages or page)))
        except (TypeError, ValueError):
            total_pages = page
        if page >= total_pages or payload.get("hasMore") is False:
            break
        page += 1
    return rows


def discover_reports(session: requests.Session, stock: dict[str, str]) -> list[dict[str, object]]:
    today = datetime.now().date().isoformat()
    common = {
        "stock": "",
        "tabName": "fulltext",
        "pageSize": "50",
        "pageNum": "1",
        "column": "sse" if stock["market"] == "sh" else "szse",
        "searchkey": stock["symbol"],
        "secid": "",
        "plate": "sh" if stock["market"] == "sh" else "sz",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    annual_payload = _request_json(session, data={
        **common,
        "category": "category_ndbg_szsh",
        "seDate": f"2021-01-01~{today}",
    })
    annual_rows = annual_payload.get("announcements") or []
    if not isinstance(annual_rows, list):
        annual_rows = []
    annual_selected = select_cninfo_reports(
        [row for row in annual_rows if isinstance(row, dict)], symbol=stock["symbol"]
    )
    org_id = next((str(row.get("org_id") or "") for row in reversed(annual_selected)
                   if str(row.get("org_id") or "")), "")
    if org_id:
        for attempt in range(3):
            exact_annual_payload = _request_json(session, data={
                **common,
                "stock": f"{stock['symbol']},{org_id}",
                "searchkey": "",
                "category": "category_ndbg_szsh",
                "seDate": f"2021-01-01~{today}",
            })
            exact_rows = exact_annual_payload.get("announcements") or []
            if isinstance(exact_rows, list):
                exact_selected = select_cninfo_reports(
                    [row for row in exact_rows if isinstance(row, dict)], symbol=stock["symbol"]
                )
                exact_annual = [row for row in exact_selected if row["source_type"] == "annual_report"
                                and 2021 <= int(str(row["report_period"])[:4]) <= 2025]
                if len(exact_annual) >= 5:
                    annual_rows = exact_rows
                    annual_selected = exact_selected
                    break
            if attempt < 2:
                time.sleep(1 + attempt)
    current_year = datetime.now().year
    current_rows: list[dict[str, object]] = []
    for query_year in (current_year - 1, current_year):
        range_end = today if query_year == current_year else f"{query_year}-12-31"
        current_rows.extend(_request_all_announcements(session, data={
            **common,
            "stock": f"{stock['symbol']},{org_id}" if org_id else "",
            "searchkey": "" if org_id else stock["symbol"],
            "category": "",
            "seDate": f"{query_year}-01-01~{range_end}",
        }))
    announcements: list[object] = list(annual_rows)
    announcements.extend(current_rows)
    selected = select_cninfo_reports(
        [row for row in announcements if isinstance(row, dict)],
        symbol=stock["symbol"],
    )
    annual = [row for row in selected if row["source_type"] == "annual_report" and int(str(row["report_period"])[:4]) >= 2021]
    interim = [row for row in selected if row["source_type"] != "annual_report"]
    latest_interim_period = max((str(row["report_period"]) for row in interim), key=_period_key, default="")
    reference_period = (
        f"{int(latest_interim_period[:4]) - 1}{latest_interim_period[4:]}" if latest_interim_period else ""
    )
    latest_interim = [
        row for row in interim if row["report_period"] in {latest_interim_period, reference_period}
    ]
    reports = annual + latest_interim
    reports.sort(key=lambda row: (_period_key(str(row["report_period"])), str(row["source_type"])))
    return reports


def _download_pdf(session: requests.Session, url: str) -> bytes:
    safe_url = normalize_cninfo_pdf_url(url)
    if safe_url is None:
        raise ExternalUpdateError("pdf_download_failed", "PDF地址不属于巨潮静态HTTPS主机")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(safe_url, headers=HEADERS, timeout=90, allow_redirects=False)
            if response.is_redirect or response.is_permanent_redirect:
                raise ValueError("PDF下载不允许重定向")
            response.raise_for_status()
            content = response.content
            if not content.startswith(b"%PDF"):
                raise ValueError("response is not a PDF")
            return content
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise ExternalUpdateError("pdf_download_failed", f"PDF下载失败：{last_error}")


def _pdf_pages(content: bytes) -> list[tuple[int, list[str]]]:
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ExternalUpdateError("pdf_invalid", f"PDF无法打开：{exc}") from exc
    pages: list[tuple[int, list[str]]] = []
    try:
        for index, page in enumerate(document):
            lines = [line.strip() for line in page.get_text().splitlines() if line.strip()]
            pages.append((index + 1, lines))
    finally:
        document.close()
    return pages


def _extract_metrics(pages: Iterable[tuple[int, list[str]]], sector: str) -> dict[str, dict[str, object]]:
    definitions = BANK_METRICS if sector == "bank" else SECURITIES_METRICS
    result: dict[str, dict[str, object]] = {}
    for field, (aliases, minimum, maximum) in definitions.items():
        candidates: list[dict[str, object]] = []
        for page_number, lines in pages:
            eligible_lines = lines
            if field == "tier1_ratio":
                eligible_lines = [line for line in lines if "核心一级资本充足率" not in line]
            elif field == "capital_adequacy_ratio":
                eligible_lines = [
                    line for line in lines
                    if "核心一级资本充足率" not in line and "一级资本充足率" not in line
                ]
            evidence = extract_labeled_number(eligible_lines, aliases=aliases, minimum=minimum, maximum=maximum)
            if evidence:
                candidates.append({**evidence, "page_number": page_number})
        if candidates:
            candidates.sort(key=lambda item: int(str(item.get("quality") or 0)), reverse=True)
            result[field] = candidates[0]
    return result


def _write_evidence(path: Path, payload: dict[str, object]) -> None:
    FinancialSectorStatusStore._atomic_write_json(path, payload)


def _initial_report_states(
    previous: dict[str, object], discovered: list[dict[str, object]], *, targeted: bool,
) -> dict[str, object]:
    if targeted:
        return dict(previous)
    valid_keys = {str(row.get("report_key") or "") for row in discovered}
    return {key: value for key, value in previous.items() if key in valid_keys}


def _latest_announced_period(previous: str, discovered: str, *, targeted: bool) -> str:
    if not targeted:
        return discovered
    return max([period for period in (previous, discovered) if period], key=_period_key, default=discovered)


def _can_reuse_published_report(
    existing: dict[str, object], report: dict[str, object], *, verify_hash: bool,
) -> bool:
    # CNINFO can replace bytes behind an unchanged announcement URL.  Every
    # discovered published report must therefore be fetched and SHA-256 checked.
    return False


def _would_regress_published_fields(
    existing: dict[str, object], metrics: dict[str, dict[str, object]],
) -> bool:
    if existing.get("status") != "published":
        return False
    raw_fields = existing.get("fields")
    previous_fields = {str(field) for field in raw_fields} if isinstance(raw_fields, (list, tuple, set)) else set()
    if previous_fields and not previous_fields.issubset(metrics):
        return True
    raw_quality = existing.get("field_quality")
    previous_quality = dict(raw_quality) if isinstance(raw_quality, dict) else {}
    if not previous_quality and existing.get("evidence_path"):
        try:
            old_evidence = json.loads(Path(str(existing["evidence_path"])).read_text(encoding="utf-8"))
            old_metrics = old_evidence.get("metrics") if isinstance(old_evidence, dict) else None
            if isinstance(old_metrics, dict):
                previous_quality = {
                    str(field): item.get("quality") for field, item in old_metrics.items()
                    if isinstance(item, dict)
                }
        except (OSError, ValueError, TypeError):
            previous_quality = {}
    for field in previous_fields:
        item = metrics.get(field)
        if not isinstance(item, dict):
            return True
        try:
            value = float(item.get("value"))
            quality = float(item.get("quality"))
            old_quality = float(previous_quality.get(field, 80))
        except (TypeError, ValueError):
            return True
        if not math.isfinite(value) or not math.isfinite(quality) or quality < old_quality:
            return True
    return False


def _process_stock(
    request: dict[str, object],
    *,
    session: requests.Session,
    report_period: str = "",
    source_type: str = "",
    force: bool = False,
) -> dict[str, object]:
    stock = {key: str(request.get(key) or "") for key in ("symbol", "name", "market", "sector_model")}
    reports = discover_reports(session, stock)
    discovered_reports = list(reports)
    discovered_latest_period = max((str(row["report_period"]) for row in reports), key=_period_key, default="")
    if report_period:
        reports = [row for row in reports if row["report_period"] == report_period]
    if source_type:
        reports = [row for row in reports if row["source_type"] == source_type]
    if not reports:
        raise ExternalUpdateError("announcement_not_found", "未找到符合条件的完整财报公告")

    raw_previous_reports = request.get("reports")
    previous_reports: dict[str, object] = dict(raw_previous_reports) if isinstance(raw_previous_reports, dict) else {}
    report_states = _initial_report_states(
        previous_reports, discovered_reports, targeted=bool(report_period or source_type),
    )
    successful_periods: list[str] = []
    core_for_latest: set[str] = set()
    processed_latest_period = max((str(row["report_period"]) for row in reports), key=_period_key)

    for report in reports:
        key = str(report["report_key"])
        raw_existing = report_states.get(key)
        existing: dict[str, object] = dict(raw_existing) if isinstance(raw_existing, dict) else {}
        verify_hash = str(report["report_period"]) == discovered_latest_period
        if not force and existing and _can_reuse_published_report(existing, report, verify_hash=verify_hash):
            successful_periods.append(str(report["report_period"]))
            if report["report_period"] == processed_latest_period:
                existing_fields = existing.get("fields")
                if isinstance(existing_fields, (list, tuple, set)):
                    core_for_latest.update(str(field) for field in existing_fields)
            continue
        content = _download_pdf(session, str(report["source_url"]))
        digest = hashlib.sha256(content).hexdigest()
        if (not force and existing.get("status") == "published"
                and existing.get("announcement_id") == report.get("announcement_id")
                and existing.get("announcement_time") == report.get("announcement_time")
                and existing.get("source_url") == report.get("source_url")
                and existing.get("pdf_sha256") == digest):
            existing["last_verified_at"] = datetime.now(timezone.utc).isoformat()
            report_states[key] = existing
            successful_periods.append(str(report["report_period"]))
            if report["report_period"] == processed_latest_period:
                existing_fields = existing.get("fields")
                if isinstance(existing_fields, (list, tuple, set)):
                    core_for_latest.update(str(field) for field in existing_fields)
            continue
        raw_path = RAW_DIR / stock["symbol"] / f"{key.replace(':', '__')}.pdf"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        pages = _pdf_pages(content)
        metrics = _extract_metrics(pages, stock["sector_model"])
        if _would_regress_published_fields(existing, metrics):
            previous_fields = existing.get("fields")
            previous_field_count = len(previous_fields) if isinstance(previous_fields, list) else 0
            raise ExternalUpdateError(
                "validation_failed",
                f"{key}重解析字段从{previous_field_count}项降至{len(metrics)}项，保留旧可信证据",
            )
        evidence = {
            "schema_version": "financial-sector-evidence-v1",
            "symbol": stock["symbol"],
            "name": stock["name"],
            "sector_model": stock["sector_model"],
            **report,
            "pdf_sha256": digest,
            "metrics": metrics,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        evidence_path = EVIDENCE_DIR / stock["symbol"] / f"{key.replace(':', '__')}.json"
        temp_path = raw_path.with_suffix(".pdf.tmp")
        temp_path.write_bytes(content)
        temp_path.replace(raw_path)
        _write_evidence(evidence_path, evidence)
        report_states[key] = {
            "status": "published",
            "announcement_id": report["announcement_id"],
            "announcement_time": report["announcement_time"],
            "source_url": report["source_url"],
            "pdf_sha256": digest,
            "report_period": report["report_period"],
            "source_type": report["source_type"],
            "fields": sorted(metrics),
            "field_quality": {field: item.get("quality") for field, item in metrics.items()},
            "fields_found": len(metrics),
            "evidence_path": str(evidence_path),
        }
        successful_periods.append(str(report["report_period"]))
        if report["report_period"] == processed_latest_period:
            core_for_latest.update(metrics)
        print(json.dumps({"symbol": stock["symbol"], "report": key, "fields": len(metrics)}, ensure_ascii=False), flush=True)

    core = BANK_CORE if stock["sector_model"] == "bank" else SECURITIES_CORE
    published_periods = [
        str(state.get("report_period") or "")
        for state in report_states.values()
        if isinstance(state, dict) and state.get("status") == "published" and state.get("report_period")
    ]
    latest_valid = max(published_periods, key=_period_key, default=str(request.get("latest_valid_period") or ""))
    latest_announced = _latest_announced_period(
        str(request.get("latest_announced_period") or ""), discovered_latest_period,
        targeted=bool(report_period or source_type),
    )
    core_for_latest = set()
    for state in report_states.values():
        if not isinstance(state, dict):
            continue
        if state.get("status") == "published" and state.get("report_period") == latest_valid:
            core_for_latest.update(str(field) for field in (state.get("fields") or []))
    status = "up_to_date" if core.issubset(core_for_latest) else "insufficient_evidence"
    return {
        "name": stock["name"],
        "market": stock["market"],
        "sector_model": stock["sector_model"],
        "latest_announced_period": latest_announced,
        "latest_valid_period": latest_valid,
        "status": status,
        "reports": report_states,
        "latest_core_fields_found": sorted(core_for_latest),
        "latest_core_fields_expected": sorted(core),
        "last_error": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="")
    parser.add_argument("--report-period", default="")
    parser.add_argument("--source-type", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cohort = _cohort()
    if args.symbol:
        cohort = [row for row in cohort if row["symbol"] == args.symbol]
        if not cohort:
            print(json.dumps({"ok": False, "error": "symbol is not a bank/securities stock"}, ensure_ascii=False))
            return 2
    store = FinancialSectorStatusStore(STATUS_DIR)
    session = requests.Session()

    def processor(request: dict[str, object]) -> dict[str, object]:
        return _process_stock(
            request,
            session=session,
            report_period=args.report_period,
            source_type=args.source_type,
            force=args.force,
        )

    result = run_symbol_updates(cohort, processor=processor, store=store)
    summary = store.build_summary([row["symbol"] for row in _cohort()])
    print(json.dumps({**result, "summary": summary}, ensure_ascii=False), flush=True)
    # Individual failures are visible and retryable; only a global crash exits nonzero.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
