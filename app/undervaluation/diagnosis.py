"""Final classification for the good-stock + valuation-margin diagnostic."""
from __future__ import annotations

from typing import Any


def classify_quality_margin_quadrant(quality: dict[str, Any] | None, margin: dict[str, Any] | None) -> dict[str, Any]:
    quality, margin = quality or {}, margin or {}
    quality_eligible = quality.get("status") == "QUALITY_ELIGIBLE" and bool(quality.get("eligible"))
    margin_status = str(margin.get("status") or "UNAVAILABLE")
    if margin_status not in {"HAS_MARGIN", "NO_MARGIN"}:
        return {
            "quadrant": "VALUATION_UNAVAILABLE",
            "complete": False,
            "quality_status": quality.get("status"),
            "margin_status": margin_status,
            "reason": "dual_valuation_evidence_not_available",
        }
    return {
        "quadrant": f"{'QUALITY_ELIGIBLE' if quality_eligible else 'NOT_QUALITY_ELIGIBLE'}_{margin_status}",
        "complete": True,
        "quality_status": quality.get("status"),
        "margin_status": margin_status,
    }
