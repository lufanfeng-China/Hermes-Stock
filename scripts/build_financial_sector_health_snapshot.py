#!/usr/bin/env python3
"""Build bank/securities annual and per-stock-latest quarterly health snapshot."""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.financial.sector_external_update import FinancialSectorStatusStore  # noqa: E402
from app.financial.sector_health import (  # noqa: E402
    score_bank_health,
    score_bank_quarterly_monitor,
    score_securities_health,
    score_securities_quarterly_monitor,
)
from app.financial.sector_health_data import build_bank_metrics, build_securities_metrics  # noqa: E402
from scripts.update_financial_sector_external import _cohort, _period_key  # noqa: E402

ROOT = PROJECT_ROOT / "data" / "derived" / "financial_sector"
EVIDENCE_DIR = ROOT / "evidence"
STATUS_DIR = ROOT / "update_status"
OUTPUT = ROOT / "sector_health_snapshot.json"
WAREHOUSE = PROJECT_ROOT / "data" / "derived" / "financial_ts" / "by_quarter"
ANNUAL_PERIODS = ["2021A", "2022A", "2023A", "2024A", "2025A"]


def _load_frame(period: str) -> pd.DataFrame | None:
    path = WAREHOUSE / f"{period}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    frame.index = frame.index.astype(str).str.zfill(6)
    return frame


def _row(frame: pd.DataFrame | None, symbol: str) -> dict[str, object] | None:
    if frame is None or symbol not in frame.index:
        return None
    row = frame.loc[symbol]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[-1]
    result: dict[str, object] = {}
    for key, value in row.to_dict().items():
        if isinstance(value, float) and not math.isfinite(value):
            result[str(key)] = None
        elif hasattr(value, "item"):
            try:
                result[str(key)] = value.item()
            except Exception:
                result[str(key)] = value
        else:
            result[str(key)] = value
    return result


def _evidence(symbol: str, period: str, source_type: str) -> dict[str, object] | None:
    path = EVIDENCE_DIR / symbol / f"{period}__{source_type}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _merged_period_evidence(symbol: str, period: str) -> dict[str, object] | None:
    sources = [
        _evidence(symbol, period, "annual_report"),
        _evidence(symbol, period, "quarterly_report"),
        _evidence(symbol, period, "half_year_report"),
        _evidence(symbol, period, "pillar3_report"),
    ]
    sources = [source for source in sources if source]
    if not sources:
        return None
    metrics: dict[str, object] = {}
    source_refs: list[dict[str, object]] = []
    for source in sources:
        raw_metrics = source.get("metrics")
        if isinstance(raw_metrics, dict):
            for field, evidence in raw_metrics.items():
                metrics.setdefault(str(field), evidence)
        source_refs.append({
            "source_type": source.get("source_type"),
            "announcement_id": source.get("announcement_id"),
            "source_url": source.get("source_url"),
            "pdf_sha256": source.get("pdf_sha256"),
        })
    return {"symbol": symbol, "report_period": period, "metrics": metrics, "sources": source_refs}


def _metric(evidence: Mapping[str, object] | None, name: str) -> float | None:
    if not evidence:
        return None
    metrics = evidence.get("metrics")
    item = metrics.get(name) if isinstance(metrics, Mapping) else None
    if not isinstance(item, Mapping):
        return None
    try:
        quality = float(item.get("quality"))
    except (TypeError, ValueError):
        return None
    if quality < 80:
        return None
    value = item.get("value")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _statement_number(row: Mapping[str, object] | None, *names: str) -> float | None:
    if not row:
        return None
    for name in names:
        try:
            value = float(row.get(name))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return None


def _quarterly_statement_inputs(row: Mapping[str, object] | None) -> dict[str, float | None]:
    revenue = _statement_number(row, "其中：营业收入", "营业收入")
    impairment_wan = _statement_number(row, "信用减值损失(万元)", "信用减值损失(万元、2019格式)")
    investment = _statement_number(row, "投资收益")
    fair_value = _statement_number(row, "加：公允价值变动净收益")
    if fair_value is None:
        loss = _statement_number(row, "公允价值变动损失")
        fair_value = -loss if loss is not None else None
    return {
        "credit_impairment_revenue_pct": (
            abs(impairment_wan * 10000.0 / revenue * 100.0)
            if impairment_wan is not None and revenue not in (None, 0) else None
        ),
        "proprietary_income_revenue_pct": (
            ((investment or 0.0) + (fair_value or 0.0)) / revenue * 100.0
            if revenue not in (None, 0) and (investment is not None or fair_value is not None) else None
        ),
    }


def _quarterly_bank_metrics(
    evidence: Mapping[str, object], current_row: Mapping[str, object] | None = None,
) -> dict[str, object]:
    fields = (
        "npl_ratio", "provision_coverage_ratio", "cet1_ratio", "tier1_ratio",
        "capital_adequacy_ratio", "net_interest_margin", "cost_income_ratio",
        "liquidity_coverage_ratio", "net_stable_funding_ratio",
    )
    return {
        **{field: _metric(evidence, field) for field in fields},
        "credit_impairment_revenue_pct": _quarterly_statement_inputs(current_row)["credit_impairment_revenue_pct"],
    }


def _quarterly_securities_metrics(
    evidence: Mapping[str, object], current_row: Mapping[str, object] | None,
    previous_evidence: Mapping[str, object] | None, previous_row: Mapping[str, object] | None,
) -> dict[str, object]:
    equity = _statement_number(current_row, "归属于母公司股东权益(资产负债表)")
    net_capital = _metric(evidence, "net_capital")
    current_margin = _metric(evidence, "margin_financing_balance")
    previous_margin = _metric(previous_evidence, "margin_financing_balance")
    current_statement = _quarterly_statement_inputs(current_row)
    previous_statement = _quarterly_statement_inputs(previous_row)
    current_impairment = current_statement["credit_impairment_revenue_pct"]
    previous_impairment = previous_statement["credit_impairment_revenue_pct"]
    margin_growth = current_margin / previous_margin - 1 if current_margin is not None and previous_margin not in (None, 0) else None
    impairment_growth = (current_impairment / previous_impairment - 1
                         if current_impairment is not None and previous_impairment not in (None, 0) else None)
    if margin_growth is not None and impairment_growth is not None and margin_growth > 0.2 and impairment_growth > 0.2:
        margin_risk = "both_rising"
    elif ((margin_growth is not None and margin_growth > 0.2)
          or (impairment_growth is not None and impairment_growth > 0.2)):
        margin_risk = "one_rising"
    else:
        margin_risk = "stable" if margin_growth is not None and impairment_growth is not None else None
    return {
        "risk_coverage_ratio": _metric(evidence, "risk_coverage_ratio"),
        "capital_leverage_ratio": _metric(evidence, "capital_leverage_ratio"),
        "net_capital_to_net_assets_pct": (net_capital / equity * 100.0 if net_capital is not None and equity not in (None, 0) else None),
        "liquidity_coverage_ratio": _metric(evidence, "liquidity_coverage_ratio"),
        "net_stable_funding_ratio": _metric(evidence, "net_stable_funding_ratio"),
        "proprietary_income_revenue_pct": current_statement["proprietary_income_revenue_pct"],
        "margin_financing_balance": current_margin,
        "credit_impairment_revenue_pct": current_impairment,
        "margin_financing_risk": margin_risk,
    }


def _previous_same_period(period: str) -> str:
    return f"{int(period[:4]) - 1}{period[4:]}"


def _merge_score_update_if_current(
    latest_status: dict[str, object], *, base_announced: str, base_status: str,
    score_update: dict[str, object],
) -> dict[str, object]:
    if (str(latest_status.get("latest_announced_period") or "") == base_announced
            and str(latest_status.get("status") or "not_started") == base_status):
        safe_update = score_update
    else:
        annual_score_keys = {
            "annual_score", "annual_score_version", "annual_period", "symbol", "name", "sector_model",
        }
        safe_update = {key: value for key, value in score_update.items() if key in annual_score_keys}
    return {**latest_status, **safe_update}


def _withhold_stale_quarterly_score(
    status_record: dict[str, object], score_update: dict[str, object],
) -> dict[str, object]:
    update = dict(score_update)
    old_period = status_record.get("latest_scored_period")
    old_score = status_record.get("quarterly_score")
    if old_period and old_score is not None:
        update.setdefault("previous_quarterly_period", old_period)
        update.setdefault("previous_quarterly_score", old_score)
    update["quarterly_score"] = None
    update["quarterly_status"] = "pending_update"
    return update


def build() -> dict[str, object]:
    annual_frames = {period: _load_frame(period) for period in ANNUAL_PERIODS}
    quarter_frames: dict[str, pd.DataFrame | None] = {}
    store = FinancialSectorStatusStore(STATUS_DIR)
    stocks: dict[str, dict[str, object]] = {}
    status_updates: dict[str, tuple[str, str, dict[str, object]]] = {}

    for stock in _cohort():
        symbol = stock["symbol"]
        status_record = store.load_symbol_status(symbol)
        annual_rows = [_row(annual_frames[period], symbol) for period in ANNUAL_PERIODS]
        annual_evidence = [_evidence(symbol, period, "annual_report") for period in ANNUAL_PERIODS]
        annual_result: dict[str, object] | None = None
        annual_inputs: dict[str, object] = {}
        if all(row is not None for row in annual_rows) and all(item is not None for item in annual_evidence):
            if stock["sector_model"] == "bank":
                annual_inputs = build_bank_metrics(annual_rows, annual_evidence)  # type: ignore[arg-type]
                annual_result = score_bank_health(annual_inputs)
            else:
                annual_inputs = build_securities_metrics(annual_rows, annual_evidence)  # type: ignore[arg-type]
                annual_result = score_securities_health(annual_inputs)

        latest_period = str(status_record.get("latest_valid_period") or "")
        quarterly_result: dict[str, object] | None = None
        quarterly_inputs: dict[str, object] = {}
        merged = _merged_period_evidence(symbol, latest_period) if latest_period else None
        if merged:
            frame_period = latest_period.replace("H1", "Q2")
            if frame_period not in quarter_frames:
                quarter_frames[frame_period] = _load_frame(frame_period)
            current_row = _row(quarter_frames[frame_period], symbol)
            previous_period = _previous_same_period(frame_period)
            if previous_period not in quarter_frames:
                quarter_frames[previous_period] = _load_frame(previous_period)
            previous_row = _row(quarter_frames[previous_period], symbol)
            previous_external = _merged_period_evidence(symbol, _previous_same_period(latest_period))
            year_start_period = f"{int(latest_period[:4]) - 1}A"
            year_start_external = _merged_period_evidence(symbol, year_start_period)
            if stock["sector_model"] == "bank":
                quarterly_inputs = _quarterly_bank_metrics(merged, current_row)
                previous_inputs = _quarterly_bank_metrics(previous_external, previous_row) if previous_external else {}
                year_start_inputs = (
                    _quarterly_bank_metrics(year_start_external, annual_rows[-1])
                    if year_start_external and annual_rows[-1] is not None else {}
                )
                previous_monitor = score_bank_quarterly_monitor(
                    previous_inputs, report_period=_previous_same_period(latest_period)
                ) if previous_inputs else None
                quarterly_result = score_bank_quarterly_monitor(
                    quarterly_inputs,
                    report_period=latest_period,
                    previous_score=previous_monitor.get("score") if previous_monitor else None,
                    previous_metrics=previous_inputs,
                    year_start_metrics=year_start_inputs,
                )
            else:
                quarterly_inputs = _quarterly_securities_metrics(
                    merged, current_row, previous_external, previous_row,
                )
                previous_inputs = (_quarterly_securities_metrics(previous_external, previous_row, None, None)
                                   if previous_external else {})
                year_start_inputs = (
                    _quarterly_securities_metrics(
                        year_start_external, annual_rows[-1], annual_evidence[-2], annual_rows[-2],
                    ) if year_start_external and annual_rows[-1] is not None else {}
                )
                previous_monitor = score_securities_quarterly_monitor(
                    previous_inputs, report_period=_previous_same_period(latest_period)
                ) if previous_inputs else None
                quarterly_result = score_securities_quarterly_monitor(
                    quarterly_inputs,
                    report_period=latest_period,
                    previous_score=previous_monitor.get("score") if previous_monitor else None,
                    previous_metrics=previous_inputs,
                    year_start_metrics=year_start_inputs,
                )

        model_label = "银行模型" if stock["sector_model"] == "bank" else "证券模型"
        announced_period = str(status_record.get("latest_announced_period") or "")
        candidate_score = quarterly_result.get("score") if quarterly_result else None
        publishable_quarterly = bool(
            candidate_score is not None
            and latest_period
            and latest_period == announced_period
            and status_record.get("status") == "up_to_date"
        )
        previous_quarterly_period = status_record.get("previous_quarterly_period")
        previous_quarterly_score = status_record.get("previous_quarterly_score")
        if candidate_score is not None and not publishable_quarterly:
            previous_quarterly_period = latest_period
            previous_quarterly_score = candidate_score
        elif not publishable_quarterly and status_record.get("quarterly_score") is not None:
            previous_quarterly_period = status_record.get("latest_scored_period")
            previous_quarterly_score = status_record.get("quarterly_score")
        current_quarterly_result = quarterly_result if publishable_quarterly else None
        latest_scored_period = (
            latest_period if candidate_score is not None else status_record.get("latest_scored_period")
        )
        record = {
            **stock,
            "financial_model": {"code": stock["sector_model"], "label": model_label},
            "annual_period": "2025A",
            "annual_score": annual_result,
            "annual_inputs": annual_inputs,
            "quarterly_score": current_quarterly_result,
            "quarterly_inputs": quarterly_inputs,
            "latest_announced_period": status_record.get("latest_announced_period"),
            "latest_valid_period": status_record.get("latest_valid_period"),
            "latest_scored_period": latest_scored_period,
            "previous_quarterly_period": previous_quarterly_period,
            "previous_quarterly_score": previous_quarterly_score,
            "update_status": status_record.get("status", "not_started"),
            "last_error": status_record.get("last_error"),
        }
        stocks[symbol] = record

        score_update: dict[str, object] = {
            "symbol": symbol, "name": stock["name"], "sector_model": stock["sector_model"],
        }
        if annual_result:
            score_update["annual_score"] = annual_result.get("score")
            score_update["annual_score_version"] = annual_result.get("score_version")
            score_update["annual_period"] = "2025A"
        if publishable_quarterly and quarterly_result:
            previous_scored_period = status_record.get("latest_scored_period")
            previous_score = status_record.get("quarterly_score")
            if previous_scored_period and previous_scored_period != latest_period and previous_score is not None:
                score_update["previous_quarterly_period"] = previous_scored_period
                score_update["previous_quarterly_score"] = previous_score
            score_update["latest_scored_period"] = latest_period
            score_update["quarterly_score"] = candidate_score
            score_update["quarterly_status"] = quarterly_result.get("status")
            score_update["quarterly_score_version"] = quarterly_result.get("score_version")
        else:
            if candidate_score is not None:
                score_update["latest_scored_period"] = latest_period
                score_update["previous_quarterly_period"] = latest_period
                score_update["previous_quarterly_score"] = candidate_score
            score_update = _withhold_stale_quarterly_score(status_record, score_update)
        status_updates[symbol] = (
            announced_period, str(status_record.get("status") or "not_started"), score_update,
        )

    annual_counts = Counter(
        "scored" if record.get("annual_score") and record["annual_score"].get("score") is not None else "insufficient_evidence"
        for record in stocks.values()
    )
    quarterly_counts = Counter(
        "scored" if record.get("quarterly_score") and record["quarterly_score"].get("score") is not None else "insufficient_evidence"
        for record in stocks.values()
    )
    period_distribution = Counter(
        str(record.get("latest_scored_period") or "pending") for record in stocks.values()
    )
    payload = {
        "schema_version": "financial-sector-health-v1",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "annual_periods": ANNUAL_PERIODS,
        "quarterly_mode": "per_stock_latest",
        "quarterly_newest_period": max(
            (str(record.get("latest_scored_period") or "") for record in stocks.values() if record.get("latest_scored_period")),
            key=_period_key,
            default=None,
        ),
        "stock_count": len(stocks),
        "annual_status_counts": dict(annual_counts),
        "quarterly_status_counts": dict(quarterly_counts),
        "period_distribution": dict(period_distribution),
        "stocks": stocks,
    }
    FinancialSectorStatusStore._atomic_write_json(OUTPUT, payload)
    for symbol, (base_announced, base_status, score_update) in status_updates.items():
        with store.symbol_lock(symbol):
            latest_status = store.load_symbol_status(symbol)
            store.save_symbol_status(_merge_score_update_if_current(
                latest_status, base_announced=base_announced, base_status=base_status,
                score_update=score_update,
            ))
    store.build_summary([stock["symbol"] for stock in _cohort()])
    return payload


if __name__ == "__main__":
    result = build()
    print(json.dumps({
        "ok": True,
        "path": str(OUTPUT),
        "stock_count": result["stock_count"],
        "annual_status_counts": result["annual_status_counts"],
        "quarterly_status_counts": result["quarterly_status_counts"],
        "period_distribution": result["period_distribution"],
    }, ensure_ascii=False))
