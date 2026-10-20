"""Choose one comparable annual/quarterly anchor set for health peer snapshots."""
from __future__ import annotations


def _order(period: str) -> tuple[int, int]:
    return int(period[:4]), 4 if period.endswith("A") else int(period[-1])


def select_health_snapshot_periods(periods: list[str]) -> dict[str, object]:
    labels = {str(item) for item in periods if len(str(item)) >= 5 and str(item)[:4].isdigit()}
    annuals = sorted((item for item in labels if item.endswith("A")), key=_order)
    quarters = sorted((item for item in labels if "Q" in item), key=_order)
    if len(annuals) < 5 or not quarters:
        raise ValueError("five annual periods and one quarterly period are required")
    annual_anchor = annuals[-1]
    quarterly_anchor = quarters[-1]
    comparable_prior = f"{int(quarterly_anchor[:4]) - 1}{quarterly_anchor[4:]}"
    if comparable_prior not in labels:
        raise ValueError(f"missing comparable prior quarter: {comparable_prior}")
    return {"annual_anchor": annual_anchor, "quarterly_anchor": quarterly_anchor,
            "periods": annuals[-5:] + [comparable_prior, quarterly_anchor]}
