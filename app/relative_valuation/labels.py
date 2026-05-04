from __future__ import annotations

from enum import StrEnum


class Classification(StrEnum):
    A_NORMAL_EARNING = "A_NORMAL_EARNING"
    B_THIN_PROFIT_DISTORTED = "B_THIN_PROFIT_DISTORTED"
    C_LOSS = "C_LOSS"


class LossSubClassification(StrEnum):
    C1_REVENUE_LOSS = "C1_REVENUE_LOSS"
    C2_GROWTH_LOSS = "C2_GROWTH_LOSS"
    C3_NO_REVENUE_CONCEPT = "C3_NO_REVENUE_CONCEPT"
    C4_LIQUIDATION_RISK = "C4_LIQUIDATION_RISK"


def classify_percentile_band(percentile: float | None) -> str | None:
    if percentile is None:
        return None
    if percentile < 20.0:
        return "低估区间"
    if percentile < 40.0:
        return "合理偏低"
    if percentile < 60.0:
        return "合理"
    if percentile < 80.0:
        return "合理偏高"
    return "高估区间"


def classify_temperature_label(percentile: float | None) -> str | None:
    if percentile is None:
        return None
    if percentile < 30.0:
        return "行业偏冷"
    if percentile < 70.0:
        return "行业温和"
    if percentile < 80.0:
        return "行业偏热"
    return "行业过热"
