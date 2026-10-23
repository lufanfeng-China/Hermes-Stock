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
from .price_evidence import summarize_price_percentile
from .own_valuation_history import (
    build_own_valuation_history,
    build_pit_disclosures_from_period_frames,
    summarize_own_valuation_history,
)
from .valuation_gate import evaluate_margin_evidence

ROOT = Path(__file__).resolve().parents[2]
STRICT_SNAPSHOT = ROOT / "data" / "derived" / "datasets" / "final" / "strict_financial_health_snapshot_2025A__2026Q2.json"
CURRENT_DIAGNOSIS_SNAPSHOT = ROOT / "data" / "derived" / "datasets" / "final" / "good_stock_undervaluation_current.json"
PRICE_PERCENTILE_SNAPSHOT = ROOT / "data" / "derived" / "datasets" / "final" / "dataset_price_percentile_5y.json"


@lru_cache(maxsize=1)
def _load_price_percentile_records() -> dict[str, dict[str, Any]]:
    """Load the QFQ precomputed price-position snapshot keyed by stock code."""
    if not PRICE_PERCENTILE_SNAPSHOT.is_file():
        return {}
    return json.loads(PRICE_PERCENTILE_SNAPSHOT.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _current_diagnosis_snapshot() -> dict[str, Any]:
    return json.loads(CURRENT_DIAGNOSIS_SNAPSHOT.read_text(encoding="utf-8")) if CURRENT_DIAGNOSIS_SNAPSHOT.is_file() else {}


def load_current_diagnosis_list(category: str = "has_margin", page: int = 1, page_size: int = 50, filters: dict[str, Any] | None = None) -> dict[str, Any]:
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
    filters = filters or {}
    industry_query = str(filters.get("industry") or "").strip()
    momentum = str(filters.get("momentum") or "").strip()
    def number(value: Any) -> float | None:
        try: return float(value)
        except (TypeError, ValueError): return None
    def passes(row: dict[str, Any]) -> bool:
        quality, industry, history, quarter = row.get("quality") or {}, row.get("industry") or {}, row.get("own_history") or {}, row.get("quarterly_momentum") or {}
        if industry_query and industry_query not in str(row.get("industry_level_2_name") or ""): return False
        if momentum and quarter.get("status") != momentum: return False
        checks = (("min_annual_score", quality.get("annual_score"), lambda actual, required: actual >= required), ("max_industry_pe", industry.get("pe_percentile"), lambda actual, maximum: actual <= maximum), ("max_industry_ps", industry.get("ps_percentile"), lambda actual, maximum: actual <= maximum), ("max_history_pe", history.get("pe_percentile"), lambda actual, maximum: actual <= maximum), ("max_history_ps", history.get("ps_percentile"), lambda actual, maximum: actual <= maximum))
        for key, value, compare in checks:
            threshold = number(filters.get(key))
            actual = number(value)
            if threshold is not None and (actual is None or not compare(actual, threshold)): return False
        return True
    selected = [row for row in selected if passes(row)]
    selected.sort(key=lambda row: ((row.get("quality") or {}).get("annual_score") or -1, row.get("stock_name") or ""), reverse=True)
    price_records = _load_price_percentile_records()
    compact = []
    for record in selected:
        price = summarize_price_percentile(price_records.get(str(record.get("symbol") or "").zfill(6)))
        compact.append({
            "market": record.get("market"), "symbol": record.get("symbol"), "stock_name": record.get("stock_name"),
            "industry": record.get("industry_level_2_name"), "quadrant": (record.get("quadrant") or {}).get("quadrant"),
            "quality_status": (record.get("quality") or {}).get("status"),
            "annual_score": (record.get("quality") or {}).get("annual_score"),
            "margin_status": (record.get("margin") or {}).get("status"),
            "industry_pe_percentile": (record.get("industry") or {}).get("pe_percentile"),
            "industry_ps_percentile": (record.get("industry") or {}).get("ps_percentile"),
            "history_pe_percentile": (record.get("own_history") or {}).get("pe_percentile"),
            "history_ps_percentile": (record.get("own_history") or {}).get("ps_percentile"),
            "quarterly_momentum": (record.get("quarterly_momentum") or {}).get("status"),
            "quarterly_period": (record.get("quarterly_momentum") or {}).get("period"),
            "price_percentile": price["percentile"], "price_percentile_label": price["label"],
            "price_percentile_scope": price["scope"], "price_history_years": price["history_years"],
            "price_percentile_basis": price["basis"],
        })
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
