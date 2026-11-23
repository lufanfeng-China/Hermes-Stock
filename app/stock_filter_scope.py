from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.concept_temperature import parse_tdx_concept_mapping


ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "data" / "derived" / "datasets" / "final"
INDUSTRY_PATH = FINAL / "dataset_stock_industry_current.json"
CONCEPT_MAPPING_PATH = Path("/mnt/c/new_tdx64/T0002/export/概念板块.txt")
CONCEPT_TEMPERATURE_PATH = FINAL / "dataset_concept_temperature_current.json"
INDUSTRY_TEMPERATURE_PATH = FINAL / "dataset_industry_temperature_current.json"
CONCEPT_TEMPERATURE_WINDOW = 10
TEMPERATURE_OPTIONS = (
    {"value": 5, "label": "极热"},
    {"value": 4, "label": "热门"},
    {"value": 3, "label": "升温"},
    {"value": 2, "label": "中性偏弱/分化上涨"},
    {"value": 1, "label": "偏冷"},
    {"value": 0, "label": "冰点"},
)


def _text(value: object) -> str:
    return str(value or "").strip()


def build_scope_index(
    industry_rows: Iterable[dict[str, Any]],
    concept_mapping: Iterable[dict[str, Any]],
    temperature_payload: dict[str, Any],
    *,
    industry_temperature_payload: dict[str, Any] | None = None,
    temperature_window: int = CONCEPT_TEMPERATURE_WINDOW,
) -> dict[str, Any]:
    industry_temperature_payload = industry_temperature_payload or {}
    industry_members: dict[str, set[str]] = defaultdict(set)
    industry_names: dict[str, str] = {}
    for row in industry_rows:
        code = _text(row.get("industry_level_2_code"))
        name = _text(row.get("industry_level_2_name"))
        market = _text(row.get("market")).lower()
        symbol = _text(row.get("symbol")).zfill(6)
        if not code or not name or not market or not symbol:
            continue
        industry_names.setdefault(code, name)
        industry_members[code].add(f"{market}:{symbol}")

    concept_members: dict[str, set[str]] = defaultdict(set)
    concept_names: dict[str, str] = {}
    for row in concept_mapping:
        code = _text(row.get("concept_code"))
        name = _text(row.get("concept_name"))
        symbol = _text(row.get("symbol")).zfill(6)
        if not code or not name or not symbol:
            continue
        concept_names.setdefault(code, name)
        concept_members[code].add(symbol)

    window_payload = (temperature_payload.get("windows") or {}).get(str(temperature_window)) or {}
    temperature_rows = window_payload.get("concepts") or []
    concept_temperature: dict[str, dict[str, Any]] = {}
    for row in temperature_rows:
        code = _text(row.get("concept_code"))
        if not code:
            continue
        concept_temperature[code] = {
            "temperature": row.get("temperature"),
            "temperature_label": _text(row.get("temperature_label")),
            "heat_score": row.get("heat_score"),
            "heat_rank": row.get("heat_rank"),
        }
        if _text(row.get("concept_name")):
            concept_names.setdefault(code, _text(row.get("concept_name")))

    industry_temperature: dict[str, dict[str, Any]] = {}
    temperature_labels = {item["value"]: item["label"] for item in TEMPERATURE_OPTIONS}
    industry_window = (industry_temperature_payload.get("windows") or {}).get(str(temperature_window)) or {}
    for row in industry_window.get("concepts") or []:
        code = _text(row.get("concept_code"))
        if not code:
            continue
        industry_temperature[code] = {
            "temperature": row.get("temperature"),
            "temperature_label": _text(row.get("temperature_label")),
            "heat_score": row.get("heat_score"),
            "heat_rank": row.get("heat_rank"),
            "temperature_previous": row.get("temperature_previous"),
            "temperature_previous_label": temperature_labels.get(row.get("temperature_previous"), "数据不足"),
            "temperature_previous_gap_days": row.get("temperature_previous_gap_days"),
            "temperature_change": row.get("temperature_change"),
            "temperature_trend": _text(row.get("temperature_trend")),
            "temperature_trend_label": _text(row.get("temperature_trend_label")),
        }

    industries = []
    for code, members in industry_members.items():
        temp = industry_temperature.get(code, {})
        industries.append({
            "code": code, "name": industry_names[code], "member_count": len(members),
            "temperature": temp.get("temperature"),
            "temperature_label": temp.get("temperature_label") or "数据不足",
            "heat_score": temp.get("heat_score"),
            "heat_rank": temp.get("heat_rank"),
            "temperature_previous": temp.get("temperature_previous"),
            "temperature_previous_label": temp.get("temperature_previous_label") or "数据不足",
            "temperature_previous_gap_days": temp.get("temperature_previous_gap_days"),
            "temperature_change": temp.get("temperature_change"),
            "temperature_trend": temp.get("temperature_trend"),
            "temperature_trend_label": temp.get("temperature_trend_label") or "数据不足",
        })
    industries.sort(key=lambda row: row["name"])
    concepts = []
    for code, members in concept_members.items():
        temp = concept_temperature.get(code, {})
        concepts.append({
            "code": code,
            "name": concept_names.get(code, code),
            "member_count": len(members),
            "temperature": temp.get("temperature"),
            "temperature_label": temp.get("temperature_label") or "数据不足",
            "heat_score": temp.get("heat_score"),
            "heat_rank": temp.get("heat_rank"),
        })
    concepts.sort(key=lambda row: (
        -(row["temperature"] if isinstance(row["temperature"], int) else -1),
        row["heat_rank"] if isinstance(row["heat_rank"], int) else 10**9,
        row["name"],
    ))
    return {
        "industries": industries,
        "concepts": concepts,
        "industry_members": dict(industry_members),
        "concept_members": dict(concept_members),
        "industry_temperature": industry_temperature,
        "concept_temperature": concept_temperature,
        "industry_temperature_as_of": _text(industry_temperature_payload.get("as_of_date")),
        "industry_temperature_window": temperature_window,
        "concept_temperature_as_of": _text(temperature_payload.get("as_of_date")),
        "concept_temperature_window": temperature_window,
    }


def _identity(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=4)
def _load_scope_index_cached(
    industry_identity: tuple[str, int, int],
    concept_identity: tuple[str, int, int],
    temperature_identity: tuple[str, int, int],
    industry_temperature_identity: tuple[str, int, int],
) -> dict[str, Any]:
    industry_path = Path(industry_identity[0])
    concept_path = Path(concept_identity[0])
    temperature_path = Path(temperature_identity[0])
    industry_temperature_path = Path(industry_temperature_identity[0])
    industries = json.loads(industry_path.read_text(encoding="utf-8"))
    concepts = parse_tdx_concept_mapping(concept_path.read_text(encoding="gb18030"))
    temperature = json.loads(temperature_path.read_text(encoding="utf-8"))
    industry_temperature = json.loads(industry_temperature_path.read_text(encoding="utf-8"))
    return build_scope_index(industries, concepts, temperature,
                             industry_temperature_payload=industry_temperature)


def stock_scope_index() -> dict[str, Any]:
    return _load_scope_index_cached(
        _identity(INDUSTRY_PATH),
        _identity(CONCEPT_MAPPING_PATH),
        _identity(CONCEPT_TEMPERATURE_PATH),
        _identity(INDUSTRY_TEMPERATURE_PATH),
    )


def effective_concept_codes(index: dict[str, Any], selected_codes: set[str], temperature_levels: set[int]) -> set[str]:
    available = set(index.get("concept_members") or {})
    codes = available.intersection(selected_codes) if selected_codes else available
    if temperature_levels:
        temperatures = index.get("concept_temperature") or {}
        codes = {code for code in codes if (temperatures.get(code) or {}).get("temperature") in temperature_levels}
    return codes


def effective_industry_codes(index: dict[str, Any], selected_codes: set[str], temperature_levels: set[int]) -> set[str]:
    available = set(index.get("industry_members") or {})
    codes = available.intersection(selected_codes) if selected_codes else available
    if temperature_levels:
        temperatures = index.get("industry_temperature") or {}
        codes = {code for code in codes if (temperatures.get(code) or {}).get("temperature") in temperature_levels}
    return codes


def filter_rows_by_scope(
    rows: Iterable[dict[str, Any]],
    index: dict[str, Any],
    *,
    industry_codes: set[str],
    industry_temperature_levels: set[int],
    concept_codes: set[str],
    temperature_levels: set[int],
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    effective_industries = effective_industry_codes(index, industry_codes, industry_temperature_levels)
    industry_active = bool(industry_codes or industry_temperature_levels)
    effective_concepts = effective_concept_codes(index, concept_codes, temperature_levels)
    concept_active = bool(concept_codes or temperature_levels)
    concept_symbols: set[str] = set()
    for code in effective_concepts:
        concept_symbols.update((index.get("concept_members") or {}).get(code) or ())
    filtered = []
    for row in rows:
        if industry_active and _text(row.get("industry_level_2_code")) not in effective_industries:
            continue
        if concept_active and _text(row.get("symbol")).zfill(6) not in concept_symbols:
            continue
        filtered.append(row)
    return filtered, effective_industries, effective_concepts


def scope_options_response(*, index: dict[str, Any] | None = None) -> dict[str, Any]:
    index = index or stock_scope_index()
    return {
        "ok": True,
        "industries": index["industries"],
        "concepts": index["concepts"],
        "industry_temperature_as_of": index["industry_temperature_as_of"],
        "industry_temperature_window": index["industry_temperature_window"],
        "concept_temperature_as_of": index["concept_temperature_as_of"],
        "concept_temperature_window": index["concept_temperature_window"],
        "temperature_options": list(TEMPERATURE_OPTIONS),
        "semantics": {
            "within_category": "OR",
            "across_categories": "AND",
            "explicit_industries_with_temperature": "selected industries intersect matching temperature levels",
            "explicit_concepts_with_temperature": "selected concepts intersect matching temperature levels",
        },
    }
