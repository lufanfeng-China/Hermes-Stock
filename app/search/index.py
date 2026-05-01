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


def is_a_share_eligible(symbol: str, stock_name: str) -> bool:
    """
    Return True if the stock is an eligible A-share (沪深北交所，排除ST/*ST/S，排除指数).
    Eligible: 6xxxxx (沪主板+科创板), 00xxxxx (深主板), 30xxxx (创业板), 92xxxx (北交所)
    Excluded: names containing ST/*ST/S/S (special treatment flags)
    """
    if not symbol or len(symbol) != 6:
        return False
    # A-share prefix rules
    if not (symbol.startswith(("6", "00", "30", "92"))):
        return False
    # Exclude indices: 999xxx (上证指数), 399xxx (深证指数), 8xxxxx (沪ETF), etc.
    if symbol.startswith(("999", "399", "8", "4")):
        return False
    # Exclude ST/*ST/S stocks
    name = stock_name or ""
    if "ST" in name or "*ST" in name or name.startswith("S ") or (name == "S"):
        return False
    return True


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
    rps_rows: list[dict[str, object]] | None = None,
    *,
    basic_info: dict[str, object] | None = None,
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
    rps_metrics = {
        "rps_20": None,
        "rps_50": None,
        "rps_120": None,
        "rps_250": None,
        "rank_20": None,
        "rank_50": None,
        "rank_120": None,
        "rank_250": None,
        "universe_size": None,
        "return_20_pct": None,
        "return_50_pct": None,
        "return_120_pct": None,
        "return_250_pct": None,
        "industry_rank_20": None,
        "industry_rank_50": None,
        "industry_universe_size": None,
    }
    if rps_rows:
        industry_level_2_name = ""
        for row in industry_rows:
            if _security_key(row) != key:
                continue
            industry_level_2_name = str(row.get("industry_level_2_name", "")).strip()
            break

        for row in rps_rows:
            if _security_key(row) != key:
                continue
            rps_metrics = {
                "rps_20": row.get("rps_20"),
                "rps_50": row.get("rps_50"),
                "rps_120": row.get("rps_120"),
                "rps_250": row.get("rps_250"),
                "rank_20": row.get("rank_20"),
                "rank_50": row.get("rank_50"),
                "rank_120": row.get("rank_120"),
                "rank_250": row.get("rank_250"),
                "universe_size": row.get("universe_size"),
                "return_20_pct": row.get("return_20_pct"),
                "return_50_pct": row.get("return_50_pct"),
                "return_120_pct": row.get("return_120_pct"),
                "return_250_pct": row.get("return_250_pct"),
                "industry_rank_20": None,
                "industry_rank_50": None,
                "industry_universe_size": None,
            }
            break
        if industry_level_2_name:
            members_in_industry: set[tuple[str, str]] = set()
            rps_by_security = {_security_key(row): row for row in rps_rows}
            ranked_rows_20: list[tuple[float, str, str]] = []
            ranked_rows_50: list[tuple[float, str, str]] = []
            for row in industry_rows:
                row_key = _security_key(row)
                if str(row.get("industry_level_2_name", "")).strip() != industry_level_2_name:
                    continue
                rps_row = rps_by_security.get(row_key)
                if not rps_row:
                    continue
                members_in_industry.add(row_key)
                rps_20 = _coerce_float(rps_row.get("rps_20"))
                rps_50 = _coerce_float(rps_row.get("rps_50"))
                if rps_20 is not None:
                    ranked_rows_20.append((rps_20, row_key[0], row_key[1]))
                if rps_50 is not None:
                    ranked_rows_50.append((rps_50, row_key[0], row_key[1]))

            def _industry_rank(rows: list[tuple[float, str, str]], target_key: tuple[str, str]) -> int | None:
                ordered = sorted(rows, key=lambda item: (-item[0], item[1], item[2]))
                for index, (_, market, stock_symbol) in enumerate(ordered, start=1):
                    if (market, stock_symbol) == target_key:
                        return index
                return None

            if members_in_industry:
                rps_metrics["industry_universe_size"] = len(members_in_industry)
                rps_metrics["industry_rank_20"] = _industry_rank(ranked_rows_20, key)
                rps_metrics["industry_rank_50"] = _industry_rank(ranked_rows_50, key)
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
        "basic_info": dict(basic_info or {}),
        **rps_metrics,
    }


def _load_financial_quarter_frame(period: str):
    try:
        import pandas as pd
    except ModuleNotFoundError:
        return None
    except Exception:
        return None
    path = _PROJECT_ROOT / "data" / "derived" / "financial_ts" / "by_quarter" / f"{period}.parquet"
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


@lru_cache(maxsize=32)
def _load_financial_quarter_frame_cached(period: str):
    return _load_financial_quarter_frame(period)


def _load_financial_quarter_row(period: str, symbol: str):
    frame = _load_financial_quarter_frame_cached(period)
    if frame is None or getattr(frame, "empty", False):
        return None
    candidates = [symbol]
    stripped = symbol.lstrip("0")
    if stripped and stripped not in candidates:
        candidates.append(stripped)
    if symbol.startswith("0") and symbol[1:] and symbol[1:] not in candidates:
        candidates.append(symbol[1:])
    for candidate in candidates:
        try:
            if candidate in frame.index:
                return frame.loc[candidate]
        except Exception:
            continue
    return None


def _snapshot_latest_period(market: str, symbol: str) -> str:
    snap = _load_financial_snapshot()
    if snap is None:
        return ""
    entry = snap.get("scores", {}).get(f"{market}:{symbol}", {})
    return str(entry.get("latest_period") or "").strip()


def _annualized_eps_from_period(period: str, current_eps: float | None) -> float | None:
    if current_eps is None:
        return None
    text = str(period or "").strip()
    if text.endswith("A"):
        return current_eps
    if text.endswith("Q1"):
        return current_eps * 4.0
    if text.endswith("Q2"):
        return current_eps * 2.0
    if text.endswith("Q3"):
        return current_eps * 4.0 / 3.0
    return None


def _ttm_eps(period: str, symbol: str, current_eps: float | None) -> float | None:
    text = str(period or "").strip()
    if not text:
        return None
    if text.endswith("A"):
        return current_eps
    if not (len(text) >= 6 and text[:4].isdigit() and text[4] == "Q" and text[5] in {"1", "2", "3"}):
        return _annualized_eps_from_period(text, current_eps)
    year = int(text[:4])
    prev_annual_row = _load_financial_quarter_row(f"{year - 1}A", symbol)
    prev_same_row = _load_financial_quarter_row(f"{year - 1}{text[4:]}", symbol)
    prev_annual_eps = _pick(prev_annual_row.get("基本每股收益")) if prev_annual_row is not None else None
    prev_same_eps = None
    if prev_same_row is not None:
        prev_same_eps = _pick(prev_same_row.get("基本每股收益（单季度）"))
        if prev_same_eps is None:
            prev_same_eps = _pick(prev_same_row.get("基本每股收益"))
    if current_eps is not None and prev_annual_eps is not None and prev_same_eps is not None:
        return current_eps + prev_annual_eps - prev_same_eps
    return _annualized_eps_from_period(text, current_eps)


def _load_realtime_quote_snapshot(market: str, symbol: str) -> dict[str, object] | None:
    try:
        from mootdx.quotes import Quotes
    except ModuleNotFoundError:
        return None
    except Exception:
        return None
    if market not in {"sh", "sz", "bj"} or not symbol:
        return None
    try:
        client = Quotes.factory(market="std")
        rows = client.quotes(symbol=[symbol])
        if rows is None or getattr(rows, "empty", False):
            return None
        row = rows.iloc[0] if hasattr(rows, "iloc") else rows[0]
        return {
            "price": _pick(row.get("price")) if hasattr(row, "get") else None,
            "last_close": _pick(row.get("last_close")) if hasattr(row, "get") else None,
            "volume": _pick(row.get("volume")) if hasattr(row, "get") else _pick(row.get("vol")) if hasattr(row, "get") else None,
            "amount": _pick(row.get("amount")) if hasattr(row, "get") else None,
        }
    except Exception:
        return None


@lru_cache(maxsize=256)
def _load_latest_daily_snapshot(market: str, symbol: str) -> dict[str, float | None]:
    snapshot = {
        "latest_close": None,
        "previous_close": None,
        "latest_volume": None,
        "avg_volume_5": None,
    }
    try:
        from mootdx.reader import Reader
    except ModuleNotFoundError:
        return snapshot
    except Exception:
        return snapshot
    if market not in {"sh", "sz", "bj"} or not symbol:
        return snapshot
    try:
        reader = Reader.factory(market="std", tdxdir=_TDX_DIR)
        daily = reader.daily(symbol=symbol)
        if daily is None or daily.empty:
            return snapshot
        latest_row = daily.iloc[-1]
        snapshot["latest_close"] = _pick(latest_row.get("close"))
        snapshot["latest_volume"] = _pick(latest_row.get("volume"))
        if len(daily) >= 2:
            snapshot["previous_close"] = _pick(daily.iloc[-2].get("close"))
            lookback = daily.iloc[max(0, len(daily) - 6):-1]
            previous_volumes = [_pick(row.get("volume")) for _idx, row in lookback.iterrows()]
            previous_volumes = [value for value in previous_volumes if value not in (None, 0)]
            if previous_volumes:
                snapshot["avg_volume_5"] = sum(previous_volumes) / len(previous_volumes)
    except Exception:
        return snapshot
    return snapshot


def _load_stock_basic_info(market: str, symbol: str) -> dict[str, object]:
    basic_info = {
        "current_price": None,
        "change_pct": None,
        "volume_ratio": None,
        "a_share_market_cap": None,
        "total_shares": None,
        "float_shares": None,
        "eps": None,
        "dynamic_pe": None,
    }

    realtime_snapshot = _load_realtime_quote_snapshot(market, symbol) or {}
    daily_snapshot = _load_latest_daily_snapshot(market, symbol)

    current_price = _pick(realtime_snapshot.get("price"))
    if current_price is None:
        current_price = daily_snapshot.get("latest_close")
    basic_info["current_price"] = current_price

    last_close = _pick(realtime_snapshot.get("last_close"))
    if last_close is None:
        last_close = daily_snapshot.get("previous_close")
    if current_price is not None and last_close not in (None, 0):
        basic_info["change_pct"] = (current_price - last_close) / last_close * 100.0

    current_volume = _pick(realtime_snapshot.get("volume"))
    if current_volume is None:
        current_volume = daily_snapshot.get("latest_volume")
    avg_volume_5 = daily_snapshot.get("avg_volume_5")
    if current_volume not in (None, 0) and avg_volume_5 not in (None, 0):
        basic_info["volume_ratio"] = current_volume / avg_volume_5

    local_reference_price = daily_snapshot.get("latest_close")
    if local_reference_price is None:
        local_reference_price = current_price

    latest_period = _snapshot_latest_period(market, symbol)
    financial_row = _load_financial_quarter_row(latest_period, symbol) if latest_period else None
    if financial_row is None:
        return basic_info

    current_eps = _pick(financial_row.get("基本每股收益（单季度）"))
    if current_eps is None:
        current_eps = _pick(financial_row.get("基本每股收益"))
    if current_eps is None:
        current_eps = _pick(financial_row.get("稀释每股收益(元)"))
    total_shares_raw = _pick(financial_row.get("总股本"))
    if total_shares_raw is None:
        total_shares_raw = _pick(financial_row.get("实收资本（或股本）"))
    float_shares_raw = _pick(financial_row.get("已上市流通A股"))
    if float_shares_raw is None:
        float_shares_raw = _pick(financial_row.get("自由流通股(股)"))
    h_shares = _pick(financial_row.get("已上市流通H股")) or 0.0
    b_shares = _pick(financial_row.get("已上市流通B股")) or 0.0
    a_share_total_shares_raw = None
    if total_shares_raw is not None:
        a_share_total_shares_raw = max(total_shares_raw - h_shares - b_shares, 0.0)

    basic_info["eps"] = current_eps
    basic_info["total_shares"] = total_shares_raw / 1e8 if total_shares_raw is not None else None
    basic_info["float_shares"] = float_shares_raw / 1e8 if float_shares_raw is not None else None
    if local_reference_price is not None and a_share_total_shares_raw is not None:
        basic_info["a_share_market_cap"] = local_reference_price * a_share_total_shares_raw / 1e8

    ttm_eps = _ttm_eps(latest_period, symbol, current_eps)
    if local_reference_price is not None and ttm_eps is not None and ttm_eps > 0:
        basic_info["dynamic_pe"] = local_reference_price / ttm_eps
    return basic_info


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


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_rps_index(
    rps_rows: list[dict[str, object]],
    securities: list[dict[str, str]],
    industry_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    security_lookup = {_security_key(row): row for row in securities}
    industry_lookup = build_industry_lookup(industry_rows, securities)
    rankings: list[dict[str, object]] = []

    for row in rps_rows:
        key = _security_key(row)
        market, symbol = key
        if not market or not symbol:
            continue
        security = security_lookup.get(key, {})
        industry = industry_lookup.get(key, {})
        rankings.append(
            {
                "trading_day": str(row.get("trading_day", "")).strip(),
                "market": market,
                "symbol": symbol,
                "stock_name": str(security.get("stock_name", row.get("stock_name", ""))).strip(),
                "name_initials": str(security.get("name_initials", "")).strip(),
                "industry_display": str(industry.get("industry_display", "")).strip(),
                "rps_20": _coerce_float(row.get("rps_20")),
                "rps_50": _coerce_float(row.get("rps_50")),
                "rps_120": _coerce_float(row.get("rps_120")),
                "rps_250": _coerce_float(row.get("rps_250")),
                "return_20_pct": _coerce_float(row.get("return_20_pct")),
                "return_50_pct": _coerce_float(row.get("return_50_pct")),
                "return_120_pct": _coerce_float(row.get("return_120_pct")),
                "return_250_pct": _coerce_float(row.get("return_250_pct")),
                "rank_20": _coerce_int(row.get("rank_20")),
                "rank_50": _coerce_int(row.get("rank_50")),
                "rank_120": _coerce_int(row.get("rank_120")),
                "rank_250": _coerce_int(row.get("rank_250")),
                "universe_size": _coerce_int(row.get("universe_size")),
            }
        )
    return rankings


def search_rps_rankings(
    index_rows: list[dict[str, object]],
    query: str = "",
    *,
    window: int = 20,
    limit: int = 20,
) -> list[dict[str, object]]:
    if window not in (20, 50, 120, 250):
        raise ValueError(f"unsupported RPS window: {window}")

    normalized = _normalized_query(query)
    metric_key = f"rps_{window}"
    rank_key = f"rank_{window}"
    return_key = f"return_{window}_pct"
    matched: list[dict[str, object]] = []

    for row in index_rows:
        if normalized:
            score = _score_stock_match(
                {
                    "symbol": str(row.get("symbol", "")).strip(),
                    "stock_name": str(row.get("stock_name", "")).strip(),
                    "name_initials": str(row.get("name_initials", "")).strip(),
                },
                normalized,
            )
            if score is None:
                continue
        rank_value = row.get(rank_key)
        rps_value = row.get(metric_key)
        if rank_value is None or rps_value is None:
            continue
        matched.append(
            {
                **row,
                "rps": rps_value,
                "rank": rank_value,
                "return_pct": row.get(return_key),
                "metric_key": metric_key,
            }
        )

    matched.sort(
        key=lambda row: (
            int(row.get("rank") if row.get("rank") is not None else 10**9),
            -float(row.get("rps") if row.get("rps") is not None else -1),
            str(row.get("symbol", "")),
        )
    )
    return matched[:limit]


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
            # Apply A-share eligibility filter
            if not is_a_share_eligible(row["symbol"], row["stock_name"]):
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
def load_rps_rows(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return _load_json_rows(Path(dataset_dir) / "dataset_stock_rps_current.json")


@lru_cache(maxsize=1)
def load_concept_index(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return build_concept_index(
        load_concept_rows(dataset_dir),
        load_security_rows(),
        load_industry_rows(dataset_dir),
    )


@lru_cache(maxsize=1)
def load_rps_index(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return build_rps_index(
        load_rps_rows(dataset_dir),
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
    symbol_text = symbol.strip()
    securities = load_security_rows()
    security_lookup = {str(row.get("symbol", "")).strip(): row for row in securities}
    security = security_lookup.get(symbol_text)
    basic_info = None
    if security is not None:
        market = str(security.get("market", "")).strip()
        if market:
            basic_info = _load_stock_basic_info(market, symbol_text)
    profile = build_stock_profile(
        symbol_text,
        securities,
        load_industry_rows(),
        load_concept_rows(),
        load_rps_rows(),
        basic_info=basic_info,
    )
    return {
        "ok": True,
        "symbol": symbol,
        "profile": profile,
    }


def rps_ranking_response(query: str = "", *, window: int = 20, limit: int = 20) -> dict[str, object]:
    matches = search_rps_rankings(load_rps_index(), query, window=window, limit=limit)
    return {
        "ok": True,
        "query": query,
        "window": window,
        "count": len(matches),
        "results": matches,
    }


# ---------------------------------------------------------------------------
# Pool filter & hierarchy APIs
# ---------------------------------------------------------------------------

def industry_hierarchy_response() -> dict[str, object]:
    """Return the full 申万一级/二级 industry tree."""
    rows = load_industry_rows()

    level1_map: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        l1 = row.get("industry_level_1_name") or ""
        l2 = row.get("industry_level_2_name") or ""
        if l1 and l2:
            level1_map.setdefault(l1, {})
            level1_map[l1].setdefault(l2, [])

    tree = []
    for l1 in sorted(level1_map.keys()):
        l2s = sorted(level1_map[l1].keys())
        tree.append({"name": l1, "level2": l2s})

    return {"ok": True, "industries": tree}


def concept_list_response(query: str = "", limit: int = 100) -> dict[str, object]:
    """Return active concept names, optionally filtered by query prefix match."""
    concept_dict_path = Path(DEFAULT_DATASET_DIR) / "dataset_concept_dictionary.json"
    all_concepts = _load_json_rows(concept_dict_path)

    # Only active concepts
    active = [c for c in all_concepts if c.get("is_active", False)]

    if query:
        q = query.strip().lower()
        filtered = [c for c in active if q in (c.get("concept_name") or "").lower()]
    else:
        filtered = active

    results = [
        {
            "concept_id": c.get("concept_id", ""),
            "concept_name": c.get("concept_name", ""),
        }
        for c in filtered[:limit]
    ]

    return {"ok": True, "query": query, "count": len(results), "results": results}


def pool_filter_response(
    level1_filters: list[str],
    level2_filters: list[str],
    concept_filters: list[str],
    limit: int = 100,
) -> dict[str, object]:
    """
    Filter stocks by 申万一级/二级 industry and/or concept membership,
    then re-compute RPS rankings within the filtered pool.
    Returns top-N stocks sorted by pool-local RPS.
    """
    industry_rows = load_industry_rows()
    concept_rows = load_concept_rows()
    rps_rows = load_rps_rows()
    security_rows = load_security_rows()

    # Build symbol → {market, name, industries (set), concepts (set)}
    symbol_map: dict[str, dict[str, object]] = {}

    for row in security_rows:
        sym = row.get("symbol") or ""
        if not sym:
            continue
        symbol_map[sym] = {
            "market": row.get("market", ""),
            "stock_name": row.get("stock_name", ""),
            "level1": set(),
            "level2": set(),
            "concepts": set(),
        }

    for row in industry_rows:
        sym = row.get("symbol") or ""
        if sym not in symbol_map:
            continue
        l1 = row.get("industry_level_1_name") or ""
        l2 = row.get("industry_level_2_name") or ""
        if l1:
            symbol_map[sym]["level1"].add(l1)
        if l2:
            symbol_map[sym]["level2"].add(l2)

    for row in concept_rows:
        sym = row.get("symbol") or ""
        if sym not in symbol_map:
            continue
        cn = row.get("concept_name") or ""
        if cn:
            symbol_map[sym]["concepts"].add(cn)

    # Apply filters
    level1_set = {x.strip() for x in level1_filters}
    level2_set = {x.strip() for x in level2_filters}
    concept_set = {x.strip() for x in concept_filters}

    pool_symbols: set[str] = set()
    for sym, info in symbol_map.items():
        if level1_set and not (info["level1"] & level1_set):
            continue
        if level2_set and not (info["level2"] & level2_set):
            continue
        if concept_set and not (info["concepts"] & concept_set):
            continue
        pool_symbols.add(sym)

    if not pool_symbols:
        return {
            "ok": True,
            "pool_size": 0,
            "filter_summary": {
                "level1": sorted(level1_set),
                "level2": sorted(level2_set),
                "concepts": sorted(concept_set),
            },
            "results": [],
        }

    # Build RPS lookup within pool
    sym_rps: dict[str, dict[str, float | None]] = {}
    for row in rps_rows:
        sym = row.get("symbol") or ""
        if sym in pool_symbols:
            sym_rps[sym] = {
                "rps_20": row.get("rps_20"),
                "rps_50": row.get("rps_50"),
                "rps_120": row.get("rps_120"),
                "rps_250": row.get("rps_250"),
                "return_20_pct": row.get("return_20_pct"),
                "return_50_pct": row.get("return_50_pct"),
                "return_120_pct": row.get("return_120_pct"),
                "return_250_pct": row.get("return_250_pct"),
            }

    # Sort by pool-local RPS: prefer rps_20, fall back to rps_50
    ranked = []
    for sym in pool_symbols:
        rps_info = sym_rps.get(sym, {})
        rps_20 = rps_info.get("rps_20") if rps_info else None
        rps_50 = rps_info.get("rps_50") if rps_info else None
        rps_120 = rps_info.get("rps_120") if rps_info else None
        rps_250 = rps_info.get("rps_250") if rps_info else None
        ret_20 = rps_info.get("return_20_pct") if rps_info else None
        ret_50 = rps_info.get("return_50_pct") if rps_info else None
        ret_120 = rps_info.get("return_120_pct") if rps_info else None
        ret_250 = rps_info.get("return_250_pct") if rps_info else None
        sort_key = rps_20 if rps_20 is not None else (rps_50 if rps_50 is not None else -1.0)
        ranked.append((sort_key, sym, symbol_map[sym], rps_20, rps_50, rps_120, rps_250, ret_20, ret_50, ret_120, ret_250))

    ranked.sort(key=lambda x: x[0], reverse=True)

    results = []
    for sort_key, sym, info, rps_20, rps_50, rps_120, rps_250, ret_20, ret_50, ret_120, ret_250 in ranked[:limit]:
        results.append({
            "symbol": sym,
            "market": info["market"],
            "stock_name": info["stock_name"],
            "rps_20": rps_20,
            "rps_50": rps_50,
            "rps_120": rps_120,
            "rps_250": rps_250,
            "return_20_pct": ret_20,
            "return_50_pct": ret_50,
            "return_120_pct": ret_120,
            "return_250_pct": ret_250,
            "level1": sorted(info["level1"]),
            "level2": sorted(info["level2"]),
            "concepts": sorted(info["concepts"])[:10],  # cap for response size
        })

    return {
        "ok": True,
        "pool_size": len(pool_symbols),
        "filter_summary": {
            "level1": sorted(level1_set),
            "level2": sorted(level2_set),
            "concepts": sorted(concept_set),
        },
        "results": results,
    }


# =============================================================================
# Financial Score Engine
# =============================================================================

from pathlib import Path as _Path

try:
    from mootdx.financial.financial import FinancialReader as _FR
except ModuleNotFoundError as exc:
    _FR = None
    _MOOTDX_IMPORT_ERROR = exc
else:
    _MOOTDX_IMPORT_ERROR = None

_TDX_DIR = "/mnt/c/new_tdx64"
_PROJECT_ROOT = _Path(__file__).resolve().parents[2]
_INDUSTRY_FILE = _PROJECT_ROOT / "data/derived/datasets/final/dataset_stock_industry_current.json"

# ---------------------------------------------------------------------------
# Dimension weights
# ---------------------------------------------------------------------------
_DIM_WEIGHTS = {
    "profitability":  0.25,
    "growth":         0.20,
    "operating":      0.15,
    "cashflow":       0.20,
    "solvency":       0.10,
    "asset_quality":  0.10,
}

# ---------------------------------------------------------------------------
# Sub-indicator definitions
#   (key, dim, field_or_None, higher_better, zero_penalty)
# ---------------------------------------------------------------------------
_SUB_DEFS = [
    # profitability
    ("roe_ex",           "profitability", None,                                           True,  True),
    ("net_margin",       "profitability", "净利润率(非金融类指标)",                         True,  True),
    ("roe_pct",          "profitability", "净资产收益率",                                  True,  True),
    # growth (YoY)
    ("revenue_growth",   "growth",        "营业收入增长率(%)",                              True,  False),
    ("profit_growth",    "growth",        "净利润增长率(%)",                               True,  False),
    ("ex_profit_growth", "growth",        "扣非净利润同比(%)",                             True,  False),
    # operating (industry ranking needed)
    ("ar_days",          "operating",     "应收帐款周转天数(非金融类指标)",                 False, True),
    ("inv_days",         "operating",     "存货周转天数(非金融类指标)",                     False, True),
    ("asset_turn",       "operating",     "总资产周转率(非金融类指标)",                    True,  True),
    # cashflow (industry ranking needed)
    ("ocf_to_profit",    "cashflow",      None,                                            True,  True),
    ("ocf_to_rev",       "cashflow",      "经营活动产生的现金流量净额/营业收入",            True,  True),
    ("free_cf",          "cashflow",      None,                                            True,  True),
    # solvency (industry ranking needed)
    ("debt_ratio",       "solvency",      "资产负债率(%)",                                 False, True),
    ("current_ratio",    "solvency",      "流动比率(非金融类指标)",                        True,  True),
    ("quick_ratio",      "solvency",      "速动比率(非金融类指标)",                        True,  True),
    # asset quality (industry ranking needed)
    ("ar_to_asset",      "asset_quality", "应收账款",                                       False, False),
    ("inv_to_asset",     "asset_quality", "存货",                                          False, False),
    ("goodwill_ratio",   "asset_quality", "商誉",                                          False, False),
    ("impair_to_rev",    "asset_quality", "资产减值损失",                                  False, False),
]

_SUB_KEYS = [d[0] for d in _SUB_DEFS]
_SUB_INDICATOR_LABELS = {
    "roe_ex": "扣非ROE",
    "net_margin": "净利率",
    "roe_pct": "净资产收益率",
    "revenue_growth": "营收增速",
    "profit_growth": "净利润增速",
    "ex_profit_growth": "扣非增速",
    "ar_days": "应收周转天数",
    "inv_days": "存货周转天数",
    "asset_turn": "总资产周转率",
    "ocf_to_profit": "净现比",
    "ocf_to_rev": "现金流/营收",
    "free_cf": "自由现金流",
    "debt_ratio": "资产负债率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "ar_to_asset": "应收占比",
    "inv_to_asset": "存货占比",
    "goodwill_ratio": "商誉占比",
    "impair_to_rev": "减值损失率",
}
_COMPONENT_LABELS = {
    "revenue": "营业收入",
    "ex_net_profit": "扣除非经常性损益后的净利润",
    "op_cf": "经营活动产生的现金流量净额",
    "net_profit": "归属于母公司所有者的净利润",
    "capex": "购建固定资产、无形资产和其他长期资产支付的现金",
    "total_debt": "负债合计",
    "total_assets": "资产总计",
    "equity": "归属于母公司股东权益(资产负债表)",
    "ar": "应收账款",
    "inventory": "存货",
    "goodwill": "商誉",
    "impair_loss": "资产减值损失",
    "current_assets": "流动资产合计",
    "current_liabilities": "流动负债合计",
    "operating_cost": "营业成本",
}
_SUB_INDICATOR_COMPONENT_KEYS = {
    "roe_ex": ["ex_net_profit", "equity"],
    "net_margin": ["net_profit", "revenue"],
    "roe_pct": ["net_profit", "equity"],
    "revenue_growth": ["revenue"],
    "profit_growth": ["net_profit"],
    "ex_profit_growth": ["ex_net_profit"],
    "ocf_to_profit": ["op_cf", "net_profit"],
    "ocf_to_rev": ["op_cf", "revenue"],
    "free_cf": ["op_cf", "capex"],
    "ar_to_asset": ["ar", "total_assets"],
    "inv_to_asset": ["inventory", "total_assets"],
    "goodwill_ratio": ["goodwill", "total_assets"],
    "impair_to_rev": ["impair_loss", "revenue"],
    "ar_days": ["ar", "revenue"],
    "inv_days": ["inventory", "operating_cost"],
    "asset_turn": ["revenue", "total_assets"],
    "debt_ratio": ["total_debt", "total_assets"],
    "current_ratio": ["current_assets", "current_liabilities"],
    "quick_ratio": ["current_assets", "inventory", "current_liabilities"],
}
_CROSS_INDUSTRY_SENSITIVE_DIMS = {"operating", "solvency", "asset_quality"}
_PURE_MARKET_DIMS = {"profitability", "growth", "cashflow"}


def blend_market_scores_with_industry(market_scores, industry_scores):
    """Blend snapshot market scores with industry scores for selected dimensions."""
    adjusted = {}
    for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
        market_value = float(market_scores.get(sub_key, 0.0) or 0.0)
        industry_value = industry_scores.get(sub_key)
        if dim in _CROSS_INDUSTRY_SENSITIVE_DIMS and industry_value is not None:
            adjusted[sub_key] = round((float(industry_value) * 0.7) + (market_value * 0.3), 4)
        else:
            adjusted[sub_key] = market_value
    return adjusted


def _build_score_methodology(market_score_mode):
    return {
        "market_score_mode": market_score_mode,
        "weights": dict(_DIM_WEIGHTS),
        "dimensions": list(_DIM_WEIGHTS.keys()),
        "blended_dimensions": sorted(_CROSS_INDUSTRY_SENSITIVE_DIMS),
        "pure_market_dimensions": sorted(_PURE_MARKET_DIMS),
    }

# ---------------------------------------------------------------------------
# Load industry mapping (申万二级)
# ---------------------------------------------------------------------------
from functools import lru_cache

@lru_cache(maxsize=1)
def _load_industry_map():
    data = json.loads(_INDUSTRY_FILE.read_text(encoding="utf-8"))
    out = {}
    for r in data:
        out[(r["market"], r["symbol"])] = (r["industry_level_2_name"] or "", r["industry_level_1_name"] or "")
    return out

# ---------------------------------------------------------------------------
# Full-market financial snapshot (pre-computed percentiles, loaded at startup)
# ---------------------------------------------------------------------------
_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"


def _require_mootdx() -> None:
    if _FR is None:
        raise RuntimeError(
            "Financial functionality requires the optional dependency 'mootdx'. "
            "Install it to read Tongdaxin financial data files."
        ) from _MOOTDX_IMPORT_ERROR

@lru_cache(maxsize=1)
def _load_financial_snapshot():
    """
    Load the pre-built full-market financial snapshot.
    Scans for the latest financial_snapshot_*.json in _SNAPSHOT_DIR.
    Returns None if no snapshot is available.
    """
    if not _SNAPSHOT_DIR.is_dir():
        return None
    files = sorted(_SNAPSHOT_DIR.glob("financial_snapshot_*.json"), reverse=True)
    if not files:
        return None
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
        return data
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Find latest valid financial file
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Find all available quarterly financial .dat files (newest first)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _all_financial_files():
    """
    Returns sorted list of (report_date_str, file_path) for all gpcw*.dat files.
    Uses the filename convention: gpcwYYYYMMDD.dat → YYYYMMDD
    """
    cw_dir = _Path(_TDX_DIR) / "vipdoc/cw"
    files = []
    for p in cw_dir.glob("gpcw*.dat"):
        name = p.stem  # e.g. "gpcw20260331"
        if len(name) == 12:
            date_str = name[4:]  # "20260331"
            try:
                int(date_str)
                files.append((date_str, str(p)))
            except ValueError:
                pass
    files.sort(reverse=True)  # newest first
    return files

# ---------------------------------------------------------------------------
# Financial data access — truly on-demand, incremental file loading.
# For a batch of stocks, we load files newest-first and stop as soon as
# each stock is found.  The file-level DataFrame cache avoids re-loading.
# ---------------------------------------------------------------------------

# Module-level cache: file_path → (date_str, DataFrame)
_FILE_DF_CACHE = {}

@lru_cache(maxsize=1)
def _all_financial_files():
    """
    Returns sorted list of (report_date_str, file_path) for all gpcw*.dat files.
    Uses the filename convention: gpcwYYYYMMDD.dat → YYYYMMDD
    """
    cw_dir = _Path(_TDX_DIR) / "vipdoc/cw"
    files = []
    for p in cw_dir.glob("gpcw*.dat"):
        name = p.stem  # e.g. "gpcw20260331"
        if len(name) == 12:
            date_str = name[4:]  # "20260331"
            try:
                int(date_str)
                files.append((date_str, str(p)))
            except ValueError:
                pass
    files.sort(reverse=True)  # newest first
    return files


def _load_file(fp):
    """Load and cache a single .dat file, return (date_str, DataFrame) or None."""
    if fp in _FILE_DF_CACHE:
        return _FILE_DF_CACHE[fp]
    try:
        _require_mootdx()
        # Extract date from filename
        name = Path(fp).stem
        date_str = name[4:]
        df = _FR.to_data(fp)
        if df is not None and not df.empty and len(df) > 0:
            _FILE_DF_CACHE[fp] = (date_str, df)
            return _FILE_DF_CACHE[fp]
    except Exception:
        pass
    return None


def _find_stock_entry(market, symbol, stop_on_first=False):
    """
    Search files newest-first for a specific (market, symbol).
    If stop_on_first=True: return on first match (for single-stock queries).
    Returns {'row': ..., 'report_date': ...} or None.
    """
    all_files = _all_financial_files()
    for date_str, fp in all_files:
        result = _load_file(fp)
        if result is None:
            continue
        _, df = result
        for sym, row in df.iterrows():
            if not hasattr(row, "get"):
                continue
            sym_str = str(sym)
            # Match market
            if market == "sh" and sym_str.startswith(("6", "5", "9")):
                pass
            elif market == "sz" and sym_str.startswith(("0", "1", "2", "3", "4", "8")):
                pass
            else:
                continue
            if sym_str == symbol:
                return {"row": row, "report_date": date_str}
        if stop_on_first:
            # For single-stock: we still need to scan all files because we don't
            # know which one has it without scanning. But we can return early
            # once found.
            break
    return None


def _batch_load_for_stocks(market_symbols):
    """
    For a batch of (market, symbol) pairs, load the minimum set of files needed.
    Files are loaded newest-first; each stock uses the first file it appears in.
    Uses direct pandas index lookup for O(1) per symbol.
    Returns: { (market, symbol): {'row': ..., 'report_date': ...} }
    """
    all_files = _all_financial_files()
    found = {}
    needed = {(m, s) for m, s in market_symbols}

    for date_str, fp in all_files:
        if not needed:
            break

        result = _load_file(fp)
        if result is None:
            continue
        _, df = result

        # The DataFrame index is the stock code (str), e.g. '600519'
        # Index is already string type
        for market, symbol in list(needed):
            key = (market, symbol)
            # Try both with and without leading zeros for sz market
            idx_candidates = [symbol]
            # For sz symbols like '000001', the index might be '1' or '000001'
            if market == "sz" and len(symbol) == 6:
                idx_candidates.append(symbol.lstrip('0'))
                idx_candidates.append(symbol[1:] if symbol.startswith('0') else symbol)

            row = None
            for idx in idx_candidates:
                if idx in df.index:
                    row = df.loc[idx]
                    break

            if row is not None:
                found[key] = {"row": row, "report_date": date_str}
                needed.discard(key)

    return found

# ---------------------------------------------------------------------------
# Extract scalar float from pandas Series or scalar
# ---------------------------------------------------------------------------
def _pick(v):
    """
    Extract a scalar float from a pandas Series (handles duplicate column names
    where ``row.get(col)`` returns a multi-value Series), a numpy scalar, or a
    raw Python numeric value.
    """
    if v is None:
        return None
    # If it's a pandas object with an iloc indexer, dig down until we hit a scalar
    while hasattr(v, "iloc"):
        if len(v) == 0:
            return None
        v = v.iloc[0]
    # numpy / pandas scalars have .item() that returns a plain Python type
    if hasattr(v, "item"):
        v = v.item()
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# ---------------------------------------------------------------------------
# Derive sub-indicator raw values from a financial row dict
# ---------------------------------------------------------------------------
def _derive_sub_fields(frow, frow_prev):
    def vv(col):
        v = frow.get(col)
        return _pick(v)

    net_profit    = vv("归属于母公司所有者的净利润")
    ex_net_prof   = vv("扣除非经常性损益后的净利润")
    revenue       = vv("营业收入")
    op_cf         = vv("经营活动产生的现金流量净额")
    total_assets  = vv("资产总计")
    total_debt    = vv("负债合计")
    equity        = vv("归属于母公司股东权益(资产负债表)")
    ar            = vv("应收账款")
    inv           = vv("存货")
    goodwill      = vv("商誉")
    impair_loss   = vv("资产减值损失")
    capex         = vv("购建固定资产、无形资产和其他长期资产支付的现金")
    op_cost       = vv("营业成本")
    cur_assets    = vv("流动资产合计")
    cur_liab      = vv("流动负债合计")
    op_profit_v   = vv("营业利润")

    # Derive 营业成本 if missing
    if op_cost is None and revenue is not None and op_profit_v is not None:
        op_cost = revenue - op_profit_v

    out = {}

    # profitability
    if equity and ex_net_prof is not None and equity != 0:
        out["roe_ex"] = ex_net_prof / equity * 100.0
    else:
        out["roe_ex"] = None
    out["net_margin"]   = vv("净利润率(非金融类指标)")
    out["roe_pct"] = vv("净资产收益率")

    # growth (YoY)
    out["revenue_growth"]   = vv("营业收入增长率(%)")
    out["profit_growth"]    = vv("净利润增长率(%)")
    out["ex_profit_growth"] = vv("扣非净利润同比(%)")

    # operating
    out["ar_days"]    = vv("应收帐款周转天数(非金融类指标)")
    out["inv_days"]   = vv("存货周转天数(非金融类指标)")
    out["asset_turn"] = vv("总资产周转率(非金融类指标)")

    # cashflow
    if op_cf is not None and net_profit and net_profit != 0:
        out["ocf_to_profit"] = op_cf / net_profit
    else:
        out["ocf_to_profit"] = None
    out["ocf_to_rev"] = vv("经营活动产生的现金流量净额/营业收入")
    if op_cf is not None and capex is not None:
        out["free_cf"] = op_cf - capex
    else:
        out["free_cf"] = None

    # solvency
    out["debt_ratio"]    = vv("资产负债率(%)")
    out["current_ratio"] = vv("流动比率(非金融类指标)")
    out["quick_ratio"]   = vv("速动比率(非金融类指标)")

    # asset quality
    if ar and total_assets and total_assets != 0:
        out["ar_to_asset"] = ar / total_assets * 100.0
    else:
        out["ar_to_asset"] = None
    if inv and total_assets and total_assets != 0:
        out["inv_to_asset"] = inv / total_assets * 100.0
    else:
        out["inv_to_asset"] = None
    if goodwill and total_assets and total_assets != 0:
        out["goodwill_ratio"] = goodwill / total_assets * 100.0
    else:
        out["goodwill_ratio"] = None
    if impair_loss and revenue and revenue != 0:
        out["impair_to_rev"] = impair_loss / revenue * 100.0
    else:
        out["impair_to_rev"] = None

    return out

# ---------------------------------------------------------------------------
# Compute industry percentile ranking
# ---------------------------------------------------------------------------
def _industry_percentile(raw_values, higher_better, zero_penalty):
    """
    Compute industry-relative percentile scores for a set of raw values.

    For zero_penalty indicators:
      - higher_better=True  (e.g. ROE, margin): 0 is treated as missing (penalised)
      - higher_better=False (e.g. ar_days, debt_ratio): 0 is the IDEAL value (top rank)
        because it means "no such liability/asset" — this is critical for metrics like
        ar_days where a wine/consumer business with zero receivables is superior.
    """
    valid = {k: v for k, v in raw_values.items() if v is not None and v == v}
    if not valid:
        return {k: 0.0 for k in raw_values}

    if zero_penalty:
        if higher_better:
            # Higher-is-better: 0 means absent/zero — penalise
            penalized = {k: None if v <= 0 else v for k, v in valid.items()}
        else:
            # Lower-is-better: 0 means ideal (no receivables / no debt) — do NOT penalise
            # Only None if the value itself was None (already excluded above)
            penalized = valid
        valid = {k: v for k, v in penalized.items() if v is not None}
        if not valid:
            return {k: 0.0 for k in raw_values}

    ascending = not higher_better
    sorted_keys = sorted(valid, key=lambda k: float(valid[k]), reverse=(not ascending))
    universe_size = len(sorted_keys)
    result = {}
    for rank_idx, k in enumerate(sorted_keys):
        pct = ((universe_size - rank_idx) / universe_size) * 100.0
        result[k] = round(pct, 4)
    return result

# ---------------------------------------------------------------------------
# Compute scores for one industry group
# ---------------------------------------------------------------------------
def _score_industry_group(stocks_with_data, stocks_without_data):
    raw_by_indicator = {k: {} for k in _SUB_KEYS}

    for market, symbol, frow, frow_prev in stocks_with_data:
        key = (market, symbol)
        fields = _derive_sub_fields(frow, frow_prev)
        for sub_key in _SUB_KEYS:
            raw_by_indicator[sub_key][key] = fields.get(sub_key)

    scores = {}
    for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
        pct_map = _industry_percentile(raw_by_indicator[sub_key], higher_better, zero_penalty)
        for market, symbol, frow, frow_prev in stocks_with_data:
            key = (market, symbol)
            scores.setdefault(key, {})[sub_key] = pct_map.get(key, 0.0)

    for market, symbol in stocks_without_data:
        key = (market, symbol)
        scores[key] = {k: 0.0 for k in _SUB_KEYS}

    return scores
# ---------------------------------------------------------------------------
# Public API: batch scores
# ---------------------------------------------------------------------------
def compute_financial_scores(market_symbols):
    """
    Compute financial scores for a batch of (market, symbol) pairs.
    Uses the pre-built full-market snapshot for all percentile calculations,
    falling back to on-demand file loading if no snapshot exists.
    """
    snap = _load_financial_snapshot()

    if snap is not None:
        # Fast path: use pre-computed snapshot
        scores = {}
        for market, symbol in market_symbols:
            key_str = f"{market}:{symbol}"
            entry = snap.get("scores", {}).get(key_str)
            if entry:
                market_sub_indicators = entry.get("sub_indicators", {})
                industry_sub_indicators = entry.get("ind_sub_indicators", {})
                sub_indicators = blend_market_scores_with_industry(
                    market_sub_indicators,
                    industry_sub_indicators,
                )
                dim_scores_raw = {}
                for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
                    dim_scores_raw.setdefault(dim, []).append(sub_indicators.get(sub_key, 0.0))
                weighted = {}
                for dim, vals in dim_scores_raw.items():
                    avg = sum(vals) / len(vals) if vals else 0.0
                    weighted[dim] = round(avg * _DIM_WEIGHTS.get(dim, 0.0), 2)
                total = round(sum(weighted.values()), 2)
                scores[(market, symbol)] = {
                    "report_date": entry.get("report_date", ""),
                    "announce_date": entry.get("announce_date", ""),
                    # Flatten blended market-facing sub-indicators and add dim_scores + total_score.
                    **{k: v for k, v in sub_indicators.items()},
                    "dim_scores": weighted,
                    "total_score": total,
                    # 行业排名（也在快照里预计算好了）
                    "ind_sub_indicators": industry_sub_indicators,
                    "ind_dim_scores": entry.get("ind_dim_scores", {}),
                    "ind_total_score": entry.get("ind_total_score", 0.0),
                    "raw_sub_indicators": entry.get("raw_sub_indicators", {}),
                    "prev_raw_sub_indicators": entry.get("prev_raw_sub_indicators", {}),
                    "latest_period": entry.get("latest_period", ""),
                    "score_methodology": _build_score_methodology("industry_adjusted_market_view"),
                }
        return {"scores": scores, "source": "snapshot", "report_date": snap.get("report_date", "")}

    # Fallback: on-demand loading (original behaviour)
    industry_map = _load_industry_map()

    # Group by industry
    industry_groups = {}
    no_industry = []
    for market, symbol in market_symbols:
        ind2, ind1 = industry_map.get((market, symbol), ("", ""))
        if ind2:
            industry_groups.setdefault(ind2, []).append((market, symbol))
        else:
            no_industry.append((market, symbol))

    # Load financial data for all stocks in this batch (one pass, incremental)
    fin_entries = _batch_load_for_stocks(market_symbols)

    stocks_by_group = {}
    report_dates = {}
    for ind2, pairs in industry_groups.items():
        with_data = []
        without_data = []
        for market, symbol in pairs:
            entry = fin_entries.get((market, symbol))
            if entry is not None:
                with_data.append((market, symbol, entry["row"], None))
                report_dates[(market, symbol)] = entry["report_date"]
            else:
                without_data.append((market, symbol))
        if with_data:
            stocks_by_group[ind2] = (with_data, without_data)

    all_scores = {}
    for ind2, (with_data, without_data) in stocks_by_group.items():
        grp_scores = _score_industry_group(with_data, without_data)
        all_scores.update(grp_scores)

    # Fallback for stocks without industry
    if no_industry:
        entries_with = []
        for m, s in no_industry:
            entry = fin_entries.get((m, s))
            if entry is not None:
                entries_with.append((m, s, entry["row"], None))
                report_dates[(m, s)] = entry["report_date"]
        global_without = [(m, s) for m, s in no_industry if (m, s) not in report_dates]
        if entries_with:
            gs = _score_industry_group(entries_with, global_without)
            all_scores.update(gs)

    # Compute weighted dimension scores and total
    # Sub-indicator scores are 0-100 percentile; each dim score = avg(sub_scores) * dim_weight
    result = {}
    for key, sub_scores in all_scores.items():
        dim_totals = {}
        dim_counts = {}
        for sub_key, pct_score in sub_scores.items():
            dim = next(d[1] for d in _SUB_DEFS if d[0] == sub_key)
            dim_totals[dim] = dim_totals.get(dim, 0.0) + pct_score
            dim_counts[dim] = dim_counts.get(dim, 0) + 1

        dim_scores = {}
        for dim, total in dim_totals.items():
            count = dim_counts[dim]
            dim_avg = total / count if count > 0 else 0.0
            dim_scores[dim] = round(dim_avg * _DIM_WEIGHTS[dim], 4)

        total = sum(dim_scores.values())
        entry = {
            **sub_scores,
            "dim_scores": dim_scores,
            "total_score": round(total, 4),
            "score_methodology": _build_score_methodology("pure_market_percentile"),
        }
        rd = report_dates.get(key)
        if rd:
            entry["report_date"] = rd
        result[key] = entry

    return {"ok": True, "scores": result}

# -----------------------------------------------------------------------
# Lookup stock name from market+symbol (memoised via load_security_rows)
# -----------------------------------------------------------------------
@lru_cache(maxsize=1)
def _stock_name_lookup():
    rows = load_security_rows()
    return {(r["market"], r["symbol"]): r["stock_name"] for r in rows}


def _format_pct_value(value: object) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _format_ratio_value(value: object, unit: str = "倍") -> str:
    try:
        return f"{float(value):.2f}{unit}"
    except (TypeError, ValueError):
        return "—"


def _build_latest_report_analysis(score_data: dict[str, object], raw_sub_indicators: dict[str, object], prev_raw_sub_indicators: dict[str, object]) -> dict[str, list[str]]:
    strengths: list[str] = []
    risks: list[str] = []

    def pct(key: str) -> float:
        try:
            return float(score_data.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    if pct("roe_ex") >= 75:
        strengths.append(f"扣非ROE 较强（{_format_pct_value(raw_sub_indicators.get('roe_ex'))}），盈利质量在当前样本中处于较优区间。")
    if pct("profit_growth") >= 75:
        strengths.append(f"净利润增速表现突出（{_format_pct_value(raw_sub_indicators.get('profit_growth'))}），最新财报增长弹性较好。")
    if pct("ocf_to_profit") >= 70:
        strengths.append(f"净现比较好（{_format_ratio_value(raw_sub_indicators.get('ocf_to_profit'))}），利润向现金转化能力较稳。")
    if pct("free_cf") >= 80:
        strengths.append("自由现金流处于较高分位，资本开支后仍保有较好现金沉淀。")

    debt_ratio = raw_sub_indicators.get("debt_ratio")
    if debt_ratio is not None:
        try:
            debt_ratio = float(debt_ratio)
        except (TypeError, ValueError):
            debt_ratio = None
    if debt_ratio is not None and debt_ratio >= 60:
        risks.append(f"资产负债率偏高（{debt_ratio:.1f}%），后续需关注杠杆与融资压力。")
    elif pct("debt_ratio") <= 30:
        risks.append(f"资产负债率在全市场对比中不占优（{_format_pct_value(raw_sub_indicators.get('debt_ratio'))}），偿债维度仍有短板。")

    if pct("goodwill_ratio") <= 30:
        risks.append(f"商誉/资产占比偏弱（{_format_pct_value(raw_sub_indicators.get('goodwill_ratio'))}），需留意并购资产后续减值风险。")
    if pct("current_ratio") <= 35:
        risks.append(f"流动比率不高（{_format_ratio_value(raw_sub_indicators.get('current_ratio'))}），短期流动性缓冲一般。")
    if pct("asset_turn") <= 40:
        risks.append(f"总资产周转率偏弱（{_format_ratio_value(raw_sub_indicators.get('asset_turn'), '次')}），运营效率仍有提升空间。")

    for key, label in (("roe_ex", "扣非ROE"), ("profit_growth", "净利润增速"), ("ocf_to_profit", "净现比")):
        cur = raw_sub_indicators.get(key)
        prev = prev_raw_sub_indicators.get(key)
        try:
            cur_f = float(cur)
            prev_f = float(prev)
        except (TypeError, ValueError):
            continue
        if prev_f == 0:
            continue
        yoy = (cur_f - prev_f) / abs(prev_f) * 100.0
        if yoy <= -20 and len(risks) < 4:
            risks.append(f"{label} 较上年同期走弱（同比 {yoy:.1f}%），需要结合后续财报继续跟踪。")
        elif yoy >= 20 and len(strengths) < 4:
            strengths.append(f"{label} 较上年同期改善明显（同比 +{yoy:.1f}%），最新财报呈现边际向好。")

    if not strengths:
        strengths.append("最新财报暂无特别突出的高分项，整体表现以中性偏稳为主。")
    if not risks:
        risks.append("最新财报暂无特别突出的硬伤，但仍需结合后续盈利与现金流延续性观察。")

    return {"strengths": strengths[:4], "risks": risks[:4]}


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _signed_delta_text(delta: float | None, suffix: str = "", comparison_label: str = "上年同期") -> str:
    if delta is None:
        return f"缺少可比{comparison_label}数据"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.2f}{suffix}"


def _metric_change_summary(
    current: float | None,
    previous: float | None,
    *,
    suffix: str = "",
    comparison_label: str = "上年同期",
) -> dict[str, object]:
    delta = None
    if current is not None and previous is not None:
        delta = current - previous
    return {
        "current_value": current,
        "previous_value": previous,
        "delta_value": delta,
        "summary": f"当期较{comparison_label} " + _signed_delta_text(delta, suffix, comparison_label),
    }


def _previous_same_period_report_date(report_date: str) -> str | None:
    text = str(report_date or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    return f"{int(text[:4]) - 1:04d}{text[4:]}"


def _lookup_financial_row(market: str, symbol: str, report_date: str | None = None) -> tuple[str, object] | None:
    try:
        all_files = _all_financial_files()
    except Exception:
        return None
    if not all_files:
        return None

    idx_candidates = [symbol]
    if market == "sz" and len(symbol) == 6:
        idx_candidates.extend([symbol.lstrip("0"), symbol[1:] if symbol.startswith("0") else symbol])

    for date_str, fp in all_files:
        if report_date and date_str != report_date:
            continue
        try:
            loaded = _load_file(fp)
        except Exception:
            loaded = None
        if loaded is None:
            continue
        _loaded_date, df = loaded
        for idx in idx_candidates:
            if idx and idx in df.index:
                return date_str, df.loc[idx]
        if report_date:
            break
    return None


def _load_sub_indicator_component_context(
    market: str,
    symbol: str,
    *,
    current_report_date: str | None = None,
    previous_report_date: str | None = None,
) -> dict[str, dict[str, float | None]]:
    """
    Load supporting raw financial components for a single stock.
    Returns empty current/previous dicts when local financial data is unavailable.
    """
    empty = {"current": {}, "previous": {}}

    current_match = _lookup_financial_row(market, symbol, current_report_date)
    previous_match = _lookup_financial_row(market, symbol, previous_report_date) if previous_report_date else None

    if current_match is None and previous_match is None:
        current_match = _lookup_financial_row(market, symbol)

    if current_match is not None and previous_match is None:
        current_date = current_match[0]
        fallback_previous = None
        try:
            all_files = _all_financial_files()
        except Exception:
            all_files = []
        for date_str, _fp in all_files:
            if current_date and date_str >= current_date:
                continue
            fallback_previous = _lookup_financial_row(market, symbol, date_str)
            if fallback_previous is not None:
                break
        previous_match = fallback_previous

    if current_match is None and previous_match is None:
        return empty

    def _extract_components(frow: object | None) -> dict[str, float | None]:
        if frow is None or not hasattr(frow, "get"):
            return {}

        def vv(col: str) -> float | None:
            return _pick(frow.get(col))

        return {
            "revenue": vv("营业收入"),
            "ex_net_profit": vv("扣除非经常性损益后的净利润"),
            "op_cf": vv("经营活动产生的现金流量净额"),
            "net_profit": vv("归属于母公司所有者的净利润"),
            "capex": vv("购建固定资产、无形资产和其他长期资产支付的现金"),
            "total_debt": vv("负债合计"),
            "total_assets": vv("资产总计"),
            "equity": vv("归属于母公司股东权益(资产负债表)"),
            "ar": vv("应收账款"),
            "inventory": vv("存货"),
            "goodwill": vv("商誉"),
            "impair_loss": vv("资产减值损失"),
            "current_assets": vv("流动资产合计"),
            "current_liabilities": vv("流动负债合计"),
            "operating_cost": vv("营业成本"),
        }

    current_row = current_match[1] if current_match else None
    previous_row = previous_match[1] if previous_match else None
    return {
        "current": _extract_components(current_row),
        "previous": _extract_components(previous_row),
    }


def _load_latest_close_prices(market_symbols: list[tuple[str, str]]) -> dict[tuple[str, str], float | None]:
    prices = {(market, symbol): None for market, symbol in market_symbols}
    if not market_symbols:
        return prices

    try:
        from mootdx.reader import Reader
    except ModuleNotFoundError:
        return prices
    except Exception:
        return prices

    readers: dict[str, object] = {}
    for market, symbol in market_symbols:
        if market not in {"sh", "sz", "bj"} or not symbol:
            continue
        try:
            reader = readers.get(market)
            if reader is None:
                reader = Reader.factory(market="std", tdxdir=_TDX_DIR)
                readers[market] = reader
            daily = reader.daily(symbol=symbol)
            if daily is None or daily.empty:
                continue
            close_value = _pick(daily.iloc[-1].get("close"))
            prices[(market, symbol)] = close_value
        except Exception:
            continue
    return prices


def _build_sub_indicator_diagnostics(
    score_data: dict[str, object],
    ind_sub_indicators: dict[str, object],
    raw_sub_indicators: dict[str, object],
    prev_raw_sub_indicators: dict[str, object],
    component_context: dict[str, dict[str, object]] | None,
    ind1: str | None = None,
    ind2: str | None = None,
) -> dict[str, dict[str, object]]:
    current_components = (component_context or {}).get("current") or {}
    previous_components = (component_context or {}).get("previous") or {}
    industry_labels = [str(v) for v in (ind1, ind2) if v]
    industry_text = " / ".join(industry_labels)
    is_insurance = any(label == "保险" for label in industry_labels)
    is_non_bank_finance = any(label == "非银金融" for label in industry_labels)
    is_industrial_metal = any(label == "工业金属" for label in industry_labels)

    def attribution_metadata(template_type: str, sub_key: str) -> dict[str, object]:
        evidence_strength = "medium"
        needs_text_validation = True
        validation_sources: list[str] = ["公告正文", "MD&A"]
        if template_type == "formula_decomposition":
            evidence_strength = "high"
            needs_text_validation = False
            validation_sources = ["无需额外文本验证"]
        elif template_type == "efficiency_misalignment":
            validation_sources = ["公告正文", "财报附注"]
        elif template_type == "direct_field_signal":
            evidence_strength = "low" if sub_key == "roe_pct" else "medium"
            validation_sources = ["公告正文", "行业价格数据", "监管披露"] if sub_key == "roe_pct" else ["公告正文", "MD&A"]

        if sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth"}:
            validation_sources = ["公告正文", "MD&A", "行业景气数据"]
        elif sub_key in {"current_ratio", "quick_ratio", "debt_ratio"} and (is_insurance or is_non_bank_finance):
            validation_sources = ["公告正文", "监管披露", "财报附注"]
        elif sub_key in {"goodwill_ratio", "impair_to_rev"}:
            validation_sources = ["公告正文", "财报附注", "审计说明"] if needs_text_validation else validation_sources

        industry_scope = "全行业通用"
        if sub_key in {"inv_to_asset", "inv_days"}:
            if is_industrial_metal:
                industry_scope = "工业金属更适用，也可供其他重资产制造链横向参考"
            else:
                industry_scope = "制造业与重资产行业更适用"
        elif sub_key in {"free_cf", "revenue_growth", "profit_growth", "ex_profit_growth", "asset_turn"}:
            industry_scope = "全行业通用"
        elif sub_key in {"current_ratio", "quick_ratio", "roe_ex", "roe_pct"} and (is_insurance or is_non_bank_finance):
            industry_scope = "保险/非银金融更适合作为辅助观察，需结合负债结构与资本约束理解"
        elif sub_key == "debt_ratio" and (is_insurance or is_non_bank_finance):
            industry_scope = "保险/非银金融更适用，需结合杠杆经营与监管资本约束解读"
        elif sub_key in {"ar_days", "ar_to_asset"}:
            industry_scope = "赊销占比较高行业更适用"
        elif sub_key in {"goodwill_ratio", "impair_to_rev"}:
            industry_scope = "并购活跃或资产波动较大的行业更适用"
        return {
            "evidence_strength": evidence_strength,
            "needs_text_validation": needs_text_validation,
            "validation_sources": validation_sources,
            "industry_scope": industry_scope,
        }

    def pct_score(source: dict[str, object], key: str) -> float | None:
        return _safe_float(source.get(key))

    def risk_from_trend(current: float | None, previous: float | None, *, lower_is_better: bool = False) -> list[str]:
        if current is None or previous is None:
            return ["缺少完整的当期/上年同期对比数据"]
        if lower_is_better:
            return ["指标抬升，方向偏谨慎"] if current > previous else ["指标回落，方向改善"]
        return ["指标走弱，方向偏谨慎"] if current < previous else ["指标改善，方向偏正面"]

    def component_values(keys: list[str]) -> dict[str, dict[str, float | None]]:
        return {
            "current": {key: _safe_float(current_components.get(key)) for key in keys},
            "previous": {key: _safe_float(previous_components.get(key)) for key in keys},
        }

    def component_delta(key: str) -> float | None:
        current = _safe_float(current_components.get(key))
        previous = _safe_float(previous_components.get(key))
        if current is None or previous is None:
            return None
        return current - previous

    def component_fragment(
        key: str,
        label: str,
        *,
        positive_text: str = "抬升",
        negative_text: str = "回落",
    ) -> str:
        delta = component_delta(key)
        if delta is None:
            return ""
        if delta > 0:
            return f"{label}{positive_text}"
        if delta < 0:
            return f"{label}{negative_text}"
        return f"{label}基本持平"

    def component_weight(key: str) -> float:
        current = _safe_float(current_components.get(key))
        previous = _safe_float(previous_components.get(key))
        if current is None or previous is None:
            return 0.0
        delta = current - previous
        if previous not in (None, 0):
            return abs(delta) / abs(previous)
        return abs(delta)

    def driver_item(
        key: str,
        label: str,
        *,
        sensitivity: int,
        positive_text: str = "抬升",
        negative_text: str = "回落",
    ) -> dict[str, object] | None:
        fragment = component_fragment(key, label, positive_text=positive_text, negative_text=negative_text)
        if not fragment:
            return None
        delta = component_delta(key)
        if delta is None or delta == 0:
            effect = 0
        else:
            effect = (1 if delta > 0 else -1) * sensitivity
        return {
            "fragment": fragment,
            "effect": effect,
            "weight": component_weight(key),
        }

    def triplet_parts(
        metric_current: float | None,
        metric_previous: float | None,
        drivers: list[dict[str, object] | None],
    ) -> tuple[str, str, str] | None:
        if metric_current is None or metric_previous is None or metric_current == metric_previous:
            return None
        metric_effect = 1 if metric_current > metric_previous else -1
        usable = [driver for driver in drivers if driver]
        aligned = sorted(
            [driver for driver in usable if driver.get("effect") == metric_effect],
            key=lambda item: float(item.get("weight", 0.0)),
            reverse=True,
        )
        opposing = sorted(
            [driver for driver in usable if driver.get("effect") == -metric_effect],
            key=lambda item: float(item.get("weight", 0.0)),
            reverse=True,
        )
        neutral = sorted(
            [driver for driver in usable if driver.get("effect") == 0],
            key=lambda item: float(item.get("weight", 0.0)),
            reverse=True,
        )
        main_text = str(aligned[0]["fragment"]) if aligned else "暂无更强主因信号"
        secondary_text = str(aligned[1]["fragment"]) if len(aligned) > 1 else (
            str(neutral[0]["fragment"]) if neutral else "暂无更强同向次因"
        )
        hedge_text = str(opposing[0]["fragment"]) if opposing else "暂无明显对冲项"
        return main_text, secondary_text, hedge_text

    def triplet_summary(
        metric_current: float | None,
        metric_previous: float | None,
        drivers: list[dict[str, object] | None],
    ) -> str:
        parts = triplet_parts(metric_current, metric_previous, drivers)
        if not parts:
            return ""
        main_text, secondary_text, hedge_text = parts
        return f"主因：{main_text}；次因：{secondary_text}；对冲项：{hedge_text}。"

    def driver_aware_formula_summary(sub_key: str) -> str:
        metric_current = _safe_float(raw_sub_indicators.get(sub_key))
        metric_previous = _safe_float(prev_raw_sub_indicators.get(sub_key))
        if sub_key == "roe_ex":
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("ex_net_profit", "扣非利润", sensitivity=1),
                driver_item("equity", "归母权益", sensitivity=-1),
            ])
            if is_insurance or is_non_bank_finance:
                prefix = f"{industry_text or '保险'}公司"
                base = (
                    f"{prefix}的扣非ROE主要看盈利端相对归母权益的产出效率，"
                    "需结合承保表现、投资收益与资本消耗综合判断。"
                )
                return f"{base}{triplet}" if triplet else base
            base = "扣非ROE主要衡量盈利端相对归母权益的回报效率，反映核心利润对股东资本的占用产出。"
            return f"{base}{triplet}" if triplet else base
        if sub_key == "ocf_to_profit":
            base = "净现比反映利润表利润与经营现金流之间的匹配度，用于判断盈利含金量。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("op_cf", "经营现金流", sensitivity=1),
                driver_item("net_profit", "净利润", sensitivity=-1),
            ])
            return f"{base}{triplet}" if triplet else base
        if sub_key == "net_margin":
            base = "净利润率反映每单位营收最终能沉淀多少利润，是观察盈利兑现效率的核心切口。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("net_profit", "净利润", sensitivity=1),
                driver_item("revenue", "营收", sensitivity=-1),
            ])
            return f"{base}{triplet}" if triplet else base
        if sub_key == "ocf_to_rev":
            base = "现金流/营收反映收入转化为经营现金流的效率，用于观察销售回笼质量。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("op_cf", "经营现金流", sensitivity=1),
                driver_item("revenue", "营收", sensitivity=-1),
            ])
            return f"{base}{triplet}" if triplet else base
        if sub_key == "free_cf":
            base = "自由现金流聚焦经营现金流扣除资本开支后的现金沉淀能力，可用于判断自我造血空间。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("op_cf", "经营现金流", sensitivity=1),
                driver_item("capex", "资本开支", sensitivity=-1, positive_text="扩张", negative_text="收缩"),
            ])
            return f"{base}{triplet}" if triplet else base
        if sub_key == "ar_to_asset":
            base = "应收占比反映资产中被客户信用占用的比例，用于观察赊销扩张与资产沉淀压力。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("ar", "应收账款", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            return f"{base}{triplet}" if triplet else base
        if sub_key == "inv_to_asset":
            if is_industrial_metal:
                base = "工业金属企业的存货占比可用于观察资源备货、在产品与产成品沉淀，对资产周转和价格波动都较敏感。"
            else:
                base = "存货占比反映资产中被备货和在制品占用的比例，可用于观察库存沉淀压力。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("inventory", "存货", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            return f"{base}{triplet}" if triplet else base
        if sub_key == "goodwill_ratio":
            base = "商誉占比反映并购形成资产在总资产中的占用程度，比例偏高通常意味着后续减值敏感性更强。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("goodwill", "商誉", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            return f"{base}{triplet}" if triplet else base
        if sub_key == "impair_to_rev":
            base = "减值占比反映收入中被资产减值侵蚀的部分，可用于观察资产质量和利润稳定性。"
            triplet = triplet_summary(metric_current, metric_previous, [
                driver_item("impair_loss", "减值损失", sensitivity=1),
                driver_item("revenue", "营收", sensitivity=-1),
            ])
            return f"{base}{triplet}" if triplet else base
        return ""

    def formula_impact_triplet_lines(sub_key: str, metric_current: float | None, metric_previous: float | None) -> list[str]:
        if sub_key == "free_cf":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("op_cf", "经营现金流", sensitivity=1),
                driver_item("capex", "资本开支", sensitivity=-1, positive_text="扩张", negative_text="收缩"),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}意味着可支配现金与资本配置空间首先承压。",
                f"次影响：{secondary_text}会继续影响分红、回购与扩产弹性。",
                f"缓冲项：{hedge_text}对现金沉淀压力形成一定缓冲。",
            ]
        if sub_key == "ocf_to_profit":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("op_cf", "经营现金流", sensitivity=1),
                driver_item("net_profit", "净利润", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变利润兑现为现金的含金量判断。",
                f"次影响：{secondary_text}继续影响现金流质量评分弹性。",
                f"缓冲项：{hedge_text}对现金兑现压力形成一定对冲。",
            ]
        if sub_key == "net_margin":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("net_profit", "净利润", sensitivity=1),
                driver_item("revenue", "营收", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变每单位营收的利润沉淀效率。",
                f"次影响：{secondary_text}继续影响盈利能力评分的稳定性。",
                f"缓冲项：{hedge_text}对利润率波动形成一定缓冲。",
            ]
        if sub_key == "ocf_to_rev":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("op_cf", "经营现金流", sensitivity=1),
                driver_item("revenue", "营收", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变销售回笼效率判断。",
                f"次影响：{secondary_text}继续影响现金流质量与收入含金量评估。",
                f"缓冲项：{hedge_text}对回款压力形成一定对冲。",
            ]
        if sub_key == "ar_to_asset":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("ar", "应收账款", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变资产被信用占用的压力判断。",
                f"次影响：{secondary_text}继续影响回款风险与资产质量预期。",
                f"缓冲项：{hedge_text}对应收占压形成一定缓冲。",
            ]
        if sub_key == "inv_to_asset":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("inventory", "存货", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            prefix = "库存沉淀压力" if not is_industrial_metal else "备库与库存沉淀压力"
            return [
                f"主影响：{main_text}会首先改变{prefix}判断。",
                f"次影响：{secondary_text}继续影响周转效率与资产质量预期。",
                f"缓冲项：{hedge_text}对库存占压形成一定缓冲。",
            ]
        if sub_key == "goodwill_ratio":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("goodwill", "商誉", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变商誉占比对应的减值敏感度。",
                f"次影响：{secondary_text}继续影响市场对并购资产质量的判断。",
                f"缓冲项：{hedge_text}对潜在减值压力形成一定缓冲。",
            ]
        if sub_key == "impair_to_rev":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("impair_loss", "减值损失", sensitivity=1),
                driver_item("revenue", "营收", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变利润表对资产质量折价的压力。",
                f"次影响：{secondary_text}继续影响市场对盈利稳定性的判断。",
                f"缓冲项：{hedge_text}对减值冲击形成一定缓冲。",
            ]
        return []

    def efficiency_impact_triplet_lines(sub_key: str, metric_current: float | None, metric_previous: float | None) -> list[str]:
        if sub_key == "debt_ratio":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("total_debt", "负债规模", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变杠杆与偿债压力判断。",
                f"次影响：{secondary_text}继续影响融资空间与财务弹性预期。",
                f"缓冲项：{hedge_text}对杠杆抬升压力形成一定缓冲。",
            ]
        if sub_key == "ar_days":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("ar", "应收账款", sensitivity=1),
                driver_item("revenue", "营收", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变现金回笼节奏判断。",
                f"次影响：{secondary_text}继续影响坏账敏感度与运营效率预期。",
                f"缓冲项：{hedge_text}对应收周转压力形成一定缓冲。",
            ]
        if sub_key == "inv_days":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("inventory", "存货", sensitivity=1),
                driver_item("operating_cost", "营业成本", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            prefix = "产销节奏" if not is_industrial_metal else "备库与产销节奏"
            return [
                f"主影响：{main_text}会首先改变{prefix}与库存消化判断。",
                f"次影响：{secondary_text}继续影响周转效率与减值敏感度预期。",
                f"缓冲项：{hedge_text}对库存周转压力形成一定缓冲。",
            ]
        if sub_key == "asset_turn":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("revenue", "营收", sensitivity=1),
                driver_item("total_assets", "总资产", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            return [
                f"主影响：{main_text}会首先改变资产使用效率判断。",
                f"次影响：{secondary_text}继续影响运营效率评分与回报率预期。",
                f"缓冲项：{hedge_text}对周转效率压力形成一定缓冲。",
            ]
        if sub_key == "current_ratio":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("current_assets", "流动资产", sensitivity=1),
                driver_item("current_liabilities", "流动负债", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            if is_insurance:
                return [
                    f"主影响：{main_text}会首先改变保险负债对应的短期流动性观察。",
                    f"次影响：{secondary_text}继续影响资产配置与久期匹配评估。",
                    f"缓冲项：{hedge_text}对流动性压力形成一定缓冲。",
                ]
            return [
                f"主影响：{main_text}会首先改变短期偿债缓冲判断。",
                f"次影响：{secondary_text}继续影响流动性安全边际评估。",
                f"缓冲项：{hedge_text}对短债压力形成一定缓冲。",
            ]
        if sub_key == "quick_ratio":
            parts = triplet_parts(metric_current, metric_previous, [
                driver_item("current_assets", "流动资产", sensitivity=1),
                driver_item("current_liabilities", "流动负债", sensitivity=-1),
                driver_item("inventory", "存货", sensitivity=-1),
            ])
            if not parts:
                return []
            main_text, secondary_text, hedge_text = parts
            if is_insurance:
                return [
                    f"主影响：{main_text}会首先改变保险负债对应的高流动性资产覆盖判断。",
                    f"次影响：{secondary_text}继续影响可快速变现资产配置评估。",
                    f"缓冲项：{hedge_text}对速动性压力形成一定缓冲。",
                ]
            return [
                f"主影响：{main_text}会首先改变高流动资产覆盖短债的判断。",
                f"次影响：{secondary_text}继续影响速动性安全边际评估。",
                f"缓冲项：{hedge_text}对速动比率压力形成一定缓冲。",
            ]
        return []

    def formula_summary(sub_key: str) -> str:
        if sub_key == "roe_ex":
            return driver_aware_formula_summary("roe_ex")
        if sub_key == "net_margin":
            return driver_aware_formula_summary("net_margin")
        if sub_key == "ocf_to_profit":
            return driver_aware_formula_summary("ocf_to_profit")
        if sub_key == "ocf_to_rev":
            return driver_aware_formula_summary("ocf_to_rev")
        if sub_key == "free_cf":
            return driver_aware_formula_summary("free_cf")
        if sub_key == "ar_to_asset":
            return driver_aware_formula_summary("ar_to_asset")
        if sub_key == "inv_to_asset":
            return driver_aware_formula_summary("inv_to_asset")
        if sub_key == "goodwill_ratio":
            return driver_aware_formula_summary("goodwill_ratio")
        if sub_key == "impair_to_rev":
            return driver_aware_formula_summary("impair_to_rev")
        return ""

    def period_summary(sub_key: str) -> str:
        if sub_key == "revenue_growth":
            return "收入动能通过当期与上年同期营收增速对比来观察，可直接反映需求扩张或收缩的方向。"
        if sub_key == "profit_growth":
            return "利润释放节奏通过当期与上年同期净利润增速对比来观察，可判断盈利弹性的变化。"
        if sub_key == "ex_profit_growth":
            return "核心经营改善程度通过扣非利润增速的期间对比来观察，更能剔除非经常性扰动。"
        return ""

    def efficiency_summary(sub_key: str) -> str:
        if sub_key == "ar_days":
            return "应收周转天数用于观察回款节奏与收入确认是否匹配，天数拉长往往意味着资金占用上升。"
        if sub_key == "inv_days":
            if is_industrial_metal:
                return "工业金属链条的存货周转天数用于观察产销节奏、备库安排与成本结转是否匹配。"
            return "存货周转天数用于观察产销节奏与库存消化是否匹配，天数抬升通常意味着周转放慢。"
        if sub_key == "asset_turn":
            return "总资产周转率用于观察收入扩张与资产投入的匹配度，反映资产使用效率。"
        if sub_key == "debt_ratio":
            return "资产负债率用于观察负债扩张与资产承接能力是否匹配，能反映杠杆使用强度。"
        if sub_key == "current_ratio":
            if is_insurance:
                return "保险公司的流动比率更适合作为补充观察，需结合负债久期、赔付准备和资产配置结构综合判断。"
            return "流动比率用于观察流动资产对流动负债的覆盖程度，是短期偿债缓冲的重要刻画。"
        if sub_key == "quick_ratio":
            if is_insurance:
                return "保险公司的速动比率更适合作为补充观察，需结合保险负债特征与可快速变现资产配置一并评估。"
            return "速动比率用于观察剔除存货后的流动性覆盖能力，更强调高流动资产的短债保障。"
        return ""

    def direct_summary(sub_key: str) -> str:
        if sub_key == "roe_pct":
            if is_insurance or is_non_bank_finance:
                prefix = f"{industry_text or '保险'}行业"
                return f"{prefix}的净资产收益率需要结合投资收益、承保利润和资本运用效率一起看，能直接反映股东回报水平。"
            return "净资产收益率直接反映股东资本的回报水平，是观察综合盈利能力的核心读数。"
        return ""

    formula_specs = {
        "roe_ex": {
            "summary": formula_summary("roe_ex"),
            "components": ["ex_net_profit", "equity"],
            "impact_summary": "扣非利润相对股东权益的产出效率影响盈利质量评分。",
            "suffix": "%",
        },
        "net_margin": {
            "summary": formula_summary("net_margin"),
            "components": ["net_profit", "revenue"],
            "impact_summary": "每单位营收沉淀利润的能力影响盈利能力评分。",
            "suffix": "%",
        },
        "ocf_to_profit": {
            "summary": formula_summary("ocf_to_profit"),
            "components": ["op_cf", "net_profit"],
            "impact_summary": "利润兑现为经营现金流的能力影响现金流质量评分。",
            "suffix": "",
        },
        "ocf_to_rev": {
            "summary": formula_summary("ocf_to_rev"),
            "components": ["op_cf", "revenue"],
            "impact_summary": "营收对应的现金回笼效率影响现金流质量评分。",
            "suffix": "",
        },
        "free_cf": {
            "summary": formula_summary("free_cf"),
            "components": ["op_cf", "capex"],
            "impact_summary": "资本开支后的现金沉淀影响现金流质量评分。",
            "suffix": "",
            "change_summary": "自由现金流较上年同期变动由经营现金流与资本开支共同驱动",
        },
        "ar_to_asset": {
            "summary": formula_summary("ar_to_asset"),
            "components": ["ar", "total_assets"],
            "impact_summary": "应收款占用资产越多，通常越压制资产质量评分。",
            "suffix": "%",
            "lower_is_better": True,
        },
        "inv_to_asset": {
            "summary": formula_summary("inv_to_asset"),
            "components": ["inventory", "total_assets"],
            "impact_summary": "存货占用资产越多，通常越压制资产质量评分。",
            "suffix": "%",
            "lower_is_better": True,
        },
        "goodwill_ratio": {
            "summary": formula_summary("goodwill_ratio"),
            "components": ["goodwill", "total_assets"],
            "impact_summary": "商誉占比抬升通常会增加后续减值压力。",
            "suffix": "%",
            "lower_is_better": True,
        },
        "impair_to_rev": {
            "summary": formula_summary("impair_to_rev"),
            "components": ["impair_loss", "revenue"],
            "impact_summary": "减值损失占收入越高，通常越压制资产质量评分。",
            "suffix": "%",
            "lower_is_better": True,
        },
    }
    period_specs = {
        "revenue_growth": {
            "summary": period_summary("revenue_growth"),
            "impact_summary": "营收增速走弱会直接拖累成长维度评分。",
        },
        "profit_growth": {
            "summary": period_summary("profit_growth"),
            "impact_summary": "净利润增速变化会直接影响成长维度评分。",
        },
        "ex_profit_growth": {
            "summary": period_summary("ex_profit_growth"),
            "impact_summary": "扣非利润增速反映核心经营增长质量。",
        },
    }
    efficiency_specs = {
        "ar_days": {
            "summary": efficiency_summary("ar_days"),
            "components": ["ar", "revenue"],
            "impact_summary": "回款周期拉长通常会压制运营效率评分。",
            "suffix": "",
            "lower_is_better": True,
        },
        "inv_days": {
            "summary": efficiency_summary("inv_days"),
            "components": ["inventory", "operating_cost"],
            "impact_summary": "库存周转放慢通常会压制运营效率评分。",
            "suffix": "",
            "lower_is_better": True,
        },
        "asset_turn": {
            "summary": efficiency_summary("asset_turn"),
            "components": ["revenue", "total_assets"],
            "impact_summary": "资产使用效率变化会直接影响运营效率评分。",
            "suffix": "",
        },
        "debt_ratio": {
            "summary": efficiency_summary("debt_ratio"),
            "components": ["total_debt", "total_assets"],
            "impact_summary": "杠杆水平抬升通常压制偿债能力评分。",
            "suffix": "%",
            "lower_is_better": True,
        },
        "current_ratio": {
            "summary": efficiency_summary("current_ratio"),
            "components": ["current_assets", "current_liabilities"],
            "impact_summary": "短期偿债缓冲变化会直接影响偿债能力评分。",
            "suffix": "",
        },
        "quick_ratio": {
            "summary": efficiency_summary("quick_ratio"),
            "components": ["current_assets", "inventory", "current_liabilities"],
            "impact_summary": "更快可变现资产的覆盖能力影响偿债能力评分。",
            "suffix": "",
        },
    }
    direct_specs = {
        "roe_pct": {
            "summary": direct_summary("roe_pct"),
            "impact_summary": "净资产收益率变化会直接影响盈利能力评分。",
            "suffix": "%",
        }
    }

    diagnostics: dict[str, dict[str, object]] = {}
    for sub_key in _SUB_KEYS:
        current_value = _safe_float(raw_sub_indicators.get(sub_key))
        previous_value = _safe_float(prev_raw_sub_indicators.get(sub_key))

        if sub_key in formula_specs:
            spec = formula_specs[sub_key]
            change = _metric_change_summary(current_value, previous_value, suffix=spec["suffix"])
            if spec.get("change_summary"):
                change["summary"] = spec["change_summary"]
            diagnostics[sub_key] = {
                "indicator_name": _SUB_INDICATOR_LABELS.get(sub_key, sub_key),
                "change": change,
                "attribution": {
                    "template_type": "formula_decomposition",
                    "summary": spec["summary"],
                    "components": component_values(spec["components"]),
                    **attribution_metadata("formula_decomposition", sub_key),
                },
                "impact": {
                    "market_score": pct_score(score_data, sub_key),
                    "industry_score": pct_score(ind_sub_indicators, sub_key),
                    "impact_summary": spec["impact_summary"],
                    "impact_risks": formula_impact_triplet_lines(sub_key, current_value, previous_value) or risk_from_trend(
                        current_value,
                        previous_value,
                        lower_is_better=bool(spec.get("lower_is_better")),
                    ),
                },
                "explanation": {"status": "idle", "content": ""},
            }
            continue

        if sub_key in period_specs:
            spec = period_specs[sub_key]
            diagnostics[sub_key] = {
                "indicator_name": _SUB_INDICATOR_LABELS.get(sub_key, sub_key),
                "change": _metric_change_summary(current_value, previous_value, suffix="%"),
                "attribution": {
                    "template_type": "period_compare",
                    "summary": spec["summary"],
                    "periods": {
                        "current": current_value,
                        "previous": previous_value,
                    },
                    **attribution_metadata("period_compare", sub_key),
                },
                "impact": {
                    "market_score": pct_score(score_data, sub_key),
                    "industry_score": pct_score(ind_sub_indicators, sub_key),
                    "impact_summary": spec["impact_summary"],
                    "impact_risks": risk_from_trend(current_value, previous_value),
                },
                "explanation": {"status": "idle", "content": ""},
            }
            continue

        if sub_key in efficiency_specs:
            spec = efficiency_specs[sub_key]
            diagnostics[sub_key] = {
                "indicator_name": _SUB_INDICATOR_LABELS.get(sub_key, sub_key),
                "change": _metric_change_summary(current_value, previous_value, suffix=spec["suffix"]),
                "attribution": {
                    "template_type": "efficiency_misalignment",
                    "summary": spec["summary"],
                    "components": component_values(spec["components"]),
                    **attribution_metadata("efficiency_misalignment", sub_key),
                },
                "impact": {
                    "market_score": pct_score(score_data, sub_key),
                    "industry_score": pct_score(ind_sub_indicators, sub_key),
                    "impact_summary": spec["impact_summary"],
                    "impact_risks": efficiency_impact_triplet_lines(sub_key, current_value, previous_value) or risk_from_trend(
                        current_value,
                        previous_value,
                        lower_is_better=bool(spec.get("lower_is_better")),
                    ),
                },
                "explanation": {"status": "idle", "content": ""},
            }
            continue

        spec = direct_specs.get(sub_key)
        diagnostics[sub_key] = {
            "indicator_name": _SUB_INDICATOR_LABELS.get(sub_key, sub_key),
            "change": _metric_change_summary(current_value, previous_value, suffix=spec["suffix"]),
            "attribution": {
                "template_type": "direct_field_signal",
                "summary": spec["summary"],
                "signal": {
                    "current": current_value,
                    "previous": previous_value,
                },
                **attribution_metadata("direct_field_signal", sub_key),
            },
            "impact": {
                "market_score": pct_score(score_data, sub_key),
                "industry_score": pct_score(ind_sub_indicators, sub_key),
                "impact_summary": spec["impact_summary"],
                "impact_risks": risk_from_trend(current_value, previous_value),
            },
            "explanation": {"status": "idle", "content": ""},
        }

    return diagnostics


def _load_snapshot_score_rankings():
    snap = _load_financial_snapshot()
    if snap is None:
        return {
            "market_total_rank": {},
            "market_total_universe_size": 0,
            "industry_total_rank": {},
            "industry_total_universe_size": {},
        }

    industry_map = _load_industry_map()
    market_rows: list[tuple[float, str, str]] = []
    industry_rows: dict[str, list[tuple[float, str, str]]] = {}

    for key_str, entry in snap.get("scores", {}).items():
        if not isinstance(entry, dict) or ":" not in key_str:
            continue
        market, symbol = key_str.split(":", 1)
        adjusted_sub = blend_market_scores_with_industry(
            entry.get("sub_indicators", {}),
            entry.get("ind_sub_indicators", {}),
        )
        dim_scores_raw: dict[str, list[float]] = {}
        for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
            dim_scores_raw.setdefault(dim, []).append(float(adjusted_sub.get(sub_key, 0.0) or 0.0))
        weighted = {}
        for dim, vals in dim_scores_raw.items():
            avg = sum(vals) / len(vals) if vals else 0.0
            weighted[dim] = avg * _DIM_WEIGHTS.get(dim, 0.0)
        total = round(sum(weighted.values()), 4)
        market_rows.append((total, market, symbol))

        ind_total_score = entry.get("ind_total_score")
        ind2, _ind1 = industry_map.get((market, symbol), ("", ""))
        try:
            ind_total_value = float(ind_total_score)
        except (TypeError, ValueError):
            ind_total_value = None
        if ind2 and ind_total_value is not None:
            industry_rows.setdefault(ind2, []).append((ind_total_value, market, symbol))

    market_rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    market_ranks = {(market, symbol): idx for idx, (_score, market, symbol) in enumerate(market_rows, start=1)}

    industry_ranks: dict[tuple[str, str], int] = {}
    industry_sizes: dict[tuple[str, str], int] = {}
    for ind2, rows in industry_rows.items():
        rows.sort(key=lambda item: (-item[0], item[1], item[2]))
        size = len(rows)
        for idx, (_score, market, symbol) in enumerate(rows, start=1):
            key = (market, symbol)
            industry_ranks[key] = idx
            industry_sizes[key] = size

    return {
        "market_total_rank": market_ranks,
        "market_total_universe_size": len(market_rows),
        "industry_total_rank": industry_ranks,
        "industry_total_universe_size": industry_sizes,
    }


def _compute_level2_industry_raw_sub_indicator_avgs(
    market: str,
    symbol: str,
    *,
    industry_map: dict[tuple[str, str], tuple[str | None, str | None]] | None = None,
) -> dict[str, float]:
    snap = _load_financial_snapshot()
    if snap is None:
        return {}

    resolved_industry_map = industry_map or _load_industry_map()
    target_ind2, _target_ind1 = resolved_industry_map.get((market, symbol), (None, None))
    if not target_ind2:
        return {}

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for key_str, entry in snap.get("scores", {}).items():
        if not isinstance(entry, dict) or ":" not in key_str:
            continue
        peer_market, peer_symbol = key_str.split(":", 1)
        peer_ind2, _peer_ind1 = resolved_industry_map.get((peer_market, peer_symbol), (None, None))
        if peer_ind2 != target_ind2:
            continue
        raw_sub_indicators = entry.get("raw_sub_indicators", {})
        if not isinstance(raw_sub_indicators, dict):
            continue
        for sub_key, value in raw_sub_indicators.items():
            numeric_value = _safe_float(value)
            if numeric_value is None:
                continue
            totals[sub_key] = totals.get(sub_key, 0.0) + numeric_value
            counts[sub_key] = counts.get(sub_key, 0) + 1

    averages: dict[str, float] = {}
    for sub_key, total in totals.items():
        count = counts.get(sub_key, 0)
        if count > 0:
            averages[sub_key] = total / count
    return averages


def build_stock_score_industry_peer_benchmark(market, symbol, sub_key):
    if sub_key not in _SUB_KEYS:
        raise ValueError(f"invalid sub_key: {sub_key}")

    snap = _load_financial_snapshot()
    if snap is None:
        return {
            "ok": False,
            "market": market,
            "symbol": symbol,
            "stock_name": _stock_name_lookup().get((market, symbol), ""),
            "ind1": None,
            "ind2": None,
            "sub_key": sub_key,
            "indicator_name": _SUB_INDICATOR_LABELS.get(sub_key, sub_key),
            "report_date": "",
            "rows": [],
        }

    industry_map = _load_industry_map()
    ind2, ind1 = industry_map.get((market, symbol), (None, None))
    stock_name = _stock_name_lookup().get((market, symbol), "")
    target_entry = snap.get("scores", {}).get(f"{market}:{symbol}", {})
    report_date = str(target_entry.get("report_date") or "")
    previous_report_date = _previous_same_period_report_date(report_date) if report_date else None
    higher_better = next(defn[3] for defn in _SUB_DEFS if defn[0] == sub_key)
    market_symbols: list[tuple[str, str]] = []
    peer_entries: list[tuple[str, str, dict[str, object]]] = []

    for key_str, entry in snap.get("scores", {}).items():
        if not isinstance(entry, dict) or ":" not in key_str:
            continue
        peer_market, peer_symbol = key_str.split(":", 1)
        peer_ind2, _peer_ind1 = industry_map.get((peer_market, peer_symbol), (None, None))
        if not ind2 or peer_ind2 != ind2:
            continue
        market_symbols.append((peer_market, peer_symbol))
        peer_entries.append((peer_market, peer_symbol, entry))

    latest_close_prices = _load_latest_close_prices(market_symbols)
    name_lookup = _stock_name_lookup()
    component_keys = _SUB_INDICATOR_COMPONENT_KEYS.get(sub_key, [])
    rows: list[dict[str, object]] = []

    for peer_market, peer_symbol, entry in peer_entries:
        raw_sub_indicators = entry.get("raw_sub_indicators", {})
        prev_raw_sub_indicators = entry.get("prev_raw_sub_indicators", {})
        metric_value = _safe_float(raw_sub_indicators.get(sub_key)) if isinstance(raw_sub_indicators, dict) else None
        peer_report_date = str(entry.get("report_date") or "")
        peer_previous_report_date = _previous_same_period_report_date(peer_report_date) if peer_report_date else None
        component_context = _load_sub_indicator_component_context(
            peer_market,
            peer_symbol,
            current_report_date=peer_report_date or None,
            previous_report_date=peer_previous_report_date,
        )
        current_components = (component_context or {}).get("current") or {}
        previous_components = (component_context or {}).get("previous") or {}
        financial_inputs = []
        for component_key in component_keys:
            item = {
                "key": component_key,
                "label": _COMPONENT_LABELS.get(component_key, component_key),
                "current_value": _safe_float(current_components.get(component_key)),
            }
            previous_value = _safe_float(previous_components.get(component_key))
            if previous_value is not None:
                item["previous_value"] = previous_value
            financial_inputs.append(item)

        row = {
            "stock_name": name_lookup.get((peer_market, peer_symbol), peer_symbol),
            "market": peer_market,
            "symbol": peer_symbol,
            "current_price": latest_close_prices.get((peer_market, peer_symbol)),
            "metric_value": metric_value,
            "report_date": peer_report_date,
            "is_current_stock": peer_market == market and peer_symbol == symbol,
            "financial_inputs": financial_inputs,
        }
        if peer_previous_report_date:
            row["previous_report_date"] = peer_previous_report_date
        elif isinstance(prev_raw_sub_indicators, dict) and prev_raw_sub_indicators.get(sub_key) is not None:
            row["previous_report_date"] = previous_report_date
        rows.append(row)

    def sort_key(item: dict[str, object]) -> tuple[bool, float, str, str]:
        metric_value = _safe_float(item.get("metric_value"))
        if metric_value is None:
            sort_value = 0.0
        else:
            sort_value = -metric_value if higher_better else metric_value
        return (
            metric_value is None,
            sort_value,
            str(item.get("market") or ""),
            str(item.get("symbol") or ""),
        )

    rows.sort(key=sort_key)
    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name,
        "ind1": ind1,
        "ind2": ind2,
        "sub_key": sub_key,
        "indicator_name": _SUB_INDICATOR_LABELS.get(sub_key, sub_key),
        "report_date": report_date,
        "rows": rows,
    }


def build_stock_score_industry_total_peer_benchmark(market, symbol):
    snap = _load_financial_snapshot()
    if snap is None:
        return {
            "ok": False,
            "market": market,
            "symbol": symbol,
            "stock_name": _stock_name_lookup().get((market, symbol), ""),
            "ind1": None,
            "ind2": None,
            "report_date": "",
            "rows": [],
        }

    industry_map = _load_industry_map()
    ind2, ind1 = industry_map.get((market, symbol), (None, None))
    stock_name = _stock_name_lookup().get((market, symbol), "")
    target_entry = snap.get("scores", {}).get(f"{market}:{symbol}", {})
    report_date = str(target_entry.get("report_date") or "")
    market_symbols: list[tuple[str, str]] = []
    peer_entries: list[tuple[str, str, dict[str, object]]] = []

    for key_str, entry in snap.get("scores", {}).items():
        if not isinstance(entry, dict) or ":" not in key_str:
            continue
        peer_market, peer_symbol = key_str.split(":", 1)
        peer_ind2, _peer_ind1 = industry_map.get((peer_market, peer_symbol), (None, None))
        if not ind2 or peer_ind2 != ind2:
            continue
        market_symbols.append((peer_market, peer_symbol))
        peer_entries.append((peer_market, peer_symbol, entry))

    latest_close_prices = _load_latest_close_prices(market_symbols)
    name_lookup = _stock_name_lookup()
    rows: list[dict[str, object]] = []

    for peer_market, peer_symbol, entry in peer_entries:
        ind_dim_scores = entry.get("ind_dim_scores", {})
        dimension_scores: dict[str, float | None] = {}
        for dim, weight in _DIM_WEIGHTS.items():
            raw_score = _safe_float(ind_dim_scores.get(dim)) if isinstance(ind_dim_scores, dict) else None
            if raw_score is None or not weight:
                dimension_scores[dim] = None
                continue
            dimension_scores[dim] = round(raw_score / weight, 4)

        rows.append(
            {
                "stock_name": name_lookup.get((peer_market, peer_symbol), peer_symbol),
                "market": peer_market,
                "symbol": peer_symbol,
                "current_price": latest_close_prices.get((peer_market, peer_symbol)),
                "total_score": _safe_float(entry.get("ind_total_score")),
                "report_date": str(entry.get("report_date") or ""),
                "is_current_stock": peer_market == market and peer_symbol == symbol,
                "dimension_scores": dimension_scores,
            }
        )

    def sort_key(item: dict[str, object]) -> tuple[bool, float, str, str]:
        total_score = _safe_float(item.get("total_score"))
        return (
            total_score is None,
            -(total_score or 0.0),
            str(item.get("market") or ""),
            str(item.get("symbol") or ""),
        )

    rows.sort(key=sort_key)
    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name,
        "ind1": ind1,
        "ind2": ind2,
        "report_date": report_date,
        "rows": rows,
    }

# -----------------------------------------------------------------------
# Public API: single stock
# -----------------------------------------------------------------------
def compute_stock_score(market, symbol):
    res = compute_financial_scores([(market, symbol)])
    score_data = res["scores"].get((market, symbol), {})
    stock_name = _stock_name_lookup().get((market, symbol), "")
    industry_map = _load_industry_map()
    ind2, ind1 = industry_map.get((market, symbol), (None, None))
    industry_raw_sub_indicator_avgs = _compute_level2_industry_raw_sub_indicator_avgs(
        market,
        symbol,
        industry_map=industry_map,
    )
    ranking_meta = _load_snapshot_score_rankings()
    market_total_rank = ranking_meta.get("market_total_rank", {}).get((market, symbol))
    market_total_universe_size = ranking_meta.get("market_total_universe_size") or None
    industry_total_rank = ranking_meta.get("industry_total_rank", {}).get((market, symbol))
    industry_total_universe_size = ranking_meta.get("industry_total_universe_size", {}).get((market, symbol))
    # Pull report_date from score_data if present
    report_date = score_data.pop("report_date", "") if score_data else ""
    announce_date = score_data.pop("announce_date", "") if score_data else ""
    # Keep industry-rank fields before popping
    ind_total_score = score_data.pop("ind_total_score", 0.0) if score_data else 0.0
    ind_dim_scores = score_data.pop("ind_dim_scores", {}) if score_data else {}
    ind_sub_indicators = score_data.pop("ind_sub_indicators", {}) if score_data else {}
    # Promoted market-rank fields to top level for the "全市场" radar
    total_score = score_data.pop("total_score", 0.0) if score_data else 0.0
    dim_scores = score_data.pop("dim_scores", {}) if score_data else {}
    sub_indicators = score_data.pop("sub_indicators", {}) if score_data else {}
    # Raw (non-percentile) sub-indicator values and report period
    raw_sub_indicators = score_data.pop("raw_sub_indicators", {}) if score_data else {}
    prev_raw_sub_indicators = score_data.pop("prev_raw_sub_indicators", {}) if score_data else {}
    latest_period = score_data.pop("latest_period", "") if score_data else ""
    score_methodology = score_data.pop("score_methodology", None) if score_data else None
    previous_same_period_report_date = _previous_same_period_report_date(report_date) if report_date else None
    if score_data and previous_same_period_report_date:
        previous_same_period_match = _lookup_financial_row(market, symbol, previous_same_period_report_date)
        if previous_same_period_match is not None:
            prev_raw_sub_indicators = _derive_sub_fields(previous_same_period_match[1], None)
    latest_report_analysis = _build_latest_report_analysis(score_data, raw_sub_indicators, prev_raw_sub_indicators) if score_data else {"strengths": [], "risks": []}
    component_context = _load_sub_indicator_component_context(
        market,
        symbol,
        current_report_date=report_date or None,
        previous_report_date=previous_same_period_report_date,
    ) if score_data else {"current": {}, "previous": {}}
    sub_indicator_diagnostics = _build_sub_indicator_diagnostics(
        score_data,
        ind_sub_indicators,
        raw_sub_indicators,
        prev_raw_sub_indicators,
        component_context,
        ind1,
        ind2,
    ) if score_data else {}
    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "stock_name": stock_name,
        "ind1": ind1,
        "ind2": ind2,
        "report_date": report_date,
        "announce_date": announce_date,
        "latest_period": latest_period,
        "score_data": score_data,
        "total_score": total_score,
        "dim_scores": dim_scores,
        "score_methodology": score_methodology,
        "latest_report_analysis": latest_report_analysis,
        "market_total_rank": market_total_rank,
        "market_total_universe_size": market_total_universe_size,
        "industry_total_rank": industry_total_rank,
        "industry_total_universe_size": industry_total_universe_size,
        "sub_indicator_diagnostics": sub_indicator_diagnostics,
        "sub_indicators": sub_indicators,
        "raw_sub_indicators": raw_sub_indicators,
        "prev_raw_sub_indicators": prev_raw_sub_indicators,
        "industry_raw_sub_indicator_avgs": industry_raw_sub_indicator_avgs,
        "ind_total_score": ind_total_score,
        "ind_dim_scores": ind_dim_scores,
        "ind_sub_indicators": ind_sub_indicators,
    }
