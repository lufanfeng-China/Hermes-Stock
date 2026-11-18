"""Compact watchlist identity and score data from existing published snapshots."""
from __future__ import annotations

from collections.abc import Iterable

from app.search.index import (
    _load_financial_snapshot,
    _load_industry_map,
    _load_snapshot_score_rankings,
    _stock_name_lookup,
    compute_financial_scores,
)


def load_watchlist_summaries(entries: Iterable[dict]) -> dict[tuple[str, str], dict]:
    """Read list fields in a batch; never run per-stock report or profile analysis."""
    pairs = [(str(item.get("market", "")), str(item.get("symbol", ""))) for item in entries]
    names = _stock_name_lookup()
    industries = _load_industry_map()
    # Missing snapshots must not trigger compute_financial_scores' raw-report fallback.
    has_snapshot = _load_financial_snapshot() is not None
    scores = compute_financial_scores(pairs)["scores"] if has_snapshot else {}
    ranks = _load_snapshot_score_rankings() if has_snapshot else {}
    result = {}
    for market, symbol in pairs:
        key = (market, symbol)
        ind2, ind1 = industries.get(key, (None, None))
        score = scores.get(key, {})
        result[key] = {
            "stock_name": names.get(key) or symbol,
            "industry_level_1": ind1,
            "industry_level_2": ind2,
            "market_total_score": score.get("total_score"),
            "market_total_rank": ranks.get("market_total_rank", {}).get(key),
            "market_total_universe_size": ranks.get("market_total_universe_size"),
            "industry_total_score": score.get("ind_total_score"),
            "industry_total_rank": ranks.get("industry_total_rank", {}).get(key),
            "industry_total_universe_size": ranks.get("industry_total_universe_size", {}).get(key),
            "dim_scores": score.get("dim_scores", {}),
            # The old list endpoint's stock_profile_response wrapper never exposed
            # RPS here (its RPS fields live under `profile`, not the top level).
            "rps_20": None, "rps_50": None, "rps_120": None, "rps_250": None,
        }
    return result
