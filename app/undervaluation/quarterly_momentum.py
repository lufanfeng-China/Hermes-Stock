"""Latest-cumulative-quarter operating momentum, separate from annual quality."""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def evaluate_quarterly_momentum(monitor: dict[str, Any] | None) -> dict[str, Any]:
    """Return D9 momentum without altering the annual quality decision."""
    monitor = monitor or {}
    period = monitor.get("latest_period")
    if monitor.get("status") != "available":
        return {
            "version": "good-stock-quarterly-momentum-v1",
            "status": "UNAVAILABLE",
            "improving": False,
            "period": period,
            "reasons": [str(monitor.get("reason") or "quarterly_monitor_unavailable")],
        }

    yoy = monitor.get("yoy") or {}
    revenue_yoy = _number(yoy.get("revenue"))
    profit_yoy = _number(yoy.get("ex_net_profit"))
    profitability = next(
        (item for item in (monitor.get("dimensions") or []) if item.get("code") == "profitability"),
        None,
    )
    profitability_status = profitability.get("status") if isinstance(profitability, dict) else None
    profitability_available = bool(profitability and profitability.get("available"))
    reasons = []
    if revenue_yoy is None:
        reasons.append("revenue_yoy_unavailable")
    elif revenue_yoy <= 0:
        reasons.append("revenue_yoy_not_positive")
    if profit_yoy is None:
        reasons.append("ex_net_profit_yoy_unavailable")
    elif profit_yoy <= 0:
        reasons.append("ex_net_profit_yoy_not_positive")
    if not profitability_available:
        reasons.append("profitability_status_unavailable")
    elif profitability_status not in {"stable", "improving"}:
        reasons.append("profitability_not_stable_or_improving")

    improving = not reasons
    return {
        "version": "good-stock-quarterly-momentum-v1",
        "status": "IMPROVING" if improving else "NOT_IMPROVING",
        "improving": improving,
        "period": period,
        "reasons": reasons,
        "evidence": {
            "revenue_yoy": revenue_yoy,
            "ex_net_profit_yoy": profit_yoy,
            "profitability_status": profitability_status,
            "profitability_available": profitability_available,
        },
    }
