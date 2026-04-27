"""Local stock and concept search indexes backed by Tongdaxin and derived JSON datasets."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.tdx.parsers import classify_concept_name_v1


TNF_HEADER_SIZE = 50
TNF_RECORD_SIZE = 360
TNF_NAME_OFFSET = 31
TNF_NAME_SIZE = 18
TNF_PINYIN_OFFSET = 329
TNF_PINYIN_SIZE = 12

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TNF_FILES = (
    ("sh", Path("/mnt/c/new_tdx64/T0002/hq_cache/shs.tnf")),
    ("sz", Path("/mnt/c/new_tdx64/T0002/hq_cache/szs.tnf")),
    ("bj", Path("/mnt/c/new_tdx64/T0002/hq_cache/bjs.tnf")),
)
DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"


def _decode_field(raw: bytes, encoding: str) -> str:
    value = raw.split(b"\x00", 1)[0].strip(b"\x00 ").decode(encoding, errors="ignore")
    return value.strip()


def parse_tnf_file(path: str | Path, *, market: str) -> list[dict[str, str]]:
    """Extract stock code, Chinese name, and initials from a Tongdaxin TNF file."""

    payload = Path(path).read_bytes()
    rows: list[dict[str, str]] = []
    for offset in range(TNF_HEADER_SIZE, len(payload), TNF_RECORD_SIZE):
        record = payload[offset : offset + TNF_RECORD_SIZE]
        if len(record) < TNF_RECORD_SIZE:
            continue
        symbol = record[0:6].decode("ascii", errors="ignore").strip()
        if len(symbol) != 6 or not symbol.isdigit():
            continue
        stock_name = _decode_field(record[TNF_NAME_OFFSET : TNF_NAME_OFFSET + TNF_NAME_SIZE], "gbk")
        name_initials = _decode_field(
            record[TNF_PINYIN_OFFSET : TNF_PINYIN_OFFSET + TNF_PINYIN_SIZE],
            "ascii",
        ).lower()
        if not stock_name:
            continue
        rows.append(
            {
                "market": market,
                "symbol": symbol,
                "stock_name": stock_name,
                "name_initials": name_initials,
            }
        )
    return rows


def _normalized_query(query: str) -> str:
    return query.strip().lower()


def _score_stock_match(row: dict[str, str], query: str) -> int | None:
    symbol = row["symbol"]
    stock_name = row["stock_name"]
    initials = row["name_initials"]
    if query == symbol:
        return 0
    if symbol.startswith(query):
        return 1
    if query == initials:
        return 2
    if initials.startswith(query):
        return 3
    if query == stock_name.lower():
        return 4
    if query in stock_name.lower():
        return 5
    return None


def search_stocks(
    rows: list[dict[str, str]],
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, str]]:
    normalized = _normalized_query(query)
    if not normalized:
        return []

    matched: list[tuple[int, dict[str, str]]] = []
    for row in rows:
        score = _score_stock_match(row, normalized)
        if score is None:
            continue
        matched.append((score, row))
    matched.sort(key=lambda item: (item[0], item[1]["symbol"]))
    return [row for _, row in matched[:limit]]


def _load_json_rows(path: str | Path) -> list[dict[str, object]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    for key in ("rows", "data", "items"):
        rows = data.get(key)
        if isinstance(rows, list):
            return rows
    raise ValueError(f"unsupported dataset payload: {path}")


def _security_key(row: dict[str, object]) -> tuple[str, str]:
    return str(row.get("market", "")), str(row.get("symbol", ""))


def build_industry_lookup(
    industry_rows: list[dict[str, object]],
    securities: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    security_lookup = {_security_key(row): row for row in securities}
    lookup: dict[tuple[str, str], dict[str, str]] = {}
    for row in industry_rows:
        key = _security_key(row)
        security = security_lookup.get(key, {})
        industry_names = [
            str(row.get("industry_level_1_name", "")).strip(),
            str(row.get("industry_level_2_name", "")).strip(),
            str(row.get("industry_level_3_name", "")).strip(),
        ]
        lookup[key] = {
            "market": key[0],
            "symbol": key[1],
            "stock_name": str(row.get("stock_name") or security.get("stock_name") or "").strip(),
            "industry_display": " / ".join(name for name in industry_names if name),
        }
    return lookup


def build_concept_index(
    concept_rows: list[dict[str, object]],
    securities: list[dict[str, str]],
    industry_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    security_lookup = {_security_key(row): row for row in securities}
    industry_lookup = build_industry_lookup(industry_rows, securities)
    concept_map: dict[str, dict[str, object]] = {}

    for row in concept_rows:
        concept_id = str(row.get("concept_id", "")).strip()
        concept_name = str(row.get("concept_name", "")).strip()
        market = str(row.get("market", "")).strip()
        symbol = str(row.get("symbol", "")).strip()
        if not concept_id or not concept_name or not market or not symbol:
            continue

        key = (market, symbol)
        security = security_lookup.get(key, {})
        industry = industry_lookup.get(key, {})
        member = {
            "market": market,
            "symbol": symbol,
            "stock_name": str(row.get("stock_name") or industry.get("stock_name") or security.get("stock_name") or "").strip(),
            "industry_display": str(industry.get("industry_display", "")).strip(),
            "name_initials": str(security.get("name_initials", "")).strip(),
        }

        concept = concept_map.setdefault(
            concept_id,
            {
                "concept_id": concept_id,
                "concept_name": concept_name,
                "member_count": 0,
                "members": [],
                "_member_keys": set(),
            },
        )
        if key in concept["_member_keys"]:
            continue
        concept["_member_keys"].add(key)
        concept["members"].append(member)
        concept["member_count"] += 1

    concepts = []
    for concept in concept_map.values():
        concept.pop("_member_keys", None)
        concepts.append(concept)
    concepts.sort(key=lambda row: (-int(row["member_count"]), str(row["concept_name"])))
    return concepts


def build_stock_profile(
    symbol: str,
    securities: list[dict[str, str]],
    industry_rows: list[dict[str, object]],
    concept_rows: list[dict[str, object]],
) -> dict[str, object]:
    security_lookup = {str(row.get("symbol", "")).strip(): row for row in securities}
    security = security_lookup.get(symbol)
    if not security:
        raise ValueError(f"stock not found: {symbol}")

    key = (str(security.get("market", "")).strip(), str(security.get("symbol", "")).strip())
    industry = build_industry_lookup(industry_rows, securities).get(key, {})
    core_concepts: list[dict[str, str]] = []
    auxiliary_concepts: dict[str, list[dict[str, str]]] = {}
    seen_concepts: set[str] = set()
    for row in concept_rows:
        row_key = _security_key(row)
        if row_key != key:
            continue
        concept_id = str(row.get("concept_id", "")).strip()
        concept_name = str(row.get("concept_name", "")).strip()
        if not concept_id or not concept_name or concept_id in seen_concepts:
            continue
        seen_concepts.add(concept_id)
        concept_filter_bucket = str(row.get("concept_filter_bucket", "")).strip()
        concept_filter_decision = str(row.get("concept_filter_decision", "")).strip()
        if not concept_filter_bucket or not concept_filter_decision:
            inferred_filter = classify_concept_name_v1(concept_name)
            concept_filter_bucket = concept_filter_bucket or inferred_filter["concept_filter_bucket"]
            concept_filter_decision = concept_filter_decision or inferred_filter["concept_filter_decision"]
        concept = {
            "concept_id": concept_id,
            "concept_name": concept_name,
            "concept_filter_bucket": concept_filter_bucket or "core",
            "concept_filter_decision": concept_filter_decision or "keep_core",
        }
        if concept["concept_filter_decision"] == "keep_core":
            core_concepts.append(concept)
            continue
        bucket = concept["concept_filter_bucket"] or "other"
        auxiliary_concepts.setdefault(bucket, []).append(concept)

    core_concepts.sort(key=lambda row: str(row["concept_name"]))
    for bucket in auxiliary_concepts:
        auxiliary_concepts[bucket].sort(key=lambda row: str(row["concept_name"]))
    return {
        "market": key[0],
        "symbol": key[1],
        "stock_name": str(security.get("stock_name", "")).strip(),
        "name_initials": str(security.get("name_initials", "")).strip(),
        "industry_display": str(industry.get("industry_display", "")).strip(),
        "concept_count": len(core_concepts),
        "core_concept_count": len(core_concepts),
        "concepts": core_concepts,
        "core_concepts": core_concepts,
        "auxiliary_concepts": auxiliary_concepts,
    }


def search_concepts(
    concepts: list[dict[str, object]],
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    normalized = _normalized_query(query)
    if not normalized:
        return []

    exact: list[dict[str, object]] = []
    partial: list[dict[str, object]] = []
    for concept in concepts:
        name = str(concept.get("concept_name", "")).lower()
        if name == normalized:
            exact.append(concept)
        elif normalized in name:
            partial.append(concept)
    partial.sort(key=lambda row: (-int(row.get("member_count", 0)), str(row.get("concept_name", ""))))
    return (exact + partial)[:limit]


@lru_cache(maxsize=1)
def load_security_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for market, path in DEFAULT_TNF_FILES:
        if not path.exists():
            continue
        for row in parse_tnf_file(path, market=market):
            key = (row["market"], row["symbol"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda row: (row["market"], row["symbol"]))
    return rows


@lru_cache(maxsize=1)
def load_concept_rows(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return _load_json_rows(Path(dataset_dir) / "dataset_stock_concept_current.json")


@lru_cache(maxsize=1)
def load_industry_rows(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return _load_json_rows(Path(dataset_dir) / "dataset_stock_industry_current.json")


@lru_cache(maxsize=1)
def load_concept_index(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return build_concept_index(
        load_concept_rows(dataset_dir),
        load_security_rows(),
        load_industry_rows(dataset_dir),
    )


def stock_search_response(query: str, *, limit: int = 20) -> dict[str, object]:
    matches = search_stocks(load_security_rows(), query, limit=limit)
    return {
        "ok": True,
        "query": query,
        "count": len(matches),
        "results": matches,
    }


def concept_search_response(query: str, *, limit: int = 20) -> dict[str, object]:
    matches = search_concepts(load_concept_index(), query, limit=limit)
    return {
        "ok": True,
        "query": query,
        "count": len(matches),
        "results": matches,
    }


def stock_profile_response(symbol: str) -> dict[str, object]:
    profile = build_stock_profile(
        symbol.strip(),
        load_security_rows(),
        load_industry_rows(),
        load_concept_rows(),
    )
    return {
        "ok": True,
        "symbol": symbol,
        "profile": profile,
    }
