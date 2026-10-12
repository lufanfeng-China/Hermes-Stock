"""Auditable same-period financial position within a Shenwan level-2 industry."""
from __future__ import annotations
from statistics import median
from typing import Any

METRICS = {
    "net_margin": {"label": "净利率", "unit": "%", "field": "net_margin", "higher_better": True},
    "ocf_to_profit": {"label": "现金利润比", "unit": "倍", "field": "ocf_to_profit", "higher_better": True},
    "debt_ratio": {"label": "资产负债率", "unit": "%", "field": "debt_ratio", "higher_better": False},
    "ar_days": {"label": "应收账款周转天数", "unit": "天", "field": "ar_days", "higher_better": False},
    "inv_days": {"label": "存货周转天数", "unit": "天", "field": "inv_days", "higher_better": False},
}

def _number(value: object) -> float | None:
    try: parsed = float(value)
    except (TypeError, ValueError): return None
    return parsed if parsed == parsed else None

def build_industry_financial_position(market: str, symbol: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compare one stock only with peers on exactly the same snapshot period."""
    scores = snapshot.get("scores") or {}
    selected = scores.get(f"{str(market).lower()}:{str(symbol).zfill(6)}")
    if not isinstance(selected, dict): return {"status": "unavailable", "reason": "stock_not_in_financial_snapshot"}
    industry, period, report_date = (str(selected.get(k) or "").strip() for k in ("industry_sw_level_2", "latest_period", "report_date"))
    if not industry or not period: return {"status": "unavailable", "reason": "industry_or_period_unavailable"}
    members = [v for v in scores.values() if isinstance(v, dict) and str(v.get("industry_sw_level_2") or "").strip() == industry]
    aligned = [v for v in members if str(v.get("latest_period") or "") == period and str(v.get("report_date") or "") == report_date]
    raw = selected.get("raw_sub_indicators") or {}; metrics = {}
    for code, d in METRICS.items():
        company = _number(raw.get(d["field"])); values = sorted(v for peer in aligned for v in [_number((peer.get("raw_sub_indicators") or {}).get(d["field"]))] if v is not None)
        if company is None or not values:
            metrics[code] = {"label": d["label"], "unit": d["unit"], "company_value": company, "industry_median": None, "percentile": None, "sample_count": len(values), "higher_better": d["higher_better"], "status": "unavailable"}; continue
        rank = sum(v <= company for v in values) / len(values) * 100
        percentile = rank if d["higher_better"] else 100 - rank + 100 / len(values)
        metrics[code] = {"label": d["label"], "unit": d["unit"], "company_value": company, "industry_median": float(median(values)), "percentile": round(percentile, 1), "sample_count": len(values), "higher_better": d["higher_better"], "status": "available"}
    member_count = len(members)
    return {"status": "available", "industry_level_2": industry, "report_period": period, "report_date": report_date, "industry_member_count": member_count, "aligned_sample_count": len(aligned), "period_alignment_coverage": round(len(aligned) / member_count * 100, 1) if member_count else 0.0, "metrics": metrics}
