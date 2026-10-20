"""Read-only industry financial-health peer responses from the published snapshot."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The builder atomically replaces this pointer only after the complete versioned
# all-market snapshot has been written.  Do not infer a dated filename here.
CURRENT_SNAPSHOT = PROJECT_ROOT / "data" / "derived" / "datasets" / "final" / "financial_health_peer_snapshot_current.json"
DEFAULT_SNAPSHOT = CURRENT_SNAPSHOT
DIMENSIONS = ("growth_quality", "profitability", "cash_quality", "working_capital", "reinvestment", "financial_risk")
DIMENSION_SOURCE_KEYS = {"growth_quality": ("growth_quality", "growth"), "cash_quality": ("cash_quality", "cash")}


def _view(record: dict[str, Any], kind: str) -> dict[str, Any]:
    source = record.get(kind) or {}
    dimensions = source.get("dimensions") or {}
    periods = list(source.get("periods") or [])
    return {
        "score": source.get("score"),
        "periods": periods if kind == "annual" else None,
        "period": source.get("period") if kind in {"quarterly", "latest_available_quarterly"} else None,
        "reference_only": kind == "latest_available_quarterly",
        "assessment_track": source.get("assessment_track") if kind == "annual" else None,
        "sample_years": len(periods) if kind == "annual" else 0,
        "coverage_weight": source.get("coverage_weight") or 0,
        "status": source.get("score_coverage_status") or ("available" if source.get("score") is not None else "unavailable"),
        "reason": source.get("reason"),
        "dimensions": {key: next((dimensions.get(source_key) for source_key in DIMENSION_SOURCE_KEYS.get(key, (key,)) if dimensions.get(source_key) is not None), None) for key in DIMENSIONS},
    }


def build_industry_health_peer_response(market: str, symbol: str, *, snapshot_path: Path = DEFAULT_SNAPSHOT, industry_map: dict | None = None, names: dict | None = None) -> dict[str, Any]:
    if industry_map is None or names is None:
        from app.search import index as search_index
        industry_map = industry_map or search_index._load_industry_map()
        names = names or search_index._stock_name_lookup()
    key = (market, symbol)
    industry_level_2, industry_level_1 = industry_map.get(key, (None, None))
    if not industry_level_2:
        return {"ok": False, "market": market, "symbol": symbol, "industry_level_1": industry_level_1, "industry_level_2": None, "rows": [], "reason": "industry_classification_unavailable"}
    with Path(snapshot_path).open(encoding="utf-8") as handle:
        stocks = (json.load(handle).get("stocks") or {})
    rows = []
    for (peer_market, peer_symbol), (peer_l2, _peer_l1) in sorted(industry_map.items()):
        if peer_l2 != industry_level_2 or str(peer_market).lower() in {"bj", "2"}:
            continue
        record = stocks.get(f"{peer_market}:{peer_symbol}") or {}
        rows.append({"market": peer_market, "symbol": peer_symbol, "stock_name": names.get((peer_market, peer_symbol), peer_symbol), "is_current_stock": (peer_market, peer_symbol) == key, "annual": _view(record, "annual"), "quarterly": _view(record, "quarterly"), "latest_available_quarterly": _view(record, "latest_available_quarterly")})
    return {"ok": True, "market": market, "symbol": symbol, "industry_level_1": industry_level_1, "industry_level_2": industry_level_2, "rows": rows}
