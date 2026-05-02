from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ViewResult:
    view_name: str
    low: float | None
    mid: float | None
    high: float | None
    is_valid: bool
    reliability: float | None = None
    method_fitness: float | None = None
    drivers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ValuationResult:
    market: str
    symbol: str
    stock_name: str
    version: str
    valuation_date: str
    latest_report_date: str | None = None
    output_level: str = 'not_estimable'
    dominant_view: str | None = None
    final_low: float | None = None
    final_mid: float | None = None
    final_high: float | None = None
    current_price: float | None = None
    upside_mid_pct: float | None = None
    margin_of_safety_pct: float | None = None
    valuation_template_id: str | None = None
    methodology_note: str | None = None
    views: list[ViewResult] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)
    failure_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload['views'] = [view.to_dict() for view in self.views]
        return payload
