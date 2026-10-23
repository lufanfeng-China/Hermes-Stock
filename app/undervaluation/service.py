"""Current/PIT diagnostic assembly for good-stock + dual valuation evidence."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from app.relative_valuation.data_loader import load_industry_valuation_snapshot
from app.relative_valuation.history import FINANCIAL_TS_DIR, _load_daily_series
from .diagnosis import classify_quality_margin_quadrant
from .industry_evidence import evaluate_industry_evidence
from .own_valuation_history import (
    build_own_valuation_history,
    build_pit_disclosures_from_period_frames,
    summarize_own_valuation_history,
)
from .valuation_gate import evaluate_margin_evidence

ROOT = Path(__file__).resolve().parents[2]
STRICT_SNAPSHOT = ROOT / "data" / "derived" / "datasets" / "final" / "strict_financial_health_snapshot_2025A__2026Q2.json"
CURRENT_DIAGNOSIS_SNAPSHOT = ROOT / "data" / "derived" / "datasets" / "final" / "good_stock_undervaluation_current.json"


@lru_cache(maxsize=1)
def _current_diagnosis_snapshot() -> dict[str, Any]:
    return json.loads(CURRENT_DIAGNOSIS_SNAPSHOT.read_text(encoding="utf-8")) if CURRENT_DIAGNOSIS_SNAPSHOT.is_file() else {}


def load_current_diagnosis_list(category: str = "has_margin", page: int = 1, page_size: int = 50) -> dict[str, Any]:
    payload = _current_diagnosis_snapshot()
    rows = payload.get("stocks") or []
    predicates = {
        "has_margin": lambda row: (row.get("margin") or {}).get("status") == "HAS_MARGIN",
        "quality_no_margin": lambda row: (row.get("quadrant") or {}).get("quadrant") == "QUALITY_ELIGIBLE_NO_MARGIN",
        "quality_ineligible": lambda row: (row.get("quality") or {}).get("status") == "NOT_QUALITY_ELIGIBLE",
        "not_applicable": lambda row: (row.get("quality") or {}).get("status") == "NOT_APPLICABLE",
        "evidence_unavailable": lambda row: (row.get("margin") or {}).get("status") == "UNAVAILABLE",
    }
    selected = [row for row in rows if predicates.get(category, predicates["has_margin"])(row)]
    selected.sort(key=lambda row: ((row.get("quality") or {}).get("annual_score") or -1, row.get("stock_name") or ""), reverse=True)
    compact = [{"market": r.get("market"), "symbol": r.get("symbol"), "stock_name": r.get("stock_name"), "industry": r.get("industry_level_2_name"), "quadrant": (r.get("quadrant") or {}).get("quadrant"), "quality_status": (r.get("quality") or {}).get("status"), "annual_score": (r.get("quality") or {}).get("annual_score"), "margin_status": (r.get("margin") or {}).get("status"), "industry_pe_percentile": (r.get("industry") or {}).get("pe_percentile"), "industry_ps_percentile": (r.get("industry") or {}).get("ps_percentile"), "history_pe_percentile": (r.get("own_history") or {}).get("pe_percentile"), "history_ps_percentile": (r.get("own_history") or {}).get("ps_percentile"), "quarterly_momentum": (r.get("quarterly_momentum") or {}).get("status")} for r in selected]
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    total = len(compact)
    start = (page - 1) * page_size
    return {"ok": bool(payload), "built_at": payload.get("built_at"), "summary": payload.get("summary"), "category": category, "page": page, "page_size": page_size, "total": total, "rows": compact[start:start + page_size]}


@lru_cache(maxsize=1)
def _strict_snapshot() -> dict[str, Any]:
    return json.loads(STRICT_SNAPSHOT.read_text(encoding="utf-8")) if STRICT_SNAPSHOT.is_file() else {}


@lru_cache(maxsize=1)
def _period_frames() -> dict[str, Any]:
    return {
        path.stem: pd.read_parquet(path)
        for path in FINANCIAL_TS_DIR.glob("*.parquet")
        if len(path.stem) in {5, 6} and path.stem[:4].isdigit() and path.stem[4:] in {"Q1", "Q2", "Q3", "A"}
    }


def build_current_diagnosis(market: str, symbol: str) -> dict[str, Any]:
    """Build a current diagnosis only from snapshot-date evidence.

    Historical requested dates are deliberately not accepted here: their
    industry valuation and annual quality snapshots require a separately
    materialized PIT snapshot, rather than current data backfilled to a date.
    """
    market, symbol = str(market).lower().strip(), str(symbol).zfill(6)
    record = (_strict_snapshot().get("stocks") or {}).get(f"{market}:{symbol}")
    if not isinstance(record, dict):
        return {"ok": False, "status": "UNAVAILABLE", "reasons": ["strict_financial_snapshot_record_missing"]}
    quality = record.get("good_stock_quality") or {}
    industry_name = None
    # The valuation loader owns the membership mapping and enforces its snapshot date.
    from app.relative_valuation.data_loader import load_stock_relative_valuation_inputs
    stock = load_stock_relative_valuation_inputs(market, symbol) or {}
    industry_name = stock.get("industry_level_2_name")
    industry_snapshot = load_industry_valuation_snapshot(str(industry_name or "")) or {}
    industry = evaluate_industry_evidence(market=market, symbol=symbol, industry_snapshot=industry_snapshot)
    as_of_date = str(industry_snapshot.get("trading_day") or "")
    if not as_of_date:
        return {"ok": False, "status": "UNAVAILABLE", "quality": quality, "industry": industry, "reasons": ["industry_snapshot_date_missing"]}
    dates, closes = _load_daily_series(market, symbol)
    disclosures = build_pit_disclosures_from_period_frames(period_frames=_period_frames(), symbol=symbol, as_of_date=as_of_date)
    own_history = summarize_own_valuation_history(build_own_valuation_history(
        bars=[{"trading_day": day, "close": close} for day, close in zip(dates, closes)],
        disclosures=disclosures, as_of_date=as_of_date,
    ))
    margin = evaluate_margin_evidence(quality=quality, industry=industry, history=own_history)
    quadrant = classify_quality_margin_quadrant(quality, margin)
    return {
        "ok": True, "schema_version": "good-stock-undervaluation-current-v1",
        "market": market, "symbol": symbol, "stock_name": stock.get("stock_name"),
        "as_of_date": as_of_date, "industry_level_2_name": industry_name,
        "quality": quality, "industry": industry, "own_history": own_history,
        "margin": margin, "quadrant": quadrant, "quarterly_momentum": record.get("quarterly_momentum"),
        "pit_scope": "current_snapshot_only",
    }
