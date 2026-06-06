"""Concept analysis API — search concept, list concepts, generate narratives."""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DERIVED_FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"


def _load_tech_eval() -> dict:
    """Load technical evaluation data, keyed by 6-digit symbol."""
    path = DERIVED_FINAL_DIR / "dataset_technical_eval.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("stocks", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_concept_keywords(concept_name: str) -> list[str]:
    """Extract meaningful keywords from a concept name for matching."""
    stripped = concept_name.replace("概念", "").replace("板块", "").replace("产业", "").strip()
    keywords = [stripped]
    if len(stripped) >= 3:
        keywords.append(stripped[:2])
    if len(stripped) >= 4:
        keywords.append(stripped[2:])
    if len(stripped) >= 5:
        keywords.append(stripped[1:3])
    return [k for k in keywords if k]


def _calc_industry_multiplier(concept_name: str, industry_display: str) -> float:
    """Calculate how well the stock's industry aligns with the concept."""
    if not industry_display:
        return 0.4
    industry_parts = [p.strip() for p in industry_display.split("/") if p.strip()]
    keywords = _extract_concept_keywords(concept_name)

    # Level 1: exact keyword in any industry level
    for kw in keywords:
        if len(kw) < 2:
            continue
        for part in industry_parts:
            if kw in part or part in kw:
                return 1.0

    # Level 2: partial overlap — check 2-char substrings
    for kw in keywords:
        if len(kw) < 3:
            continue
        for part in industry_parts:
            for i in range(len(kw) - 1):
                if kw[i:i+2] in part:
                    return 0.65

    return 0.35


def _generate_concept_narrative(
    concept_name: str,
    industry_display: str,
    concept_list: list[str],
    rank: int | None,
    total: int,
) -> str:
    """Generate a detailed narrative explaining why this stock belongs to the concept."""
    if not concept_name:
        return "概念板块归属"

    concept_kw = concept_name.replace("概念", "").replace("板块", "").strip()
    stock_concepts = [c for c in concept_list if c and c != concept_name]

    # Find related concepts from the stock's other concept tags
    keywords = _extract_concept_keywords(concept_name)
    related_concepts = []
    for c in stock_concepts:
        c_stripped = c.replace("概念", "").replace("板块", "").strip()
        for kw in keywords:
            if kw and len(kw) >= 2 and (kw in c_stripped or c_stripped in kw):
                if c not in related_concepts:
                    related_concepts.append(c)
                break

    # Build rank part
    rank_part = ""
    if rank is not None and rank >= 1 and total > 0:
        if rank <= 3:
            rank_part = f"为该股第{['一','二','三'][rank-1]}大核心概念"
        elif rank <= 10:
            rank_part = f"在该股{total}个概念中排第{rank}位"
        else:
            rank_part = f"在该股{total}个概念中位列第{rank}"

    industry_parts = [p.strip() for p in industry_display.split("/") if p.strip()] if industry_display else []
    industry_tail = industry_parts[-1] if industry_parts else ""

    # Industry overlap
    industry_match = None
    for part in industry_parts:
        if concept_kw in part or part in concept_kw:
            industry_match = part
            break

    parts = [concept_name]
    if rank_part:
        parts.append(rank_part)

    if industry_match:
        parts.append(f"主营业务{industry_match}与{concept_name}直接相关")
    elif industry_tail:
        parts.append(f"主营{industry_tail}")

    if related_concepts:
        concepts_str = "、".join(related_concepts[:3])
        if len(related_concepts) > 3:
            concepts_str += "等"
        parts.append(f"同时具备{concepts_str}关联标签")
    else:
        if not industry_match:
            parts.append(f"因业务涉及{concept_kw}领域被纳入")

    return "，".join(parts) + "。"


def handle_concept_analysis(query: str) -> dict[str, Any]:
    """Handle /api/concept-analysis — search concept and return enriched stock list."""
    from urllib.parse import parse_qs

    from app.search.index import (
        _coerce_float,
        _coerce_int,
        _load_financial_snapshot,
        _load_latest_daily_snapshot,
        load_industry_valuation_rows,
        load_rps_rows,
        search_concept_stocks,
    )

    params = {k: v[0] for k, v in parse_qs(query).items() if v}
    q = str(params.get("q", "")).strip()
    if not q:
        return {"ok": False, "error": "q required", "status": HTTPStatus.BAD_REQUEST}

    result = search_concept_stocks(q)
    if not result.get("concept"):
        return {"ok": True, "concept": None, "stocks": [], "method": result.get("method")}

    concept = result["concept"]
    members = concept.get("members", [])

    # Enrich with score/RPS/valuation
    rps_rows = load_rps_rows()
    valuation_rows = load_industry_valuation_rows()
    snapshot = _load_financial_snapshot() or {}
    score_rows = snapshot.get("scores") or {}
    tech_eval_rows = _load_tech_eval()

    rps_lookup = {(str(r.get("market", "")).strip(), str(r.get("symbol", "")).strip()): r for r in rps_rows}
    score_lookup = score_rows if isinstance(score_rows, dict) else {}

    # Pre-compute market_total_rank by sorting all stocks by total_score (descending)
    ranked_scores: list[tuple[float, str]] = []
    for k, s in score_lookup.items():
        ts = _coerce_float(s.get("total_score"))
        if ts is not None:
            ranked_scores.append((ts, k))
    ranked_scores.sort(key=lambda x: (-x[0], x[1]))
    rank_by_key: dict[str, int] = {k: i + 1 for i, (_, k) in enumerate(ranked_scores)}

    # Build PE lookup dict once (O(1) per stock)
    pe_lookup: dict[tuple[str, str], float | None] = {}
    for vrow in valuation_rows:
        for mv in (vrow.get("member_valuation_rows") or []):
            mk = (str(mv.get("market", "")).strip(), str(mv.get("symbol", "")).strip())
            if mk not in pe_lookup:
                pe_lookup[mk] = _coerce_float(mv.get("pe_ttm"))

    enriched = []
    for m in members:
        market = str(m.get("market", "")).strip()
        symbol = str(m.get("symbol", "")).strip()
        key = f"{market}:{symbol}"
        rps = rps_lookup.get((market, symbol), {})
        score = score_lookup.get(key, {}) if isinstance(score_lookup, dict) else {}
        tech = tech_eval_rows.get(symbol, {}) if isinstance(tech_eval_rows, dict) else {}
        pe = pe_lookup.get((market, symbol))

        total_rps = sum(_coerce_float(rps.get(f"rps_{w}")) or 0 for w in (20, 50, 120, 250))

        # Multi-factor match percentage
        rank = m.get("concept_rank_in_stock")
        total = m.get("concept_total_count", 0)
        industry = str(m.get("industry_display", ""))
        concept_name = str(concept.get("concept_name", ""))
        concept_list_data = m.get("concept_list", [])

        # Factor A: prominence (0-100)
        if rank is not None and isinstance(rank, int) and rank >= 1 and total and total >= rank:
            prominence = ((total - rank + 1) / total) * 100
        else:
            prominence = 40

        # Factor B: industry alignment (0-100)
        industry_mult = _calc_industry_multiplier(concept_name, industry)
        industry_score = industry_mult * 100

        # Factor C: related concept density (0-100)
        keywords = _extract_concept_keywords(concept_name)
        stock_concepts = [c for c in concept_list_data if c and c != concept_name]
        rel_count = 0
        for c in stock_concepts:
            c_s = c.replace("概念", "").replace("板块", "").strip()
            for kw in keywords:
                if kw and len(kw) >= 2 and (kw in c_s or c_s in kw):
                    rel_count += 1
                    break
        density_score = min(100, rel_count * 15)

        # Weighted: 20% prominence + 70% industry + 10% density
        match_pct = round(prominence * 0.2 + industry_score * 0.7 + density_score * 0.1)
        match_pct = min(100, max(0, match_pct))

        narrative = _generate_concept_narrative(concept_name, industry, concept_list_data, rank, total)

        # Fetch current price from cached daily snapshot (local, fast)
        daily = _load_latest_daily_snapshot(market, symbol)
        cp = daily.get("latest_close")

        enriched.append({
            "market": market, "symbol": symbol,
            "stock_name": str(m.get("stock_name", symbol)),
            "industry_display": str(m.get("industry_display", "")),
            "current_price": cp,
            "pe_ttm": pe,
            "rps_20": _coerce_float(rps.get("rps_20")),
            "rps_50": _coerce_float(rps.get("rps_50")),
            "rps_120": _coerce_float(rps.get("rps_120")),
            "rps_250": _coerce_float(rps.get("rps_250")),
            "total_rps": round(total_rps, 0),
            "market_total_rank": rank_by_key.get(key),
            "tech_trend_label": tech.get("trend_label"),
            "tech_trend": tech.get("trend"),
            "match_pct": match_pct,
            "narrative": narrative,
        })

    enriched.sort(key=lambda s: s.get("match_pct") or 0, reverse=True)

    return {
        "ok": True,
        "concept_name": concept.get("concept_name"),
        "member_count": concept.get("member_count"),
        "matched": result.get("matched"),
        "method": result.get("method"),
        "stocks": enriched,
    }


def handle_concept_list(query: str, limit: int = 100) -> dict[str, Any]:
    """Handle /api/concept-list — search concept names."""
    from urllib.parse import parse_qs

    from app.search.index import concept_list_response

    params = parse_qs(query)
    search_query = params.get("q", [""])[0].strip()
    user_limit = int(params.get("limit", [str(limit)])[0]) if params.get("limit") else limit
    return concept_list_response(search_query, limit=min(user_limit, 200))


def handle_concept_cross(query: str) -> dict[str, Any]:
    """Handle /api/concept-cross — multi-concept intersection search."""
    from urllib.parse import parse_qs

    from app.search.index import (
        _coerce_float,
        _coerce_int,
        _load_financial_snapshot,
        _load_latest_daily_snapshot,
        load_industry_valuation_rows,
        load_rps_rows,
        search_concept_stocks,
    )

    params = {k: v[0] for k, v in parse_qs(query).items() if v}
    q = str(params.get("q", "")).strip()
    if not q:
        return {"ok": False, "error": "q required", "status": HTTPStatus.BAD_REQUEST}

    # Split comma-separated concepts, trim whitespace
    queries = [c.strip() for c in q.split(",") if c.strip()]
    if len(queries) < 2:
        # Fallback to single-concept analysis
        result = handle_concept_analysis(query)
        result["cross"] = False
        return result

    # Search each concept
    concept_results = []
    concept_names = []
    for cq in queries:
        r = search_concept_stocks(cq)
        if r.get("concept"):
            concept_results.append(r)
            concept_names.append(str(r["concept"].get("concept_name", cq)))

    if not concept_results:
        return {"ok": True, "cross": True, "concepts": [], "stocks": [], "method": "not_found"}

    # Build member key sets for each concept
    member_sets = []
    for r in concept_results:
        members = r["concept"].get("members", [])
        keys = {f"{str(m.get('market','')).strip()}:{str(m.get('symbol','')).strip()}": m for m in members}
        member_sets.append(keys)

    # Intersection: stocks present in ALL concepts
    intersected_keys = set(member_sets[0].keys())
    for ms in member_sets[1:]:
        intersected_keys &= set(ms.keys())

    if not intersected_keys:
        return {
            "ok": True, "cross": True,
            "concepts": [{"name": n, "member_count": len(ms)} for n, ms in zip(concept_names, member_sets)],
            "intersection_count": 0, "stocks": [], "method": "cross",
        }

    # Load enrichment data once
    rps_rows = load_rps_rows()
    valuation_rows = load_industry_valuation_rows()
    snapshot = _load_financial_snapshot() or {}
    score_rows = snapshot.get("scores") or {}
    tech_eval_rows = _load_tech_eval()

    rps_lookup = {(str(r.get("market", "")).strip(), str(r.get("symbol", "")).strip()): r for r in rps_rows}
    score_lookup = score_rows if isinstance(score_rows, dict) else {}

    # Pre-compute market_total_rank
    ranked_scores: list[tuple[float, str]] = []
    for k, s in score_lookup.items():
        ts = _coerce_float(s.get("total_score"))
        if ts is not None:
            ranked_scores.append((ts, k))
    ranked_scores.sort(key=lambda x: (-x[0], x[1]))
    rank_by_key: dict[str, int] = {k: i + 1 for i, (_, k) in enumerate(ranked_scores)}

    pe_lookup: dict[tuple[str, str], float | None] = {}
    for vrow in valuation_rows:
        for mv in (vrow.get("member_valuation_rows") or []):
            mk = (str(mv.get("market", "")).strip(), str(mv.get("symbol", "")).strip())
            if mk not in pe_lookup:
                pe_lookup[mk] = _coerce_float(mv.get("pe_ttm"))

    # Enrich intersection stocks
    enriched = []
    for key in intersected_keys:
        # Take member data from first concept (richest)
        m = member_sets[0].get(key, {})
        if not m:
            continue
        market = str(m.get("market", "")).strip()
        symbol = str(m.get("symbol", "")).strip()
        rps = rps_lookup.get((market, symbol), {})
        score = score_lookup.get(key, {}) if isinstance(score_lookup, dict) else {}
        tech = tech_eval_rows.get(symbol, {}) if isinstance(tech_eval_rows, dict) else {}
        pe = pe_lookup.get((market, symbol))

        total_rps = sum(_coerce_float(rps.get(f"rps_{w}")) or 0 for w in (20, 50, 120, 250))

        # Compute max match_pct across all matched concepts
        industry = str(m.get("industry_display", ""))
        concept_list_data = m.get("concept_list", [])
        best_match = 0
        for ci, c_name in enumerate(concept_names):
            rank_i = member_sets[ci].get(key, {}).get("concept_rank_in_stock") if ci > 0 else m.get("concept_rank_in_stock")
            total_i = member_sets[ci].get(key, {}).get("concept_total_count", 0) if ci > 0 else m.get("concept_total_count", 0)
            if rank_i is not None and isinstance(rank_i, int) and rank_i >= 1 and total_i and total_i >= rank_i:
                p = ((total_i - rank_i + 1) / total_i) * 100
            else:
                p = 40
            im = _calc_industry_multiplier(c_name, industry) * 100
            # Simplified density: just prominence + industry for cross mode
            match_i = round(p * 0.25 + im * 0.75)
            if match_i > best_match:
                best_match = match_i

        narrative = "、".join(concept_names) + f"，主营{industry.split('/')[-1].strip() if industry else '—'}"

        # Fetch current price from cached daily snapshot (local, fast)
        daily = _load_latest_daily_snapshot(market, symbol)
        cp = daily.get("latest_close")

        enriched.append({
            "market": market, "symbol": symbol,
            "stock_name": str(m.get("stock_name", symbol)),
            "industry_display": industry,
            "current_price": cp,
            "pe_ttm": pe,
            "rps_20": _coerce_float(rps.get("rps_20")),
            "rps_50": _coerce_float(rps.get("rps_50")),
            "rps_120": _coerce_float(rps.get("rps_120")),
            "rps_250": _coerce_float(rps.get("rps_250")),
            "total_rps": round(total_rps, 0),
            "market_total_rank": rank_by_key.get(key),
            "tech_trend_label": tech.get("trend_label"),
            "tech_trend": tech.get("trend"),
            "match_pct": best_match,
            "narrative": narrative,
            "matched_concepts": concept_names,
        })

    enriched.sort(key=lambda s: s.get("match_pct") or 0, reverse=True)

    return {
        "ok": True,
        "cross": True,
        "concepts": [{"name": n, "member_count": len(ms)} for n, ms in zip(concept_names, member_sets)],
        "intersection_count": len(enriched),
        "method": "cross",
        "stocks": enriched,
    }
