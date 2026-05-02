from __future__ import annotations

from .config import get_template_defaults, refine_valuation_template_id, resolve_valuation_template_id
from .context import ValuationContext
from .data_loader import load_valuation_inputs
from .failure_conditions import build_failure_conditions
from .models import ValuationResult
from .risk_engine import build_risk_tags
from .views import compute_asset_view, compute_earnings_view, compute_revenue_view
from .weight_engine import blend_view_results, compute_output_level, compute_view_weights, pick_dominant_view


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _pct_delta(current_price: float | None, target: float | None) -> float | None:
    if current_price in (None, 0) or target is None:
        return None
    return round((target - current_price) / current_price * 100.0, 4)


def build_valuation_result(market: str, symbol: str) -> dict[str, object]:
    loaded = load_valuation_inputs(market, symbol)
    template_id = resolve_valuation_template_id(
        loaded.get('valuation_template_id'),
        loaded.get('industry_level_1_name'),
        loaded.get('industry_level_2_name'),
    )
    template_id = refine_valuation_template_id(
        template_id,
        loaded.get('industry_level_2_name'),
        {
            'dynamic_pe': loaded.get('dynamic_pe'),
            'eps': loaded.get('eps'),
            'debt_ratio': loaded.get('debt_ratio'),
            'profit_growth': loaded.get('profit_growth'),
            'revenue_growth': loaded.get('revenue_growth'),
            'revenue_per_share': (
                float(loaded.get('revenue')) / float(loaded.get('total_shares'))
                if loaded.get('revenue') not in (None, 0) and loaded.get('total_shares') not in (None, 0)
                else None
            ),
        },
    )
    loaded['valuation_template_id'] = template_id
    context = ValuationContext(
        market=str(loaded.get('market') or market),
        symbol=str(loaded.get('symbol') or symbol),
        stock_name=str(loaded.get('stock_name') or symbol),
        valuation_template_id=template_id,
        industry_level_1_name=str(loaded.get('industry_level_1_name') or ''),
        industry_level_2_name=str(loaded.get('industry_level_2_name') or ''),
        valuation_date=str(loaded.get('valuation_date') or ''),
        latest_report_date=loaded.get('latest_report_date'),
        current_price=loaded.get('current_price'),
        market_cap=loaded.get('market_cap'),
        dynamic_pe=loaded.get('dynamic_pe'),
        short_history=bool(loaded.get('short_history')),
        structural_break_date=loaded.get('structural_break_date'),
        rate_regime=str(loaded.get('rate_regime') or 'neutral'),
    )
    config = get_template_defaults(template_id)
    views = [
        compute_earnings_view(loaded, context, config),
        compute_asset_view(loaded, context, config),
        compute_revenue_view(loaded, context, config),
    ]
    weights = compute_view_weights(views, loaded, template_id)
    for view in views:
        weight = float(weights.get(view.view_name, 0.0))
        view.reliability = round(weight, 4) if view.is_valid else 0.0
        view.method_fitness = round(weight, 4) if view.is_valid else 0.0
    blended = blend_view_results(views, weights)
    dominant_view = pick_dominant_view(weights)
    output_level = compute_output_level(views, context.short_history, bool(context.structural_break_date))
    methodology_note = f'盈利/资产/收入三视角融合；行业模板={template_id}'
    if sum(1 for view in views if view.is_valid) == 1:
        methodology_note += '；single-view reference'
    risk_tags = build_risk_tags(loaded, template_id, output_level)
    failure_conditions = build_failure_conditions(loaded, template_id)

    result = ValuationResult(
        market=context.market,
        symbol=context.symbol,
        stock_name=context.stock_name,
        version='valuation_v1',
        valuation_date=context.valuation_date,
        latest_report_date=context.latest_report_date,
        output_level=output_level,
        dominant_view=dominant_view,
        final_low=_round_or_none(blended.get('low')),
        final_mid=_round_or_none(blended.get('mid')),
        final_high=_round_or_none(blended.get('high')),
        current_price=_round_or_none(context.current_price),
        upside_mid_pct=_pct_delta(context.current_price, blended.get('mid')),
        margin_of_safety_pct=_pct_delta(context.current_price, blended.get('low')),
        valuation_template_id=template_id,
        methodology_note=methodology_note,
        views=views,
        risk_tags=risk_tags,
        failure_conditions=failure_conditions,
    )
    payload = result.to_dict()
    payload['ok'] = True
    return payload
