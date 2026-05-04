from __future__ import annotations

from dataclasses import dataclass

from .labels import Classification, LossSubClassification


@dataclass(frozen=True)
class ClassificationResult:
    classification: Classification
    sub_classification: LossSubClassification | None
    is_new_listing: bool
    eligible_for_percentile: bool


def classify_relative_valuation_stock(
    *,
    ttm_net_profit: float | None,
    pe_ttm: float | None,
    dynamic_pe_invalid_threshold: float | None,
    ttm_revenue: float | None,
    revenue_yoy: float | None,
    gross_margin: float | None,
    book_value_per_share: float | None,
    listed_days: int | None,
) -> ClassificationResult:
    is_new_listing = listed_days is not None and listed_days < 60

    if ttm_net_profit is not None and ttm_net_profit > 0:
        if (
            pe_ttm is not None
            and pe_ttm > 0
            and dynamic_pe_invalid_threshold is not None
            and pe_ttm <= dynamic_pe_invalid_threshold
        ):
            classification = Classification.A_NORMAL_EARNING
        else:
            classification = Classification.B_THIN_PROFIT_DISTORTED
        return ClassificationResult(
            classification=classification,
            sub_classification=None,
            is_new_listing=is_new_listing,
            eligible_for_percentile=not is_new_listing,
        )

    sub_classification = _classify_loss_subtype(
        ttm_revenue=ttm_revenue,
        revenue_yoy=revenue_yoy,
        gross_margin=gross_margin,
        book_value_per_share=book_value_per_share,
    )
    return ClassificationResult(
        classification=Classification.C_LOSS,
        sub_classification=sub_classification,
        is_new_listing=is_new_listing,
        eligible_for_percentile=not is_new_listing,
    )


def _classify_loss_subtype(
    *,
    ttm_revenue: float | None,
    revenue_yoy: float | None,
    gross_margin: float | None,
    book_value_per_share: float | None,
) -> LossSubClassification:
    if book_value_per_share is not None and book_value_per_share <= 0:
        return LossSubClassification.C4_LIQUIDATION_RISK
    if _is_no_revenue_concept(ttm_revenue):
        return LossSubClassification.C3_NO_REVENUE_CONCEPT
    if (
        gross_margin is not None
        and revenue_yoy is not None
        and gross_margin >= 0.10
        and revenue_yoy >= 0.20
    ):
        return LossSubClassification.C2_GROWTH_LOSS
    return LossSubClassification.C1_REVENUE_LOSS


def _is_no_revenue_concept(ttm_revenue: float | None) -> bool:
    if ttm_revenue is None:
        return False
    revenue = float(ttm_revenue)
    if revenue > 10_000:
        return revenue < 1_000_000
    return revenue < 0.01
