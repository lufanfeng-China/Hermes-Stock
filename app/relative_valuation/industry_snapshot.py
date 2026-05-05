from __future__ import annotations

from .labels import classify_temperature_label
from .percentiles import compute_empirical_percentile


def build_industry_day_snapshot(
    *,
    trading_day: str,
    industry_level_1_name: str,
    industry_level_2_code: str,
    industry_level_2_name: str,
    members: list[dict[str, object]],
    historical_weighted_pe_series: list[float] | tuple[float, ...],
    minimum_valid_member_count: int = 10,
    dynamic_threshold_multiplier: float = 5.0,
    dynamic_threshold_floor: float = 50.0,
    dynamic_threshold_cap: float = 200.0,
) -> dict[str, object]:
    valid_members: list[dict[str, object]] = []
    loss_count = 0
    invalid_book_value_count = 0
    new_listing_filtered_count = 0
    suspended_filtered_count = 0

    for member in members:
        if bool(member.get("is_suspended")):
            suspended_filtered_count += 1
            continue
        listed_days = _to_float(member.get("listed_days"))
        if listed_days is not None and listed_days < 60:
            new_listing_filtered_count += 1
            continue
        book_value_per_share = _to_float(member.get("book_value_per_share"))
        if book_value_per_share is None or book_value_per_share <= 0:
            invalid_book_value_count += 1
            continue
        ttm_net_profit = _to_float(member.get("ttm_net_profit"))
        if ttm_net_profit is None or ttm_net_profit <= 0:
            loss_count += 1
            continue
        valid_members.append(member)

    weighted_pe_ttm = _compute_weighted_ratio(valid_members, numerator_key="total_market_cap", denominator_key="ttm_net_profit")
    weighted_ps_ttm = _compute_weighted_ratio(valid_members, numerator_key="total_market_cap", denominator_key="ttm_revenue")
    free_float_weighted_pe_ttm = _compute_weighted_ratio(valid_members, numerator_key="free_float_market_cap", denominator_key="ttm_net_profit")
    free_float_weighted_ps_ttm = _compute_weighted_ratio(valid_members, numerator_key="free_float_market_cap", denominator_key="ttm_revenue")
    if weighted_pe_ttm is None:
        weighted_pe_ttm = free_float_weighted_pe_ttm
    if weighted_ps_ttm is None:
        weighted_ps_ttm = free_float_weighted_ps_ttm
    pe_invalid_threshold = None
    if weighted_pe_ttm is not None:
        pe_invalid_threshold = weighted_pe_ttm * dynamic_threshold_multiplier
        pe_invalid_threshold = max(pe_invalid_threshold, dynamic_threshold_floor)
        pe_invalid_threshold = min(pe_invalid_threshold, dynamic_threshold_cap)

    temperature_percentile_since_2022 = None
    temperature_label = None
    sample_status = "ok"
    if len(valid_members) < minimum_valid_member_count:
        sample_status = "insufficient"
    elif weighted_pe_ttm is not None:
        temperature_percentile_since_2022 = compute_empirical_percentile(weighted_pe_ttm, list(historical_weighted_pe_series))
        temperature_label = classify_temperature_label(temperature_percentile_since_2022)

    return {
        "trading_day": trading_day,
        "industry_level_1_name": industry_level_1_name,
        "industry_level_2_code": industry_level_2_code,
        "industry_level_2_name": industry_level_2_name,
        "total_member_count": len(members),
        "valid_member_count": len(valid_members),
        "loss_count": loss_count,
        "invalid_book_value_count": invalid_book_value_count,
        "new_listing_filtered_count": new_listing_filtered_count,
        "suspended_filtered_count": suspended_filtered_count,
        "weighted_pe_ttm": weighted_pe_ttm,
        "weighted_ps_ttm": weighted_ps_ttm,
        "free_float_weighted_pe_ttm": free_float_weighted_pe_ttm,
        "free_float_weighted_ps_ttm": free_float_weighted_ps_ttm,
        "pe_invalid_threshold": pe_invalid_threshold,
        "temperature_percentile_since_2022": temperature_percentile_since_2022,
        "temperature_label": temperature_label,
        "sample_status": sample_status,
    }


def _compute_weighted_ratio(
    members: list[dict[str, object]],
    *,
    numerator_key: str,
    denominator_key: str,
) -> float | None:
    numerator_sum = 0.0
    denominator_sum = 0.0
    for member in members:
        numerator = _to_float(member.get(numerator_key))
        denominator = _to_float(member.get(denominator_key))
        if numerator is None or denominator is None or denominator <= 0:
            continue
        numerator_sum += numerator
        denominator_sum += denominator
    if denominator_sum <= 0:
        return None
    return numerator_sum / denominator_sum


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
