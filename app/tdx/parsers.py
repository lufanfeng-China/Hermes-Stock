"""Parsers for Tongdaxin industry and concept source files."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path


INDUSTRY_CURRENT_DATASET = "dataset_stock_industry_current"
INDUSTRY_SNAPSHOT_DATASET = "snapshot_stock_industry_membership"
CONCEPT_DICTIONARY_DATASET = "dataset_concept_dictionary"
CONCEPT_CURRENT_DATASET = "dataset_stock_concept_current"
CONCEPT_SNAPSHOT_DATASET = "snapshot_stock_concept_membership"
INDUSTRY_PARSER_VERSION = "industry_parser_v1"
CONCEPT_PARSER_VERSION = "concept_parser_v1"
DEFAULT_INDUSTRY_SOURCE_FILE = "T0002/hq_cache/tdxhy.cfg"
DEFAULT_CONCEPT_SOURCE_FILE = "T0002/signals/extern_sys.txt"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONCEPT_FILTER_CONFIG_PATH = PROJECT_ROOT / "config" / "concept_filter_rules.v1.json"


def today_trading_day() -> str:
    return date.today().isoformat()


def default_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_text_file(path: str | Path, *, preferred_encoding: str = "utf-8") -> str:
    path = Path(path)
    for encoding in (preferred_encoding, "utf-8", "gbk", "utf-8-sig"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding=preferred_encoding, errors="replace")


def write_json_rows(path: str | Path, rows: list[dict[str, object]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def market_from_flag(flag: str) -> str:
    return {"0": "sz", "1": "sh"}.get(flag, flag)


def parse_industry_code_map(text: str) -> dict[str, str]:
    code_map: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        code = parts[-1].strip()
        name = parts[0].strip()
        if code.startswith("X") and name:
            code_map[code] = name
    return code_map


def derive_industry_hierarchy(industry_code_raw_x: str, code_map: dict[str, str]) -> dict[str, str]:
    level_1_code = industry_code_raw_x[:3] if len(industry_code_raw_x) >= 3 else ""
    level_2_code = industry_code_raw_x[:5] if len(industry_code_raw_x) >= 5 else ""
    level_3_code = industry_code_raw_x if len(industry_code_raw_x) >= 7 else ""
    return {
        "industry_level_1_code": level_1_code,
        "industry_level_1_name": code_map.get(level_1_code, ""),
        "industry_level_2_code": level_2_code,
        "industry_level_2_name": code_map.get(level_2_code, ""),
        "industry_level_3_code": level_3_code,
        "industry_level_3_name": code_map.get(level_3_code, ""),
    }


def build_industry_datasets(
    *,
    stock_mapping_text: str,
    industry_code_text: str,
    trading_day: str,
    generated_at: str,
    data_cutoff_time: str,
    source_file: str = DEFAULT_INDUSTRY_SOURCE_FILE,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    code_map = parse_industry_code_map(industry_code_text)
    current_rows: list[dict[str, object]] = []
    for raw_line in stock_mapping_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        industry_code_raw_x = parts[5].strip()
        if not industry_code_raw_x.startswith("X"):
            continue
        row: dict[str, object] = {
            "dataset_name": INDUSTRY_CURRENT_DATASET,
            "trading_day": trading_day,
            "market": market_from_flag(parts[0].strip()),
            "symbol": parts[1].strip(),
            "stock_name": "",
            "source": "tdx_local",
            "source_file": source_file,
            "industry_source": "tdx_x_tree",
            "industry_code_raw_t": parts[2].strip(),
            "industry_code_raw_x": industry_code_raw_x,
            "analysis_template_id": "",
            "valuation_template_id": "",
            "mapping_confidence": 1.0,
            "parser_version": INDUSTRY_PARSER_VERSION,
            "generated_at": generated_at,
            "data_cutoff_time": data_cutoff_time,
            "validation_status": "passed",
        }
        row.update(derive_industry_hierarchy(industry_code_raw_x, code_map))
        current_rows.append(row)
    snapshot_rows = copy.deepcopy(current_rows)
    return current_rows, snapshot_rows


_CONCEPT_SPLIT_RE = re.compile(r"[,，]")
_SPACE_RE = re.compile(r"\s+")


def normalize_concept_name(name: str) -> str:
    return _SPACE_RE.sub(" ", name.strip())


def split_concept_names(concept_list_raw: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for part in _CONCEPT_SPLIT_RE.split(concept_list_raw):
        normalized = normalize_concept_name(part)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return names


def stable_concept_id(normalized_name: str) -> str:
    return hashlib.sha1(f"tdx_local:{normalized_name}".encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def load_concept_filter_rules(path: str | Path = CONCEPT_FILTER_CONFIG_PATH) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _matches_concept_rule(concept_name: str, rule: dict[str, object]) -> bool:
    match_type = str(rule.get("match_type", "")).strip()
    patterns = [str(item) for item in rule.get("patterns", []) if str(item)]
    if match_type == "exact":
        return concept_name in patterns
    if match_type == "contains":
        return any(pattern in concept_name for pattern in patterns)
    if match_type == "regex_any":
        return any(re.search(pattern, concept_name) for pattern in patterns)
    return False


def classify_concept_name_v1(concept_name: str) -> dict[str, str]:
    rules = load_concept_filter_rules()
    version = str(rules.get("version", "")).strip() or "concept_filter_rules_v1"
    sorted_rules = sorted(
        (rule for rule in rules.get("rules", []) if isinstance(rule, dict)),
        key=lambda item: int(item.get("priority", 0)),
    )
    for rule in sorted_rules:
        if _matches_concept_rule(concept_name, rule):
            return {
                "concept_filter_version": version,
                "concept_filter_rule_id": str(rule.get("id", "")).strip(),
                "concept_filter_bucket": str(rule.get("bucket", "")).strip() or "core",
                "concept_filter_decision": str(rule.get("decision", "")).strip() or "keep_core",
                "concept_filter_reason": str(rule.get("reason", "")).strip(),
            }
    return {
        "concept_filter_version": version,
        "concept_filter_rule_id": "default_keep_core",
        "concept_filter_bucket": str(rules.get("default_bucket", "")).strip() or "core",
        "concept_filter_decision": str(rules.get("default_decision", "")).strip() or "keep_core",
        "concept_filter_reason": "default keep_core/core classification",
    }


def build_concept_datasets(
    *,
    concept_text: str,
    trading_day: str,
    generated_at: str,
    data_cutoff_time: str,
    source_file: str = DEFAULT_CONCEPT_SOURCE_FILE,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    current_rows: list[dict[str, object]] = []
    dictionary_index: dict[str, dict[str, object]] = {}

    for raw_line in concept_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        concept_names = split_concept_names(parts[3])
        if not concept_names:
            continue
        normalized_raw = ",".join(concept_names)
        for rank, concept_name in enumerate(concept_names, start=1):
            concept_id = stable_concept_id(concept_name)
            concept_filter = classify_concept_name_v1(concept_name)
            current_rows.append(
                {
                    "dataset_name": CONCEPT_CURRENT_DATASET,
                    "trading_day": trading_day,
                    "market": market_from_flag(parts[0].strip()),
                    "symbol": parts[1].strip(),
                    "stock_name": "",
                    "concept_id": concept_id,
                    "concept_name": concept_name,
                    "source": "tdx_local",
                    "source_file": source_file,
                    "is_active": True,
                    "concept_rank_in_stock": rank,
                    "concept_list_raw": normalized_raw,
                    "parser_version": CONCEPT_PARSER_VERSION,
                    "generated_at": generated_at,
                    "data_cutoff_time": data_cutoff_time,
                    "validation_status": "passed",
                    **concept_filter,
                }
            )
            dictionary_index.setdefault(
                concept_id,
                {
                    "dataset_name": CONCEPT_DICTIONARY_DATASET,
                    "concept_id": concept_id,
                    "concept_name": concept_name,
                    "concept_name_normalized": concept_name,
                    "concept_category": "",
                    "source": "tdx_local",
                    "source_file": source_file,
                    "first_seen_date": trading_day,
                    "last_seen_date": trading_day,
                    "is_active": True,
                    "alias_names": [],
                    "parser_version": CONCEPT_PARSER_VERSION,
                    "generated_at": generated_at,
                    **concept_filter,
                },
            )

    dictionary_rows = sorted(dictionary_index.values(), key=lambda row: str(row["concept_name_normalized"]))
    snapshot_rows = copy.deepcopy(current_rows)
    return dictionary_rows, current_rows, snapshot_rows


def with_dataset_name(rows: list[dict[str, object]], dataset_name: str) -> list[dict[str, object]]:
    renamed = copy.deepcopy(rows)
    for row in renamed:
        row["dataset_name"] = dataset_name
    return renamed
