"""Latest-cumulative-quarter operating momentum, separate from annual quality."""
from __future__ import annotations

from typing import Any
from math import isfinite


def _number(value: Any) -> float | None:
    try:
        value = float(value) if value is not None else None
        return value if value is not None and isfinite(value) else None
    except (TypeError, ValueError):
        return None


def evaluate_quarterly_momentum(monitor: dict[str, Any] | None) -> dict[str, Any]:
    """Return D9 momentum without altering the annual quality decision."""
    monitor = monitor or {}
    period = monitor.get("latest_period")
    if monitor.get("status") != "available":
        return {
            "version": "good-stock-quarterly-momentum-v2-profit-direction",
            "status": "UNAVAILABLE",
            "improving": False,
            "period": period,
            "reasons": [str(monitor.get("reason") or "quarterly_monitor_unavailable")],
            "evidence": {"profit_change": (monitor.get("profit_comparisons") or {}).get("ex_net_profit") or {}},
        }

    yoy = monitor.get("yoy") or {}
    revenue_yoy = _number(yoy.get("revenue"))
    profit_yoy = _number(yoy.get("ex_net_profit"))
    profit_change = (monitor.get("profit_comparisons") or {}).get("ex_net_profit")
    profit_change = profit_change if isinstance(profit_change, dict) else {}
    current = _number(profit_change.get("current"))
    previous = _number(profit_change.get("previous"))
    profit_available = current is not None and previous is not None and profit_change.get("direction") in {"improving", "deteriorating", "flat"}
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
    if not profit_available:
        reasons.append("ex_net_profit_comparison_unavailable")
    elif current <= previous or profit_change.get("direction") != "improving":
        reasons.append("ex_net_profit_yoy_not_positive")
    if not profitability_available or profitability_status not in {"stable", "improving", "watch"}:
        reasons.append("profitability_status_unavailable")
    elif profitability_status not in {"stable", "improving"}:
        reasons.append("profitability_not_stable_or_improving")

    unavailable = revenue_yoy is None or not profit_available or not profitability_available or profitability_status not in {"stable", "improving", "watch"}
    improving = not reasons
    return {
        "version": "good-stock-quarterly-momentum-v2-profit-direction",
        "status": "UNAVAILABLE" if unavailable else "IMPROVING" if improving else "NOT_IMPROVING",
        "improving": improving,
        "period": period,
        "reasons": reasons,
        "evidence": {
            "profit_change": profit_change,
            "revenue_yoy": revenue_yoy,
            "ex_net_profit_yoy": profit_yoy,
            "profitability_status": profitability_status,
            "profitability_available": profitability_available,
        },
    }
