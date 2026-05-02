from __future__ import annotations


def build_risk_tags(data: dict[str, object], template_id: str, output_level: str) -> list[str]:
    tags: list[str] = []
    if data.get('short_history'):
        tags.append('short_history')
    if data.get('structural_break_date'):
        tags.append('structural_break')
    try:
        debt_ratio = float(data.get('debt_ratio')) if data.get('debt_ratio') is not None else None
    except (TypeError, ValueError):
        debt_ratio = None
    if debt_ratio is not None and debt_ratio >= 60:
        tags.append('high_leverage')
    try:
        ocf_to_profit = float(data.get('ocf_to_profit')) if data.get('ocf_to_profit') is not None else None
    except (TypeError, ValueError):
        ocf_to_profit = None
    if ocf_to_profit is not None and ocf_to_profit < 1.0:
        tags.append('cashflow_quality_warning')
    if template_id in {'bank', 'nonbank_finance'}:
        tags.append('financial_stock_special_case')
    if output_level == 'cautious_reference':
        tags.append('single_view_reference')
    return tags
