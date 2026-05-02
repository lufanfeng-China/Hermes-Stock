from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValuationContext:
    market: str
    symbol: str
    stock_name: str
    valuation_template_id: str
    industry_level_1_name: str
    industry_level_2_name: str
    valuation_date: str
    latest_report_date: str | None
    current_price: float | None
    market_cap: float | None
    dynamic_pe: float | None
    short_history: bool
    structural_break_date: str | None
    rate_regime: str
