from __future__ import annotations

from .models import ViewResult


def compute_view_weights(views: list[ViewResult], score_context: dict[str, object], template_id: str | None) -> dict[str, float]:
    valid = [view for view in views if view.is_valid]
    if not valid:
        return {view.view_name: 0.0 for view in views}
    if len(valid) == 1:
        return {view.view_name: (1.0 if view.is_valid else 0.0) for view in views}

    base = 1.0 / len(valid)
    weights = {view.view_name: (base if view.is_valid else 0.0) for view in views}

    try:
        ocf_to_profit = float(score_context.get('ocf_to_profit')) if score_context.get('ocf_to_profit') is not None else None
    except (TypeError, ValueError):
        ocf_to_profit = None
    try:
        revenue_growth = float(score_context.get('revenue_growth')) if score_context.get('revenue_growth') is not None else None
    except (TypeError, ValueError):
        revenue_growth = None
    try:
        debt_ratio = float(score_context.get('debt_ratio')) if score_context.get('debt_ratio') is not None else None
    except (TypeError, ValueError):
        debt_ratio = None

    if ocf_to_profit is not None and ocf_to_profit >= 1.0 and 'earnings' in weights:
        weights['earnings'] += 0.10
    if revenue_growth is not None and revenue_growth >= 15.0 and 'revenue' in weights:
        weights['revenue'] += 0.10
    if debt_ratio is not None and debt_ratio >= 60.0 and 'asset' in weights:
        weights['asset'] -= 0.10
    if template_id in {'bank', 'nonbank_finance'} and 'asset' in weights:
        weights['asset'] += 0.10
    if template_id == 'premium_liquor':
        weights['earnings'] += 0.28
        weights['asset'] += 0.12
        weights['revenue'] -= 0.20
    if template_id == 'white_appliance':
        weights['earnings'] += 0.12
        weights['asset'] += 0.16
        weights['revenue'] -= 0.18
    if template_id == 'power_battery':
        weights['earnings'] += 0.14
        weights['revenue'] += 0.14
        weights['asset'] -= 0.16
    if template_id == 'electric_utility':
        weights['earnings'] += 0.18
        weights['asset'] += 0.08
        weights['revenue'] -= 0.22
    if template_id == 'gas_utility':
        weights['earnings'] += 0.16
        weights['asset'] += 0.14
        weights['revenue'] -= 0.24
    if template_id == 'environmental_services':
        weights['earnings'] -= 0.30
        weights['asset'] += 0.22
        weights['revenue'] += 0.08
    if template_id == 'environmental_equipment':
        weights['earnings'] -= 0.18
        weights['asset'] += 0.16
        weights['revenue'] += 0.12
    if template_id == 'rail_transit_equipment':
        weights['earnings'] += 0.08
        weights['asset'] += 0.06
        weights['revenue'] -= 0.14
    if template_id == 'highway_rail_operator':
        weights['asset'] += 0.08
        weights['revenue'] -= 0.12
    if template_id == 'industrial_metal':
        weights['earnings'] += 0.16
        weights['asset'] += 0.06
        weights['revenue'] -= 0.12
    if template_id == 'medical_device':
        weights['earnings'] -= 0.18
        weights['asset'] += 0.08
        weights['revenue'] += 0.10
    if template_id == 'military_info_system':
        weights['asset'] += 0.50
        weights['revenue'] -= 0.20
    if template_id == 'display_panel':
        weights['asset'] += 0.22
        weights['revenue'] -= 0.18
    if template_id == 'motor_control_components':
        weights['earnings'] += 0.08
        weights['asset'] -= 0.16
        weights['revenue'] += 0.12
    if template_id == 'consumer_assembly':
        weights['earnings'] += 0.10
        weights['asset'] += 0.08
        weights['revenue'] -= 0.18
    if template_id == 'aerospace_material':
        weights['earnings'] += 0.08
        weights['asset'] += 0.12
        weights['revenue'] -= 0.20
    if template_id == 'high_temp_alloy':
        weights['earnings'] += 0.18
        weights['asset'] += 0.10
        weights['revenue'] -= 0.22
    if template_id == 'property_development':
        weights['asset'] += 0.20
        weights['revenue'] -= 0.12
    if template_id == 'testing_inspection_service':
        weights['earnings'] += 0.12
        weights['asset'] += 0.08
        weights['revenue'] -= 0.12
    if template_id == 'tourism_services':
        weights['earnings'] += 0.04
        weights['asset'] += 0.08
        weights['revenue'] -= 0.12
    if template_id == 'education_training':
        weights['earnings'] -= 0.14
        weights['asset'] += 0.12
        weights['revenue'] += 0.04
    if template_id == 'leisure_culture_goods':
        weights['earnings'] -= 0.12
        weights['asset'] += 0.06
        weights['revenue'] += 0.06
    if template_id == 'human_resource_service':
        weights['earnings'] += 0.08
        weights['asset'] += 0.04
        weights['revenue'] -= 0.10
    if template_id == 'port_operator':
        weights['earnings'] += 0.06
        weights['asset'] += 0.10
        weights['revenue'] -= 0.10
    if template_id == 'textile_quality_manufacturing':
        weights['earnings'] += 0.06
        weights['asset'] += 0.06
        weights['revenue'] -= 0.10
    if template_id == 'appliance_precision_components':
        weights['earnings'] += 0.10
        weights['asset'] += 0.08
        weights['revenue'] -= 0.12
    if template_id == 'kitchen_appliance_brand':
        weights['earnings'] += 0.08
        weights['asset'] -= 0.14
        weights['revenue'] += 0.10
    if template_id == 'coal_mining':
        weights['asset'] += 0.08
        weights['revenue'] -= 0.12
    if template_id == 'film_cinema':
        weights['earnings'] -= 0.08
        weights['asset'] += 0.04
        weights['revenue'] += 0.04
    if template_id == 'snack_food':
        weights['asset'] += 0.06
        weights['revenue'] -= 0.06
    if template_id == 'condiment':
        weights['earnings'] += 0.04
        weights['asset'] -= 0.08
        weights['revenue'] += 0.04
    if template_id == 'premium_game':
        weights['earnings'] += 0.16
        weights['asset'] -= 0.06
        weights['revenue'] -= 0.10
    if template_id == 'steel_standard':
        weights['earnings'] += 0.08
        weights['asset'] += 0.10
        weights['revenue'] -= 0.12
    if template_id == 'interior_decoration':
        weights['earnings'] -= 0.12
        weights['asset'] += 0.08
        weights['revenue'] += 0.06
    if template_id == 'cement_materials':
        weights['earnings'] += 0.08
        weights['asset'] += 0.06
        weights['revenue'] -= 0.14
    if template_id == 'rubber_materials':
        weights['earnings'] -= 0.16
        weights['asset'] += 0.06
        weights['revenue'] += 0.08
    if template_id == 'daily_chemical':
        weights['earnings'] += 0.06
        weights['asset'] -= 0.08
        weights['revenue'] += 0.02
    if template_id == 'trade_distribution':
        weights['earnings'] -= 0.12
        weights['asset'] += 0.08
        weights['revenue'] += 0.04
    if template_id == 'commodity_trading':
        weights['earnings'] -= 0.10
        weights['asset'] += 0.06
        weights['revenue'] += 0.04
    if template_id == 'export_supply_chain':
        weights['earnings'] += 0.08
        weights['asset'] += 0.06
        weights['revenue'] -= 0.10
    if template_id == 'livestock_breeding':
        weights['earnings'] -= 0.12
        weights['asset'] += 0.06
        weights['revenue'] += 0.06
    if template_id == 'hog_breeding':
        weights['earnings'] -= 0.12
        weights['asset'] += 0.06
        weights['revenue'] += 0.06
    if template_id == 'feed_processing':
        weights['earnings'] += 0.08
        weights['asset'] += 0.06
        weights['revenue'] -= 0.10
    if template_id == 'ecommerce_service':
        weights['earnings'] += 0.08
        weights['asset'] += 0.12
        weights['revenue'] -= 0.22
    if template_id == 'seed_planting':
        weights['earnings'] -= 0.16
        weights['asset'] += 0.10
        weights['revenue'] += 0.08
    if template_id == 'film_content_production':
        weights['earnings'] -= 0.12
        weights['asset'] += 0.06
        weights['revenue'] += 0.06
    if template_id == 'distressed_education':
        weights['earnings'] -= 0.26
        weights['asset'] += 0.16
        weights['revenue'] += 0.10

    for key, value in list(weights.items()):
        if value < 0:
            weights[key] = 0.0
    total = sum(weights.values()) or 1.0
    return {key: value / total for key, value in weights.items()}


def pick_dominant_view(weights: dict[str, float]) -> str | None:
    positive = {k: v for k, v in weights.items() if v > 0}
    if not positive:
        return None
    return max(positive, key=positive.get)


def blend_view_results(views: list[ViewResult], weights: dict[str, float]) -> dict[str, float | None]:
    valid = [view for view in views if view.is_valid and weights.get(view.view_name, 0.0) > 0]
    if not valid:
        return {'low': None, 'mid': None, 'high': None}
    if len(valid) == 1:
        view = valid[0]
        return {'low': view.low, 'mid': view.mid, 'high': view.high}
    low = sum((view.low or 0.0) * weights.get(view.view_name, 0.0) for view in valid)
    mid = sum((view.mid or 0.0) * weights.get(view.view_name, 0.0) for view in valid)
    high = sum((view.high or 0.0) * weights.get(view.view_name, 0.0) for view in valid)
    return {'low': low, 'mid': mid, 'high': high}


def compute_output_level(views: list[ViewResult], short_history: bool, structural_break: bool) -> str:
    valid_count = sum(1 for view in views if view.is_valid)
    if valid_count == 0:
        return 'not_estimable'
    if valid_count == 1:
        return 'cautious_reference'
    if short_history or structural_break:
        return 'highly_cautious'
    return 'standard'
