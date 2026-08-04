"""Concept-theme clustering and primary-driver attribution.

A theme cluster groups highly overlapping current concept memberships so a stock
cannot consume portfolio risk multiple times merely because it carries several
near-duplicate labels.  This module intentionally does not infer historical
membership; callers must label historical use as current-mapping research.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_theme_clusters(mapping: list[dict[str, str]], overlap_threshold: float = 0.60) -> dict[str, Any]:
    """Cluster concept codes whose member-set Jaccard overlap is >= threshold."""
    if not 0 < overlap_threshold <= 1:
        raise ValueError("overlap_threshold must be in (0, 1]")
    members: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for row in mapping:
        code, symbol = row.get("concept_code"), row.get("symbol")
        if not code or not symbol:
            continue
        members[str(code)].add(str(symbol))
        names.setdefault(str(code), str(row.get("concept_name", code)))
    codes = sorted(members)
    parent = {code: code for code in codes}

    def find(code: str) -> str:
        while parent[code] != code:
            parent[code] = parent[parent[code]]
            code = parent[code]
        return code

    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    for index, left in enumerate(codes):
        left_members = members[left]
        for right in codes[index + 1:]:
            right_members = members[right]
            union_size = len(left_members | right_members)
            if union_size and len(left_members & right_members) / union_size >= overlap_threshold:
                union(left, right)
    grouped: dict[str, list[str]] = defaultdict(list)
    for code in codes:
        grouped[find(code)].append(code)
    clusters = []
    concept_to_cluster = {}
    for number, (_, concept_codes) in enumerate(sorted(grouped.items()), 1):
        cluster_id = f"theme-{number:03d}"
        concept_codes = sorted(concept_codes)
        cluster = {
            "theme_cluster_id": cluster_id,
            "concept_codes": concept_codes,
            "concept_names": [names[code] for code in concept_codes],
            "concept_count": len(concept_codes),
        }
        clusters.append(cluster)
        concept_to_cluster.update({code: cluster_id for code in concept_codes})
    return {
        "overlap_metric": "jaccard_member_overlap",
        "overlap_threshold": overlap_threshold,
        "clusters": clusters,
        "concept_to_cluster": concept_to_cluster,
    }


def primary_concept_for_stock(symbol: str, concepts: list[dict[str, Any]], concept_to_cluster: dict[str, str]) -> dict[str, Any] | None:
    """Return deterministic primary concept: temp, heat, breadth, rank, code."""
    candidates = [row for row in concepts if str(row.get("symbol", symbol)) == str(symbol) and row.get("concept_code") in concept_to_cluster]
    if not candidates:
        return None
    def key(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
        temp = row.get("temperature")
        return (-(float(temp) if temp is not None else -1), -float(row.get("heat_score", -1)), -float(row.get("breadth_pct", -1)), float(row.get("concept_rank", 10**9)), str(row["concept_code"]))
    primary = dict(sorted(candidates, key=key)[0])
    primary["theme_cluster_id"] = concept_to_cluster[primary["concept_code"]]
    return primary
