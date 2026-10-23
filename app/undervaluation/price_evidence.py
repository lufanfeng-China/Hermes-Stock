"""Auditable display contract for precomputed QFQ price percentiles."""
from __future__ import annotations

from typing import Any


def summarize_price_percentile(record: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a price-percentile dataset record for all-market list output."""
    if not isinstance(record, dict) or record.get("price_percentile_5y") is None:
        return {
            "percentile": None,
            "label": "—",
            "scope": "unavailable",
            "history_years": None,
            "basis": None,
        }

    history_years = record.get("history_years")
    try:
        history_years = float(history_years) if history_years is not None else None
    except (TypeError, ValueError):
        history_years = None
    scope = str(record.get("history_scope") or "five_year")
    if scope == "available_history" and history_years is not None:
        label = f"历史分位（{history_years:.1f}年）"
    elif scope == "available_history":
        label = "历史分位"
    else:
        scope = "five_year"
        label = "五年分位"

    return {
        "percentile": float(record["price_percentile_5y"]),
        "label": label,
        "scope": scope,
        "history_years": history_years,
        "basis": record.get("price_basis"),
    }
