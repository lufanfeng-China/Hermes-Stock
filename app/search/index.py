"""Local stock and concept search indexes backed by Tongdaxin and derived JSON datasets."""

from __future__ import annotations

import json
import sys
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


# ═══════════════════════════════════════════════════════════════════════════
#  CONCEPT DOMAIN — concept index, search, list
#  (Future: migrate to app/search/concept.py once shared utils extracted)
# ═══════════════════════════════════════════════════════════════════════════

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
        concept_rank = _coerce_int(row.get("concept_rank_in_stock"))
        # Count total concepts and keep the raw concept list for narrative generation
        concept_list_raw = str(row.get("concept_list_raw", ""))
        concept_total = len([c.strip() for c in concept_list_raw.split(",") if c.strip()]) if concept_list_raw else 0
        concept_list = [c.strip() for c in concept_list_raw.split(",") if c.strip()] if concept_list_raw else []
        member = {
            "market": market,
            "symbol": symbol,
            "stock_name": str(row.get("stock_name") or industry.get("stock_name") or security.get("stock_name") or "").strip(),
            "industry_display": str(industry.get("industry_display", "")).strip(),
            "name_initials": str(security.get("name_initials", "")).strip(),
            "concept_rank_in_stock": concept_rank if concept_rank else None,
            "concept_total_count": concept_total,
            "concept_list": concept_list,
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


def search_concept_stocks(query: str) -> dict[str, object]:
    """Search concept by name (exact → partial → text). Returns matched stocks."""
    from app.tdx.parsers import normalize_concept_name

    concept_rows = load_concept_rows()
    securities = load_security_rows()
    industry_rows = load_industry_rows()
    concept_index = build_concept_index(concept_rows, securities, industry_rows)

    q = query.strip()
    qn = normalize_concept_name(q)

    # L1: exact match
    for c in concept_index:
        if normalize_concept_name(str(c.get("concept_name", ""))) == qn:
            return {"matched": True, "concept": c, "method": "exact"}

    # L1: partial match
    partials = [c for c in concept_index if q in str(c.get("concept_name", "")) or qn in normalize_concept_name(str(c.get("concept_name", "")))]
    if partials:
        # Return largest concept
        partials.sort(key=lambda c: -int(c.get("member_count", 0)))
        return {"matched": True, "concept": partials[0], "method": "partial"}

    # L2: text search in concept labels of each stock
    q_lower = q.lower()
    text_matches: dict[str, list[dict]] = {}
    for row in concept_rows:
        concept_list = str(row.get("concept_list_raw", "")).lower()
        if q_lower in concept_list or any(q_lower in str(row.get(f, "")).lower() for f in ["concept_name", "stock_name"]):
            key = f"{row.get('market', '')}:{row.get('symbol', '')}"
            if key not in text_matches:
                text_matches[key] = []
            text_matches[key].append({
                "market": str(row.get("market", "")).strip(),
                "symbol": str(row.get("symbol", "")).strip(),
                "stock_name": str(row.get("stock_name", "")).strip(),
            })

    # Build synthetic concept from text matches
    if text_matches:
        members = []
        seen = set()
        for key, entries in text_matches.items():
            e = entries[0]
            mk = (e["market"], e["symbol"])
            if mk not in seen:
                seen.add(mk)
                members.append(e)
        concepts_list = {"concept_id": f"search:{qn}", "concept_name": q, "member_count": len(members), "members": members}
        return {"matched": False, "concept": concepts_list, "method": "text_search"}

    return {"matched": False, "concept": None, "method": "not_found"}


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
        "industry_rps_20": None,
        "industry_rps_50": None,
        "industry_rps_120": None,
        "industry_rps_250": None,
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
                "industry_rps_20": None,
                "industry_rps_50": None,
                "industry_rps_120": None,
                "industry_rps_250": None,
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
            ranked_rows_120: list[tuple[float, str, str]] = []
            ranked_rows_250: list[tuple[float, str, str]] = []
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
                rps_120 = _coerce_float(rps_row.get("rps_120"))
                rps_250 = _coerce_float(rps_row.get("rps_250"))
                if rps_20 is not None:
                    ranked_rows_20.append((rps_20, row_key[0], row_key[1]))
                if rps_50 is not None:
                    ranked_rows_50.append((rps_50, row_key[0], row_key[1]))
                if rps_120 is not None:
                    ranked_rows_120.append((rps_120, row_key[0], row_key[1]))
                if rps_250 is not None:
                    ranked_rows_250.append((rps_250, row_key[0], row_key[1]))

            def _industry_rank(rows: list[tuple[float, str, str]], target_key: tuple[str, str]) -> int | None:
                ordered = sorted(rows, key=lambda item: (-item[0], item[1], item[2]))
                for index, (_, market, stock_symbol) in enumerate(ordered, start=1):
                    if (market, stock_symbol) == target_key:
                        return index
                return None

            if members_in_industry:
                rps_metrics["industry_universe_size"] = len(members_in_industry)
                if ranked_rows_20:
                    rps_metrics["industry_rps_20"] = sum(item[0] for item in ranked_rows_20) / len(ranked_rows_20)
                if ranked_rows_50:
                    rps_metrics["industry_rps_50"] = sum(item[0] for item in ranked_rows_50) / len(ranked_rows_50)
                if ranked_rows_120:
                    rps_metrics["industry_rps_120"] = sum(item[0] for item in ranked_rows_120) / len(ranked_rows_120)
                if ranked_rows_250:
                    rps_metrics["industry_rps_250"] = sum(item[0] for item in ranked_rows_250) / len(ranked_rows_250)
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
def _load_latest_daily_snapshot(market: str, symbol: str) -> dict[str, object]:
    snapshot = {
        "latest_close": None,
        "previous_close": None,
        "latest_volume": None,
        "avg_volume_5": None,
        "trading_day": None,
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
        snapshot["trading_day"] = _extract_trading_day_from_daily_row(latest_row)
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


def _extract_trading_day_from_daily_row(row) -> str | None:
    candidates = []
    if hasattr(row, "name"):
        candidates.append(row.name)
    if hasattr(row, "get"):
        candidates.extend([row.get("date"), row.get("datetime"), row.get("trade_date")])
    for value in candidates:
        if value is None:
            continue
        if hasattr(value, "strftime"):
            try:
                return value.strftime("%Y-%m-%d")
            except Exception:
                pass
        text = str(value).strip()
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
    return None


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


def load_rps_rows_as_of(as_of_date: str, dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    """Load RPS data as of a historical date using the precomputed history dataset.

    For each (market, symbol), returns the latest record with trading_day <= as_of_date.
    Returns list in the same format as load_rps_rows().
    """
    history_path = Path(dataset_dir) / "dataset_stock_rps_history.json"
    if not history_path.exists():
        return load_rps_rows(dataset_dir)

    all_history = _load_json_rows(history_path)
    if not all_history:
        return load_rps_rows(dataset_dir)

    # Group by (market, symbol), keep latest record <= as_of_date
    best: dict[tuple[str, str], dict[str, object]] = {}
    for record in all_history:
        td = str(record.get("trading_day", ""))
        if td > as_of_date:
            continue
        key = (_normalize_text(record.get("market")), _normalize_text(record.get("symbol")))
        if key not in best or td > str(best[key].get("trading_day", "")):
            best[key] = record

    # Return as list with consistent keys matching load_rps_rows format
    result: list[dict[str, object]] = []
    for record in best.values():
        result.append({
            "trading_day": str(record.get("trading_day", "")),
            "market": _normalize_text(record.get("market")),
            "symbol": _normalize_text(record.get("symbol")),
            "rps_20": record.get("rps_20"),
            "rps_50": record.get("rps_50"),
            "rps_120": record.get("rps_120"),
            "rps_250": record.get("rps_250"),
        })
    return result


@lru_cache(maxsize=1)
def load_industry_valuation_rows(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return _load_json_rows(Path(dataset_dir) / "dataset_industry_valuation_current.json")


@lru_cache(maxsize=1)
def load_stock_screener_strategy_rows(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    path = Path(dataset_dir) / "dataset_stock_screener_strategies_current.json"
    if not path.exists():
        return []
    return _load_json_rows(path)


# Dict cache for date-specific strategy files
_strategy_rows_cache: dict[str, list[dict[str, object]]] = {}


def load_stock_screener_strategy_rows_as_of(
    trading_day: str,
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
) -> list[dict[str, object]]:
    """Load strategy dataset for a specific trading day."""
    if trading_day in _strategy_rows_cache:
        return _strategy_rows_cache[trading_day]

    path = Path(dataset_dir) / f"dataset_stock_screener_strategies_{trading_day}.json"
    if not path.exists():
        return []

    rows = _load_json_rows(path)
    _strategy_rows_cache[trading_day] = rows
    return rows


@lru_cache(maxsize=1)
def load_concept_index(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[dict[str, object]]:
    return build_concept_index(
        load_concept_rows(dataset_dir),
        load_security_rows(),
        load_industry_rows(dataset_dir),
    )


@lru_cache(maxsize=1)
def _load_price_percentile_5y(
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
) -> dict[str, dict[str, object]]:
    """Load pre-computed 5-year price percentile data.
    Returns dict keyed by 6-digit symbol → {price_percentile_5y, price_band_5y, ...}
    """
    path = Path(dataset_dir) / "dataset_price_percentile_5y.json"
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Manual cache keyed by (dataset_dir, as_of_date)
_tech_eval_cache: dict[tuple[str, str], dict[str, dict[str, object]]] = {}


def _load_technical_eval(
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
    as_of_date: str = "",
) -> dict[str, dict[str, object]]:
    """Load pre-computed 6-dimension technical evaluation.
    When as_of_date is provided, loads date-specific cached file.
    Returns dict keyed by 6-digit symbol.
    """
    cache_key = (str(dataset_dir), as_of_date)
    if cache_key in _tech_eval_cache:
        return _tech_eval_cache[cache_key]

    if as_of_date:
        path = Path(dataset_dir) / f"dataset_technical_eval_{as_of_date}.json"
    else:
        path = Path(dataset_dir) / "dataset_technical_eval.json"
    if not path.is_file():
        if as_of_date:
            _build_tech_eval_async(as_of_date)
        # Don't cache empty results — file may be created by background build
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    result = raw.get("stocks", raw)
    _tech_eval_cache[cache_key] = result
    return result


_macd_signals_cache: dict[tuple[str, str], dict[str, str]] = {}

def _load_macd_signals(
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
    as_of_date: str = "",
) -> dict[str, str]:
    """Load MACD signal dataset. When as_of_date is provided, loads date-specific file.
    Returns dict keyed by 'market:symbol' -> signal label."""
    cache_key = (str(dataset_dir), as_of_date)
    if cache_key in _macd_signals_cache:
        return _macd_signals_cache[cache_key]

    if as_of_date:
        path = Path(dataset_dir) / f"dataset_macd_signals_{as_of_date}.json"
    else:
        path = Path(dataset_dir) / "dataset_macd_signals_current.json"
    if not path.is_file():
        if as_of_date:
            _build_macd_async(as_of_date)
        return {}
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    result = {}
    for row in rows:
        key = f"{row.get('market','')}:{row.get('symbol','')}"
        result[key] = row.get("macd_signal", "")
    _macd_signals_cache[cache_key] = result
    return result


def _build_macd_async(trading_day: str) -> None:
    """Spawn background process to build MACD signals for a given date."""
    import subprocess
    try:
        subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "build_macd_signals.py"),
                "--trading-day", trading_day,
                "--tdxdir", "/mnt/c/new_tdx64",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _build_tech_eval_async(trading_day: str) -> None:
    """Spawn background process to build tech eval for a given date."""
    import subprocess
    try:
        subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "build_technical_eval.py"),
                "--trading-day", trading_day,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass  # silently fail — background build is best-effort


def _build_strategy_async(trading_day: str, strategy: str) -> None:
    """Spawn background process to build ALL strategy datasets for a given date.
    Builds all strategies so the date file is complete after first visit."""
    import subprocess
    all_strategies = ["rps_first", "ma_cross", "blowup_stall", "blowup_break", "ma_pullback"]
    # Build the requested strategy first (fastest path), then the rest
    ordered = [strategy] + [s for s in all_strategies if s != strategy]
    try:
        subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "build_stock_screener_strategies.py"),
                "--strategy", ordered[0],
                "--trading-day", trading_day,
                "--tdxdir", "/mnt/c/new_tdx64",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Start remaining strategies after a short delay (let first one finish)
        for s in ordered[1:]:
            subprocess.Popen(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "build_stock_screener_strategies.py"),
                    "--strategy", s,
                    "--trading-day", trading_day,
                    "--tdxdir", "/mnt/c/new_tdx64",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


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


def _is_word_boundary(s: str, pos: int) -> bool:
    """Check if position *pos* in *s* is at a word boundary (start of string or preceded by non-alphanumeric)."""
    if pos == 0:
        return True
    return not s[pos - 1].isalnum()


def concept_list_response(query: str = "", limit: int = 100) -> dict[str, object]:
    """Return active concept names, fuzzy-matched with scoring, sorted by stock_count desc.
    
    Single-stock concepts (stock_count <= 1) are filtered out entirely.
    """
    concept_dict_path = Path(DEFAULT_DATASET_DIR) / "dataset_concept_dictionary.json"
    all_concepts = _load_json_rows(concept_dict_path)

    # Only active concepts
    active = [c for c in all_concepts if c.get("is_active", False)]

    # Build stock count lookup from concept → stock mapping (do this FIRST)
    stock_count_by_concept: dict[str, int] = {}
    try:
        concept_rows = load_concept_rows()
        for row in concept_rows:
            cn = (row.get("concept_name") or "").strip()
            if cn:
                stock_count_by_concept[cn] = stock_count_by_concept.get(cn, 0) + 1
    except Exception:
        pass  # non-critical, proceed without counts

    # Build results with stock counts, filtering out single-stock concepts
    results: list[dict[str, object]] = []
    for c in active:
        name = c.get("concept_name") or ""
        cnt = stock_count_by_concept.get(name, 0)
        if cnt <= 1:
            continue  # skip single-stock concepts
        results.append({
            "concept_id": c.get("concept_id", ""),
            "concept_name": name,
            "stock_count": cnt,
        })

    if query:
        q = query.strip().lower()
        # Score each result by match position (earlier = better) and word-boundary boost
        scored: list[tuple[int, int, dict[str, object]]] = []
        for r in results:
            name_lower = r["concept_name"].lower()
            pos = name_lower.find(q)
            if pos == -1:
                continue  # no match, exclude
            boundary_bonus = 1000 if _is_word_boundary(name_lower, pos) else 0
            score = boundary_bonus - pos  # higher = better
            scored.append((score, r["stock_count"], r))

        # Sort by score DESC then stock_count DESC
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        results = [item[2] for item in scored]
    else:
        # No query: sort by stock_count descending only
        results.sort(key=lambda r: r["stock_count"], reverse=True)

    return {"ok": True, "query": query, "count": len(results[:limit]), "results": results[:limit]}


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


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _is_valid_date(date_str: str) -> bool:
    """Check if date_str is YYYY-MM-DD format."""
    if not date_str or len(date_str) != 10:
        return False
    parts = date_str.split("-")
    if len(parts) != 3:
        return False
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return 2020 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31
    except (ValueError, TypeError):
        return False


def _classification_label(classification: str, sub_classification: str = "") -> str:
    classification_text = _normalize_text(classification)
    sub_text = _normalize_text(sub_classification).upper()
    if classification_text == "A_NORMAL_EARNING":
        return "正常盈利"
    if classification_text == "B_THIN_PROFIT_DISTORTED":
        return "微盈利畸高"
    if classification_text == "C_LOSS":
        if sub_text in {"C3", "C4", "C3_NO_REVENUE_CONCEPT", "C4_LIQUIDATION_RISK"}:
            return "高风险例外"
        return "亏损经营"
    return classification_text


def _score_rank_lookups(
    score_rows: dict[str, object],
    industry_lookup: dict[tuple[str, str], dict[str, object]],
) -> tuple[dict[str, int], int, dict[str, int], dict[str, int], dict[str, float], dict[str, float], dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    """Compute market and Shenwan level-2 score ranks for screener rows."""

    # Pre-compute trend scores for blending
    snap = _load_financial_snapshot()
    trend_payload = _compute_trend_scores_from_snapshot(snap) if snap else None
    trend_market = (trend_payload or {}).get("sub_indicators", {})
    trend_ind = (trend_payload or {}).get("ind_sub_indicators", {})

    market_scored: list[tuple[str, float]] = []
    market_score_lookup: dict[str, float] = {}
    market_abs_lookup: dict[str, float] = {}
    market_trend_lookup: dict[str, float] = {}
    industry_score_lookup: dict[str, float] = {}
    industry_abs_lookup: dict[str, float] = {}
    industry_trend_lookup: dict[str, float] = {}
    industry_scored: dict[str, list[tuple[str, float]]] = {}
    for score_key, score_entry in score_rows.items():
        if not isinstance(score_entry, dict):
            continue
        market, _, symbol = str(score_key).partition(":")
        market = market.strip().lower()
        symbol = symbol.strip()
        if not market or not symbol:
            continue
        # ── Blended market score ──
        abs_total = _screener_market_total_score(score_entry)
        if abs_total is not None:
            market_abs_lookup[str(score_key)] = abs_total
            trend_total = _screener_trend_total_score(score_entry, str(score_key), trend_market, trend_ind)
            if trend_total is not None:
                market_trend_lookup[str(score_key)] = trend_total
                blended = round(abs_total * 0.6 + trend_total * 0.4, 4)
            else:
                blended = abs_total
            market_scored.append((str(score_key), blended))
            market_score_lookup[str(score_key)] = blended

        # ── Blended industry score ──
        ind_abs = _coerce_float(score_entry.get("ind_total_score"))
        if ind_abs is None:
            continue
        industry_abs_lookup[str(score_key)] = ind_abs
        ind_t = _screener_ind_trend_total(score_entry, str(score_key), trend_ind)
        if ind_t is not None:
            industry_trend_lookup[str(score_key)] = ind_t
        ind_blended = round(ind_abs * 0.6 + ind_t * 0.4, 4) if ind_t is not None else ind_abs
        industry = industry_lookup.get((market, symbol)) or {}
        industry_level_2 = (
            _normalize_text(score_entry.get("industry_sw_level_2"))
            or _normalize_text(industry.get("industry_level_2_name"))
        )
        if industry_level_2:
            industry_scored.setdefault(industry_level_2, []).append((str(score_key), ind_blended))
        industry_score_lookup[str(score_key)] = ind_blended

    market_rank = _rank_descending(market_scored)
    industry_rank: dict[str, int] = {}
    industry_universe_size: dict[str, int] = {}
    for industry_level_2, items in industry_scored.items():
        industry_rank.update(_rank_descending(items))
        industry_universe_size[industry_level_2] = len(items)
    return market_rank, len(market_scored), industry_rank, industry_universe_size, market_score_lookup, industry_score_lookup, market_abs_lookup, market_trend_lookup, industry_abs_lookup, industry_trend_lookup


def _screener_trend_total_score(
    score_entry: dict[str, object],
    score_key: str,
    trend_market: dict[str, dict[str, float]],
    trend_ind: dict[str, dict[str, float]],
) -> float | None:
    """Compute blended trend total from cached trend percentiles."""
    m_trend = trend_market.get(score_key, {})
    i_trend = trend_ind.get(score_key, {})
    if not m_trend:
        return None
    blended_trend = blend_market_scores_with_industry(m_trend, i_trend)
    dim_scores_raw: dict[str, list[float]] = {}
    for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
        dim_scores_raw.setdefault(dim, []).append(float(blended_trend.get(sub_key, 0.0) or 0.0))
    total = 0.0
    has_value = False
    for dim, values in dim_scores_raw.items():
        if not values:
            continue
        total += (sum(values) / len(values)) * _DIM_WEIGHTS.get(dim, 0.0)
        has_value = True
    return round(total, 4) if has_value else None


def _screener_ind_trend_total(
    score_entry: dict[str, object],
    score_key: str,
    trend_ind: dict[str, dict[str, float]],
) -> float | None:
    """Compute industry trend total from cached trend percentiles."""
    i_trend = trend_ind.get(score_key, {})
    if not i_trend:
        return None
    dim_scores_raw: dict[str, list[float]] = {}
    for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
        dim_scores_raw.setdefault(dim, []).append(float(i_trend.get(sub_key, 0.0) or 0.0))
    total = 0.0
    has_value = False
    for dim, values in dim_scores_raw.items():
        if not values:
            continue
        total += (sum(values) / len(values)) * _DIM_WEIGHTS.get(dim, 0.0)
        has_value = True
    return round(total, 4) if has_value else None


def _score_divergence_label(abs_score: float | None, trend_score: float | None) -> str:
    """Return 'positive' (trend improving), 'negative' (trend worsening), or ''."""
    if abs_score is None or trend_score is None:
        return ""
    diff = trend_score - abs_score
    if diff >= 10:
        return "positive"
    if diff <= -10:
        return "negative"
    return ""


def _screener_market_total_score(score_entry: dict[str, object]) -> float | None:
    sub_indicators = score_entry.get("sub_indicators")
    ind_sub_indicators = score_entry.get("ind_sub_indicators")
    if isinstance(sub_indicators, dict) and len(sub_indicators) >= len(_SUB_DEFS):
        adjusted_sub = blend_market_scores_with_industry(
            sub_indicators,
            ind_sub_indicators if isinstance(ind_sub_indicators, dict) else {},
        )
        dim_scores_raw: dict[str, list[float]] = {}
        for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
            dim_scores_raw.setdefault(dim, []).append(float(adjusted_sub.get(sub_key, 0.0) or 0.0))
        total = 0.0
        has_value = False
        for dim, values in dim_scores_raw.items():
            if not values:
                continue
            total += (sum(values) / len(values)) * _DIM_WEIGHTS.get(dim, 0.0)
            has_value = True
        if has_value:
            return round(total, 4)
    return _coerce_float(score_entry.get("total_score"))


def _rank_descending(items: list[tuple[str, float]]) -> dict[str, int]:
    ranked: dict[str, int] = {}
    for index, (key, _score) in enumerate(sorted(items, key=lambda item: (-item[1], item[0])), start=1):
        ranked[key] = index
    return ranked


def _matches_keyword_filter(actual: object, expected: str) -> bool:
    expected_text = _normalize_text(expected)
    if not expected_text:
        return True
    actual_text = _normalize_text(actual)
    if not actual_text:
        return False
    return actual_text == expected_text


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _normalize_text(value).lower() in {"1", "true", "yes", "y", "passed", "命中"}


def _passes_min_max(value: object, *, min_value: float | None = None, max_value: float | None = None) -> bool:
    numeric = _coerce_float(value)
    if numeric is None:
        return False
    if min_value is not None and numeric < min_value:
        return False
    if max_value is not None and numeric > max_value:
        return False
    return True


def _extract_member_metric(member_row: dict[str, object], *keys: str) -> object:
    for key in keys:
        if key in member_row and member_row.get(key) not in (None, ""):
            return member_row.get(key)
    return None


def evaluate_rps_standard_launch_signal(
    latest_rps: dict[str, object],
    ref3_rps: dict[str, object],
    ref5_rps: dict[str, object],
    bars: list[dict[str, object]],
) -> dict[str, object]:
    def moving_average(values: list[float | None], period: int, end_index: int) -> float | None:
        start_index = end_index - period + 1
        if start_index < 0:
            return None
        window = values[start_index : end_index + 1]
        if any(value is None for value in window):
            return None
        return sum(float(value) for value in window) / period

    closes = [_coerce_float(bar.get("close")) for bar in bars]
    highs = [_coerce_float(bar.get("high")) for bar in bars]
    volumes = [_coerce_float(bar.get("volume")) for bar in bars]
    latest_index = len(bars) - 1
    latest_close = closes[latest_index] if latest_index >= 0 else None
    latest_volume = volumes[latest_index] if latest_index >= 0 else None

    ma20 = moving_average(closes, 20, latest_index) if latest_index >= 0 else None
    ma50 = moving_average(closes, 50, latest_index) if latest_index >= 0 else None
    ma120 = moving_average(closes, 120, latest_index) if latest_index >= 0 else None
    ma50_ref5 = moving_average(closes, 50, latest_index - 5) if latest_index >= 5 else None
    vol5 = moving_average(volumes, 5, latest_index) if latest_index >= 0 else None
    hhv60_window = highs[max(0, latest_index - 59) : latest_index + 1]
    hhv60 = max((float(value) for value in hhv60_window if value is not None), default=None)

    rps20 = _coerce_float(latest_rps.get("rps_20"))
    rps50 = _coerce_float(latest_rps.get("rps_50"))
    rps120 = _coerce_float(latest_rps.get("rps_120"))
    rps250 = _coerce_float(latest_rps.get("rps_250"))
    ref3_rps20 = _coerce_float(ref3_rps.get("rps_20"))
    ref5_rps50 = _coerce_float(ref5_rps.get("rps_50"))

    conditions = {
        "rps_base": all(value is not None for value in (rps20, rps50, rps120, rps250))
        and bool(rps250 >= 80 and rps120 >= 85 and rps50 >= 88 and rps20 >= 92),
        "rps_structure": all(value is not None for value in (rps20, rps50, rps120, rps250))
        and bool(rps20 > rps50 and rps50 >= rps120 - 3 and rps120 >= rps250 - 5),
        "rps_turning_point": all(value is not None for value in (rps20, rps50, ref3_rps20, ref5_rps50))
        and bool(rps20 > ref3_rps20 and rps50 > ref5_rps50),
        "trend_confirmed": all(value is not None for value in (latest_close, ma20, ma50, ma120, ma50_ref5))
        and bool(latest_close > ma20 and ma20 > ma50 and ma50 >= ma50_ref5),
        "volume_start": latest_volume is not None and vol5 is not None and bool(latest_volume > 1.3 * vol5),
    }
    return {
        "passed": all(conditions.values()),
        "conditions": conditions,
    }


def evaluate_rps_attack_signal(
    latest_rps: dict[str, object],
    ref1_rps: dict[str, object],
    ref2_rps: dict[str, object],
    ref3_rps: dict[str, object],
    bars: list[dict[str, object]],
) -> dict[str, object]:
    def moving_average(values: list[float | None], period: int, end_index: int) -> float | None:
        start_index = end_index - period + 1
        if start_index < 0:
            return None
        window = values[start_index : end_index + 1]
        if any(value is None for value in window):
            return None
        return sum(float(value) for value in window) / period

    closes = [_coerce_float(bar.get("close")) for bar in bars]
    highs = [_coerce_float(bar.get("high")) for bar in bars]
    volumes = [_coerce_float(bar.get("volume")) for bar in bars]
    latest_index = len(bars) - 1
    latest_close = closes[latest_index] if latest_index >= 0 else None
    latest_volume = volumes[latest_index] if latest_index >= 0 else None

    ma20 = moving_average(closes, 20, latest_index) if latest_index >= 0 else None
    ma50 = moving_average(closes, 50, latest_index) if latest_index >= 0 else None
    ma50_ref3 = moving_average(closes, 50, latest_index - 3) if latest_index >= 3 else None
    vol5 = moving_average(volumes, 5, latest_index) if latest_index >= 0 else None
    hhv40_window = highs[max(0, latest_index - 39) : latest_index + 1]
    hhv40 = max((float(value) for value in hhv40_window if value is not None), default=None)

    rps20 = _coerce_float(latest_rps.get("rps_20"))
    rps50 = _coerce_float(latest_rps.get("rps_50"))
    rps120 = _coerce_float(latest_rps.get("rps_120"))
    rps250 = _coerce_float(latest_rps.get("rps_250"))
    ref1_rps20 = _coerce_float(ref1_rps.get("rps_20"))
    ref2_rps20 = _coerce_float(ref2_rps.get("rps_20"))
    ref3_rps50 = _coerce_float(ref3_rps.get("rps_50"))

    conditions = {
        "rps_base": all(value is not None for value in (rps20, rps50, rps120, rps250))
        and bool(rps250 >= 75 and rps120 >= 80 and rps50 >= 82 and rps20 >= 88),
        "rps_acceleration": all(value is not None for value in (rps20, rps50, ref1_rps20, ref2_rps20, ref3_rps50))
        and bool(rps20 > ref1_rps20 and ref1_rps20 > ref2_rps20 and rps50 > ref3_rps50),
        "rps_structure": all(value is not None for value in (rps20, rps50, rps120, rps250))
        and bool(rps20 > rps50 and rps120 >= rps250 - 8),
        "trend_confirmed": all(value is not None for value in (latest_close, ma20, ma50, ma50_ref3))
        and bool(latest_close > ma20 and latest_close > ma50 and ma50 > ma50_ref3),
        "volume_mild_expand": latest_volume is not None and vol5 is not None and bool(latest_volume > 1.2 * vol5),
    }
    return {
        "passed": all(conditions.values()),
        "conditions": conditions,
    }


def evaluate_rps_pullback_signal(
    latest_rps: dict[str, object],
    ref3_rps: dict[str, object],
    ref5_rps: dict[str, object],
    bars: list[dict[str, object]],
    thresholds: dict[str, object] | None = None,
) -> dict[str, object]:
    if thresholds is None:
        thresholds = {}

    def moving_average(values: list[float | None], period: int, end_index: int) -> float | None:
        start_index = end_index - period + 1
        if start_index < 0:
            return None
        window = values[start_index : end_index + 1]
        if any(value is None for value in window):
            return None
        return sum(float(value) for value in window) / period

    opens = [_coerce_float(bar.get("open")) for bar in bars]
    highs = [_coerce_float(bar.get("high")) for bar in bars]
    lows = [_coerce_float(bar.get("low")) for bar in bars]
    closes = [_coerce_float(bar.get("close")) for bar in bars]
    volumes = [_coerce_float(bar.get("volume")) for bar in bars]
    latest_index = len(bars) - 1

    latest_open = opens[latest_index] if latest_index >= 0 else None
    latest_high_ref1 = highs[latest_index - 1] if latest_index >= 1 else None
    latest_low5_window = lows[max(0, latest_index - 4) : latest_index + 1]
    latest_close = closes[latest_index] if latest_index >= 0 else None
    latest_volume = volumes[latest_index] if latest_index >= 0 else None

    ma20 = moving_average(closes, 20, latest_index) if latest_index >= 0 else None
    ma50 = moving_average(closes, 50, latest_index) if latest_index >= 0 else None
    ma120 = moving_average(closes, 120, latest_index) if latest_index >= 0 else None
    ma250 = moving_average(closes, 250, latest_index) if latest_index >= 0 else None
    ma50_ref5 = moving_average(closes, 50, latest_index - 5) if latest_index >= 5 else None
    ma120_ref10 = moving_average(closes, 120, latest_index - 10) if latest_index >= 10 else None
    vol5 = moving_average(volumes, 5, latest_index) if latest_index >= 0 else None
    llv_low5 = min((float(value) for value in latest_low5_window if value is not None), default=None)

    rps20 = _coerce_float(latest_rps.get("rps_20"))
    rps50 = _coerce_float(latest_rps.get("rps_50"))
    rps120 = _coerce_float(latest_rps.get("rps_120"))
    rps250 = _coerce_float(latest_rps.get("rps_250"))
    ref3_rps20 = _coerce_float(ref3_rps.get("rps_20"))
    ref5_rps50 = _coerce_float(ref5_rps.get("rps_50"))

    rps250_min = _coerce_float(thresholds.get("rps250_min")) or 80.0
    rps120_min = _coerce_float(thresholds.get("rps120_min")) or 85.0
    rps50_min = _coerce_float(thresholds.get("rps50_min")) or 88.0
    rps20_min = _coerce_float(thresholds.get("rps20_min")) or 92.0
    volume_ratio_min = _coerce_float(thresholds.get("volume_ratio_min")) or 1.2
    overheat_ratio_max = _coerce_float(thresholds.get("overheat_ratio_max")) or 1.08

    conditions = {
        "rps_base": all(value is not None for value in (rps20, rps50, rps120, rps250))
        and bool(rps250 >= rps250_min and rps120 >= rps120_min and rps50 >= rps50_min and rps20 >= rps20_min),
        "rps_structure": all(value is not None for value in (rps20, rps50, rps120, rps250))
        and bool(rps20 > rps50 and rps50 >= rps120 - 3 and rps120 >= rps250 - 5),
        "rps_turning_point": all(value is not None for value in (rps20, rps50, ref3_rps20, ref5_rps50))
        and bool(rps20 > ref3_rps20 and rps50 > ref5_rps50),
        "trend_quality": all(value is not None for value in (latest_close, ma20, ma50, ma120, ma250))
        and bool(latest_close > ma20 and ma20 > ma50 and ma50 > ma120 and ma120 >= ma250 * 0.98),
        "midterm_up": all(value is not None for value in (ma50, ma50_ref5, ma120, ma120_ref10))
        and bool(ma50 > ma50_ref5 and ma120 >= ma120_ref10),
        "pullback_touched": llv_low5 is not None and ma20 is not None and bool(llv_low5 <= ma20 * 1.02),
        "trend_intact": llv_low5 is not None and ma50 is not None and bool(llv_low5 >= ma50 * 0.98),
        "renewed_strength": all(value is not None for value in (latest_close, ma20, latest_high_ref1))
        and bool(latest_close > ma20 and latest_close > latest_high_ref1),
        "volume_confirmed": latest_volume is not None and vol5 is not None and bool(latest_volume > vol5 * volume_ratio_min),
        "bullish_candle": latest_close is not None and latest_open is not None and bool(latest_close > latest_open),
        "not_overheated": latest_close is not None and ma20 not in (None, 0.0) and bool(latest_close / ma20 < overheat_ratio_max),
    }
    return {
        "passed": all(conditions.values()),
        "conditions": conditions,
    }


def build_stock_screener_response(params: dict[str, str]) -> dict[str, object]:
    snapshot = _load_financial_snapshot() or {}
    score_rows = snapshot.get("scores") or {}
    securities = load_security_rows()
    industry_rows = load_industry_rows()
    as_of_date = _normalize_text(params.get("as_of_date"))
    if as_of_date and _is_valid_date(as_of_date):
        rps_rows = load_rps_rows_as_of(as_of_date)
    else:
        rps_rows = load_rps_rows()
        as_of_date = ""  # clear invalid date
    valuation_rows = load_industry_valuation_rows()
    active_strategy = _normalize_text(params.get("strategy"))
    if active_strategy and as_of_date:
        all_strategy_rows = load_stock_screener_strategy_rows_as_of(as_of_date)
        # Filter to only the active strategy
        strategy_rows = [
            r for r in all_strategy_rows
            if _normalize_text(r.get("strategy")) == active_strategy
        ]
        if not strategy_rows and all_strategy_rows:
            # File exists but doesn't have this strategy — trigger async merge-build
            _build_strategy_async(as_of_date, active_strategy)
            _strategy_rows_cache.pop(as_of_date, None)  # invalidate cache
            strategy_rows = []
        elif not all_strategy_rows:
            # File doesn't exist at all
            _build_strategy_async(as_of_date, active_strategy)
            _strategy_rows_cache.pop(as_of_date, None)  # invalidate cache
            strategy_rows = []
    else:
        strategy_rows = load_stock_screener_strategy_rows() if active_strategy else []

    # Load 5-year price percentile data
    price_pct_rows = _load_price_percentile_5y()
    tech_eval_rows = _load_technical_eval(as_of_date=as_of_date)

    security_lookup = {_security_key(row): row for row in securities}
    industry_lookup = {_security_key(row): row for row in industry_rows}
    rps_lookup = {_security_key(row): row for row in rps_rows}
    price_pct_lookup = price_pct_rows  # keyed by symbol string
    market_rank_lookup, market_universe_size, industry_rank_lookup, industry_universe_sizes, market_score_lookup, industry_score_lookup, market_abs_lookup, market_trend_lookup, industry_abs_lookup, industry_trend_lookup = _score_rank_lookups(
        score_rows if isinstance(score_rows, dict) else {},
        industry_lookup,
    )

    industry_rps_aggregate: dict[str, dict[str, float | int | None]] = {}
    for row in rps_rows:
        key = _security_key(row)
        industry = industry_lookup.get(key) or {}
        level2 = _normalize_text(industry.get("industry_level_2_name"))
        if not level2:
            score_entry = score_rows.get(f"{key[0]}:{key[1]}") or {}
            level2 = _normalize_text(score_entry.get("industry_sw_level_2"))
        if not level2:
            continue
        bucket = industry_rps_aggregate.setdefault(
            level2,
            {
                "count": 0,
                "sum_rps_20": 0.0,
                "sum_rps_50": 0.0,
                "sum_rps_120": 0.0,
                "sum_rps_250": 0.0,
                "count_rps_20": 0,
                "count_rps_50": 0,
                "count_rps_120": 0,
                "count_rps_250": 0,
            },
        )
        bucket["count"] = int(bucket["count"] or 0) + 1
        for window in (20, 50, 120, 250):
            value = _coerce_float(row.get(f"rps_{window}"))
            if value is None:
                continue
            bucket[f"sum_rps_{window}"] = float(bucket[f"sum_rps_{window}"] or 0.0) + value
            bucket[f"count_rps_{window}"] = int(bucket[f"count_rps_{window}"] or 0) + 1

    valuation_lookup: dict[tuple[str, str], dict[str, object]] = {}
    for row in valuation_rows:
        top_level_temperature_label = row.get("industry_temperature_label")
        if top_level_temperature_label in (None, ""):
            top_level_temperature_label = row.get("temperature_label")
        top_level_temperature_pct = row.get("industry_temperature_percentile_since_2022")
        if top_level_temperature_pct in (None, ""):
            top_level_temperature_pct = row.get("temperature_percentile_since_2022")
        top_level_level1 = row.get("industry_level_1_name") or row.get("industry_level_1")
        top_level_level2 = row.get("industry_level_2_name") or row.get("industry_level_2")
        for member in row.get("member_valuation_rows") or []:
            if not isinstance(member, dict):
                continue
            market = _normalize_text(member.get("market")).lower()
            symbol = _normalize_text(member.get("symbol"))
            if not market or not symbol:
                continue
            valuation_lookup[(market, symbol)] = {
                "current_price": _extract_member_metric(member, "current_price", "price", "close"),
                "pe_ttm": _extract_member_metric(member, "pe_ttm"),
                "ps_ttm": _extract_member_metric(member, "ps_ttm"),
                "total_market_cap": _extract_member_metric(member, "total_market_cap"),
                "free_float_market_cap": _extract_member_metric(member, "free_float_market_cap"),
                "classification": _extract_member_metric(member, "classification", "valuation_classification"),
                "sub_classification": _extract_member_metric(member, "sub_classification", "classification_subtype", "classification_code"),
                "classification_label": _extract_member_metric(member, "classification_label"),
                "valuation_band": _extract_member_metric(member, "valuation_band"),
                "valuation_band_label": _extract_member_metric(member, "valuation_band_label", "band_label"),
                "primary_metric": _extract_member_metric(member, "primary_metric", "primary_percentile_metric"),
                "primary_percentile": _extract_member_metric(member, "primary_percentile", "percentile", "industry_percentile"),
                "industry_temperature_label": top_level_temperature_label,
                "industry_temperature_percentile_since_2022": top_level_temperature_pct,
                "industry_level_1": top_level_level1,
                "industry_level_2": top_level_level2,
            }

    strategy_lookup: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in strategy_rows:
        market = _normalize_text(row.get("market")).lower()
        symbol = _normalize_text(row.get("symbol"))
        strategy = _normalize_text(row.get("strategy"))
        if not market or not symbol or not strategy:
            continue
        strategy_lookup[(market, symbol, strategy)] = row

    rows: list[dict[str, object]] = []
    for score_key, score_entry in score_rows.items():
        if not isinstance(score_entry, dict):
            continue
        market, _, symbol = str(score_key).partition(":")
        market = market.strip().lower()
        symbol = symbol.strip()
        if not market or not symbol:
            continue
        key = (market, symbol)
        security = security_lookup.get(key) or {}
        industry = industry_lookup.get(key) or {}
        valuation = valuation_lookup.get(key) or {}
        rps = rps_lookup.get(key) or {}
        dim_scores = score_entry.get("dim_scores") if isinstance(score_entry.get("dim_scores"), dict) else {}
        ind_dim_scores = score_entry.get("ind_dim_scores") if isinstance(score_entry.get("ind_dim_scores"), dict) else {}
        sub_indicators = score_entry.get("sub_indicators") if isinstance(score_entry.get("sub_indicators"), dict) else {}
        ind_sub_indicators = score_entry.get("ind_sub_indicators") if isinstance(score_entry.get("ind_sub_indicators"), dict) else {}
        industry_level_1 = (
            _normalize_text(score_entry.get("industry_sw_level_1"))
            or _normalize_text(industry.get("industry_level_1_name"))
            or _normalize_text(valuation.get("industry_level_1"))
        )
        industry_level_2 = (
            _normalize_text(score_entry.get("industry_sw_level_2"))
            or _normalize_text(industry.get("industry_level_2_name"))
            or _normalize_text(valuation.get("industry_level_2"))
        )
        industry_rps = industry_rps_aggregate.get(industry_level_2) or {}
        classification = _normalize_text(valuation.get("classification"))
        sub_classification = _normalize_text(valuation.get("sub_classification"))
        valuation_band_label = _normalize_text(valuation.get("valuation_band_label")) or _normalize_text(valuation.get("valuation_band"))
        current_price = _coerce_float(valuation.get("current_price"))
        primary_percentile = _coerce_float(valuation.get("primary_percentile"))
        market_total_rank = _coerce_int(score_entry.get("market_total_rank")) or market_rank_lookup.get(score_key)
        industry_total_rank = _coerce_int(score_entry.get("industry_total_rank")) or industry_rank_lookup.get(score_key)
        market_total_universe_size = _coerce_int(score_entry.get("market_total_universe_size")) or market_universe_size or None
        industry_total_universe_size = (
            _coerce_int(score_entry.get("industry_total_universe_size"))
            or industry_universe_sizes.get(industry_level_2)
        )
        row = {
            "market": market,
            "symbol": symbol,
            "stock_name": _normalize_text(security.get("stock_name")) or _normalize_text(score_entry.get("stock_name")) or symbol,
            "current_price": current_price,
            "pe_ttm": _coerce_float(valuation.get("pe_ttm")),
            "ps_ttm": _coerce_float(valuation.get("ps_ttm")),
            "total_market_cap": _coerce_float(valuation.get("total_market_cap")),
            "free_float_market_cap": _coerce_float(valuation.get("free_float_market_cap")),
            "industry_level_1": industry_level_1,
            "industry_level_2": industry_level_2,
            "market_total_score": market_score_lookup.get(score_key, _coerce_float(score_entry.get("total_score"))),
            "market_absolute_score": market_abs_lookup.get(score_key),
            "market_trend_score": market_trend_lookup.get(score_key),
            "industry_total_score": industry_score_lookup.get(score_key, _coerce_float(score_entry.get("ind_total_score"))),
            "industry_absolute_score": industry_abs_lookup.get(score_key),
            "industry_trend_score": industry_trend_lookup.get(score_key),
            "score_divergence": _score_divergence_label(
                market_abs_lookup.get(score_key), market_trend_lookup.get(score_key)
            ),
            "market_total_rank": market_total_rank,
            "market_total_universe_size": market_total_universe_size,
            "industry_total_rank": industry_total_rank,
            "industry_total_universe_size": industry_total_universe_size,
            "classification": classification,
            "classification_label": _normalize_text(valuation.get("classification_label")) or _classification_label(classification, sub_classification),
            "valuation_band": _normalize_text(valuation.get("valuation_band")),
            "valuation_band_label": valuation_band_label,
            "primary_metric": _normalize_text(valuation.get("primary_metric")),
            "primary_percentile": primary_percentile,
            "industry_temperature_label": _normalize_text(valuation.get("industry_temperature_label")),
            "industry_temperature_percentile_since_2022": _coerce_float(
                valuation.get("industry_temperature_percentile_since_2022")
            ),
            "dim_scores": dim_scores,
            "ind_dim_scores": ind_dim_scores,
            "sub_indicators": sub_indicators,
            "ind_sub_indicators": ind_sub_indicators,
            "rps_20": _coerce_float(rps.get("rps_20")),
            "rps_50": _coerce_float(rps.get("rps_50")),
            "rps_120": _coerce_float(rps.get("rps_120")),
            "rps_250": _coerce_float(rps.get("rps_250")),
            "strategy": None,
            "strategy_label": None,
            "industry_rps_20": None,
            "industry_rps_50": None,
            "industry_rps_120": None,
            "industry_rps_250": None,
        }
        # Add 5-year price percentile
        pct_data = price_pct_lookup.get(symbol) or {}
        row["price_percentile_5y"] = _coerce_float(pct_data.get("price_percentile_5y"))
        row["price_band_5y"] = pct_data.get("price_band_5y")
        # Add technical evaluation
        tech = tech_eval_rows.get(symbol) or {}
        for field in ("trend", "trend_label", "trend_prev", "trend_prev_label", "momentum", "momentum_label",
                      "short_trend", "short_trend_label", "short_trend_prev", "short_trend_prev_label",
                      "volume_signal", "volume_label", "position", "position_label",
                      "buy_trigger", "buy_trigger_label", "conclusion", "conclusion_label",
                      "conclusion_color", "conclusion_reason", "entry_price", "stop_loss",
                      "risk_pct", "golden_cross", "golden_cross_label", "macd_cross", "macd_cross_label"):
            row[f"tech_{field}"] = tech.get(field)
        for window in (20, 50, 120, 250):
            count_key = f"count_rps_{window}"
            count = int(industry_rps.get(count_key) or 0)
            if count > 0:
                row[f"industry_rps_{window}"] = round(float(industry_rps.get(f"sum_rps_{window}") or 0.0) / count, 2)
        if active_strategy:
            strategy_entry = strategy_lookup.get((market, symbol, active_strategy)) or {}
            if _coerce_bool(strategy_entry.get("passed")):
                row["strategy"] = _normalize_text(strategy_entry.get("strategy")) or None
                row["strategy_label"] = (
                    "RPS标准" if active_strategy == "rps_standard_launch"
                    else (_normalize_text(strategy_entry.get("strategy_label")) or None)
                )
        rows.append(row)

    text_filters = {
        "industry_level_1": "industry_level_1",
        "industry_level_2": "industry_level_2",
        "industry_temperature_label": "industry_temperature_label",
        "classification": "classification",
        "valuation_band": "valuation_band_label",
        "score_divergence": "score_divergence",
    }
    numeric_field_filters = {
        "min_total_score": ("market_total_score", "min"),
        "min_ind_total_score": ("industry_total_score", "min"),
        "max_market_rank": ("market_total_rank", "max"),
        "max_industry_rank": ("industry_total_rank", "max"),
        "min_primary_percentile": ("primary_percentile", "min"),
        "max_primary_percentile": ("primary_percentile", "max"),
        "min_current_price": ("current_price", "min"),
        "max_current_price": ("current_price", "max"),
        "min_pe_ttm": ("pe_ttm", "min"),
        "max_pe_ttm": ("pe_ttm", "max"),
        "min_price_percentile_5y": ("price_percentile_5y", "min"),
        "max_price_percentile_5y": ("price_percentile_5y", "max"),
    }
    # Technical evaluation text filters (value matching)
    tech_text_filters = {
        "tech_trend": "tech_trend",
        "tech_short_trend": "tech_short_trend",
        "tech_momentum": "tech_momentum",
        "tech_volume": "tech_volume_signal",
        "tech_position": "tech_position",
        "tech_conclusion": "tech_conclusion",
        "tech_buy_trigger": "tech_buy_trigger",
        "golden_cross": "tech_golden_cross",
        "macd_cross": "tech_macd_cross",
    }

    filtered = rows
    if active_strategy:
        if strategy_rows:
            filtered = [row for row in filtered if row.get("strategy") == active_strategy]
        else:
            # Strategy data not yet built for this historical date — show empty
            filtered = []
    for param_key, field_name in text_filters.items():
        expected = _normalize_text(params.get(param_key))
        if not expected:
            continue
        if param_key in {"industry_temperature_label", "valuation_band", "industry_level_1", "industry_level_2"}:
            expected_values = {
                value.strip()
                for value in expected.split(",")
                if value.strip()
            }
            if not expected_values:
                continue
            filtered = [
                row for row in filtered
                if _normalize_text(row.get(field_name)) in expected_values
            ]
            continue
        filtered = [row for row in filtered if _matches_keyword_filter(row.get(field_name), expected)]

    # Apply technical evaluation text filters (support !prefix for "not", comma-separated for OR)
    for param_key, field_name in tech_text_filters.items():
        raw = _normalize_text(params.get(param_key))
        if not raw:
            continue

        # Support comma-separated multi-select (OR logic)
        raw_values = [v.strip() for v in raw.split(",") if v.strip()]
        _negation_map = {
            "bearish": {"bearish", "strong_bearish"},
            "weak": {"weak"},
            "divergence": {"divergence"},
            "high": {"high", "overheated"},
            "avoid": {"avoid"},
        }
        if len(raw_values) > 1:
            # Multi-select OR: any match passes
            if any(v.startswith("!") for v in raw_values):
                exclude_set = set()
                for v in raw_values:
                    if v.startswith("!"):
                        exclude_set |= _negation_map.get(v[1:], {v[1:]})
                positives = [v for v in raw_values if not v.startswith("!")]
                if positives:
                    filtered = [row for row in filtered
                        if not any(x.strip() in exclude_set for x in _normalize_text(row.get(field_name)).split(","))
                        or any(v in [x.strip() for x in _normalize_text(row.get(field_name)).split(",")] for v in positives)]
                else:
                    filtered = [row for row in filtered
                        if not any(x.strip() in exclude_set for x in _normalize_text(row.get(field_name)).split(","))]
            else:
                filtered = [row for row in filtered
                    if any(v in [x.strip() for x in _normalize_text(row.get(field_name)).split(",")] for v in raw_values)]
            continue

        raw = raw_values[0]
        if raw.startswith("!"):
            # "not" filter: semantic exclusion (e.g. !bearish excludes bearish+strong_bearish)
            exclude_val = raw[1:]
            _negation_map = {
                "bearish": {"bearish", "strong_bearish"},
                "weak": {"weak"},
                "divergence": {"divergence"},
                "high": {"high", "overheated"},
                "avoid": {"avoid"},
            }
            exclude_set = _negation_map.get(exclude_val, {exclude_val})
            filtered = [row for row in filtered if _normalize_text(row.get(field_name)) not in exclude_set]
        elif raw == "any":
            # "any" means any non-null value
            filtered = [row for row in filtered if row.get(field_name)]
        else:
            # Single value: check if it matches the field (or any comma-separated part)
            filtered = [row for row in filtered
                if raw in [x.strip() for x in _normalize_text(row.get(field_name)).split(",")]]


    # Trend switch filter: today trend == target AND yesterday trend != target
    trend_switch_target = _normalize_text(params.get("trend_switch"))
    if trend_switch_target:
        filtered = [
            row for row in filtered
            if _normalize_text(row.get("tech_trend")) == trend_switch_target
            and _normalize_text(row.get("tech_trend_prev")) != trend_switch_target
            and _normalize_text(row.get("tech_trend_prev")) != ""
        ]

    # Short trend switch filter
    short_trend_switch_target = _normalize_text(params.get("short_trend_switch"))
    if short_trend_switch_target:
        filtered = [
            row for row in filtered
            if _normalize_text(row.get("tech_short_trend")) == short_trend_switch_target
            and _normalize_text(row.get("tech_short_trend_prev")) != short_trend_switch_target
            and _normalize_text(row.get("tech_short_trend_prev")) != ""
        ]

    # MACD signal filter
    macd_signal_target = _normalize_text(params.get("macd_signal"))
    if macd_signal_target:
        macd_data = _load_macd_signals(as_of_date=as_of_date)
        if macd_data:
            filtered = [
                row for row in filtered
                if macd_data.get(f"{_normalize_text(row.get('market'))}:{_normalize_text(row.get('symbol'))}") == macd_signal_target
            ]
        else:
            # MACD data not yet built for this date — return empty
            filtered = []

    for param_key, (field_name, bound) in numeric_field_filters.items():
        threshold = _coerce_float(params.get(param_key))
        if threshold is None:
            continue
        if bound == "min":
            filtered = [row for row in filtered if _passes_min_max(row.get(field_name), min_value=threshold)]
        else:
            filtered = [row for row in filtered if _passes_min_max(row.get(field_name), max_value=threshold)]

    for param_key, raw_value in params.items():
        threshold = _coerce_float(raw_value)
        if threshold is None:
            continue
        if param_key in {"min_dim_operating", "max_dim_operating"}:
            continue
        if param_key.startswith("min_dim_"):
            dim_key = param_key[8:]
            weight = _DIM_WEIGHTS.get(dim_key, 1.0)
            adjusted_threshold = threshold * weight if weight > 0 else threshold
            filtered = [
                row for row in filtered
                if _passes_min_max((row.get("dim_scores") or {}).get(dim_key), min_value=adjusted_threshold)
            ]
            continue
        if param_key.startswith("max_dim_"):
            dim_key = param_key[8:]
            weight = _DIM_WEIGHTS.get(dim_key, 1.0)
            adjusted_threshold = threshold * weight if weight > 0 else threshold
            filtered = [
                row for row in filtered
                if _passes_min_max((row.get("dim_scores") or {}).get(dim_key), max_value=adjusted_threshold)
            ]
            continue
        if param_key.startswith("min_sub_"):
            sub_key = param_key[8:]
            filtered = [
                row for row in filtered
                if _passes_min_max((row.get("sub_indicators") or {}).get(sub_key), min_value=threshold)
            ]
            continue
        if param_key.startswith("max_sub_"):
            sub_key = param_key[8:]
            filtered = [
                row for row in filtered
                if _passes_min_max((row.get("sub_indicators") or {}).get(sub_key), max_value=threshold)
            ]
            continue
        for prefix, field_base in (
            ("min_rps_", "rps_"),
            ("max_rps_", "rps_"),
            ("min_industry_rps_", "industry_rps_"),
            ("max_industry_rps_", "industry_rps_"),
        ):
            if not param_key.startswith(prefix):
                continue
            suffix = param_key[len(prefix):]
            if suffix not in {"20", "50", "120", "250", "total"}:
                continue
            if suffix == "total":
                # Sum all 4 RPS periods
                def _rps_total(row):
                    return sum(row.get(f"{field_base}{w}") or 0 for w in ("20","50","120","250"))
                if prefix.startswith("min_"):
                    filtered = [row for row in filtered if _rps_total(row) >= threshold]
                else:
                    filtered = [row for row in filtered if _rps_total(row) <= threshold]
            else:
                field_name = f"{field_base}{suffix}"
                if prefix.startswith("min_"):
                    filtered = [row for row in filtered if _passes_min_max(row.get(field_name), min_value=threshold)]
                else:
                    filtered = [row for row in filtered if _passes_min_max(row.get(field_name), max_value=threshold)]
            break

    filtered.sort(
        key=lambda row: (
            -(row.get("market_total_score") if row.get("market_total_score") is not None else -1.0),
            int(row.get("market_total_rank") if row.get("market_total_rank") is not None else 10**9),
            str(row.get("market", "")),
            str(row.get("symbol", "")),
        )
    )

    page = _coerce_int(params.get("page")) or 1
    if page < 1:
        page = 1
    page_size = _coerce_int(params.get("page_size")) or 50
    if page_size < 1:
        page_size = 50
    page_size = min(page_size, 200)
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    end = start + page_size

    data_date = ""
    if rps_rows:
        data_date = str(rps_rows[0].get("trading_day", ""))
    effective_date = data_date
    if as_of_date:
        effective_date = as_of_date
    return {
        "ok": True,
        "active_strategy": active_strategy or None,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": filtered[start:end],
        "data_date": data_date,
        "effective_date": effective_date,
        "is_historical": bool(as_of_date),
        "tech_eval_ready": bool(tech_eval_rows),
        "strategy_ready": bool(strategy_rows) if active_strategy else True,
    }


_REALTIME_SCENARIO_DEFAULTS: dict[str, dict[str, object]] = {
    "tail_session": {
        "label": "尾盘选股",
        "conditions": {
            "gain_min_pct": 3.0,
            "gain_max_pct": 5.0,
            "limit_up_lookback_days": 20,
            "min_volume_ratio": 1.4,
            "max_market_cap_yi": 200.0,
            "turnover_min_pct": 5.0,
            "turnover_max_pct": 10.0,
            "intraday_above_vwap": True,
            "intraday_above_vwap_min_ratio_pct": 80.0,
            "intraday_vwap_max_breach_pct": 0.3,
            "current_above_open": True,
        },
    },
    "rps_pullback": {
        "label": "RPS回踩",
        "conditions": {
            "rps250_min": 80.0,
            "rps120_min": 85.0,
            "rps50_min": 88.0,
            "rps20_min": 92.0,
            "volume_ratio_min": 1.2,
            "overheat_ratio_max": 1.08,
        },
    },
    "scheme_2560": {
        "label": "2560",
        "conditions": {
            # ── 基础条件 ──
            "min_listed_days": 120,
            "min_amount_20d_yi": 1.0,
            "min_price": 5.0,
            "price_above_ma60": True,
            "gain_20d_max_pct": 35.0,
            "ma25_trend_up_5d": True,
            "ma25_trend_up_5d_pct": 0.5,
            "ma25_above_ma10": True,
            "price_above_ma25": True,
            "price_ma25_range_pct": 8.0,
            "vol_ratio_5d_60d_min": 1.15,
            "vol_ratio_5d_60d_max": 2.5,
            # ── 回踩买点* ──
            "pb_trend_ma25_5d": True,
            "pb_trend_ma25_5d_pct": 0.5,
            "pb_vol_ratio_min": 1.15,
            "pb_vol_ratio_max": 2.5,
            "pb_low_max_ma25_pct": 1.03,
            "pb_close_above_ma25": True,
            "pb_low_min_ma25_pct": 0.97,
            "pb_kline_mid_strong": True,
            "pb_price_ma25_max_pct": 5.0,
            # ── 突破买点 ──
            "bo_range_10d_max_pct": 12.0,
            "bo_vol_drop_min_pct": 15.0,
            "bo_close_break_ratio": 1.01,
            "bo_vol_burst_min": 1.3,
            "bo_vol_burst_max": 3.0,
            "bo_price_ma25_max_pct": 10.0,
            "bo_ma25_trend_up": True,
            "bo_ma25_trend_up_pct": 0.5,
            # ── 强势回踩 ──
            "sp_gain_30d_min_pct": 20.0,
            "sp_gain_30d_max_pct": 60.0,
            "sp_above_ma25_days": 20,
            "sp_recent_revert_max_pct": 1.03,
            "sp_close_above_ma25": True,
            "sp_low_min_ma25_pct": 0.97,
            "sp_vol_shrink_max_ratio": 0.7,
            "sp_vol_below_vma5": True,
            "sp_kline_mid_strong": True,
            "sp_vol_ratio_min": 1.15,
        },
    },
    "ma_cross": {
        "label": "均线选股",
        "conditions": {},
    },
}


def load_realtime_quote_rows(batch_size: int = 80) -> list[dict[str, object]]:
    """Load current沪深A股 quote snapshots from mootdx; 北交所 is skipped for this path."""
    from mootdx.quotes import Quotes

    securities = [
        row for row in load_security_rows()
        if str(row.get("market", "")).lower() in {"sh", "sz"}
    ]
    symbols = [str(row.get("symbol", "")).strip() for row in securities if str(row.get("symbol", "")).strip()]
    client = Quotes.factory(market="std")
    rows: list[dict[str, object]] = []
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start:start + batch_size]
        if not batch:
            continue
        try:
            frame = client.quotes(symbol=batch)
        except Exception:
            continue
        if frame is None or getattr(frame, "empty", True):
            continue
        for item in frame.to_dict("records"):
            market_id = _coerce_int(item.get("market"))
            market = "sh" if market_id == 1 else "sz"
            rows.append({
                "market": market,
                "symbol": _normalize_text(item.get("code")),
                "price": _coerce_float(item.get("price")),
                "last_close": _coerce_float(item.get("last_close")),
                "open": _coerce_float(item.get("open")),
                "high": _coerce_float(item.get("high")),
                "low": _coerce_float(item.get("low")),
                "volume": _coerce_float(item.get("volume") if item.get("volume") not in (None, "") else item.get("vol")),
                "amount": _coerce_float(item.get("amount")),
                "servertime": item.get("servertime"),
            })
    return [row for row in rows if row.get("symbol")]


@lru_cache(maxsize=4096)
def load_realtime_intraday_points(market: str, symbol: str) -> list[dict[str, object]]:
    """Load current-day realtime minute points from mootdx for VWAP strength checks."""
    del market
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        frame = client.minute(symbol=symbol)
    except Exception:
        return []
    if frame is None or getattr(frame, "empty", True):
        return []
    points: list[dict[str, object]] = []
    for item in frame.to_dict("records"):
        price = _coerce_float(item.get("price"))
        volume = _coerce_float(item.get("volume") if item.get("volume") not in (None, "") else item.get("vol"))
        amount = _coerce_float(item.get("amount"))
        if price is None or volume in (None, 0.0):
            continue
        point: dict[str, object] = {"price": price, "volume": volume}
        if amount is not None:
            point["amount"] = amount
        points.append(point)
    return points


@lru_cache(maxsize=10000)
def _recent_avg_daily_volume(market: str, symbol: str, days: int = 5) -> float | None:
    try:
        from mootdx.reader import Reader
        reader = Reader.factory(market="std", tdxdir="/mnt/c/new_tdx64")
        daily = reader.daily(symbol=symbol)
    except Exception:
        return None
    if daily is None or daily.empty or "volume" not in daily:
        return None
    values = [float(v) for v in daily.sort_index()["volume"].tail(days).tolist() if v == v]
    if not values:
        return None
    return sum(values) / len(values)


@lru_cache(maxsize=10000)
def _has_recent_limit_up(market: str, symbol: str, days: int) -> bool:
    try:
        from mootdx.reader import Reader
        reader = Reader.factory(market="std", tdxdir="/mnt/c/new_tdx64")
        daily = reader.daily(symbol=symbol)
    except Exception:
        return False
    if daily is None or daily.empty or "close" not in daily:
        return False
    closes = [float(v) for v in daily.sort_index()["close"].tail(days + 1).tolist() if v == v]
    for previous, current in zip(closes, closes[1:]):
        if previous > 0 and (current / previous - 1) * 100 >= 9.8:
            return True
    return False


@lru_cache(maxsize=10000)
def _recent_daily_bars(market: str, symbol: str, count: int = 300) -> list[dict[str, object]]:
    """Return recent daily bars for a stock from local Tongdaxin data."""
    try:
        from mootdx.reader import Reader
        reader = Reader.factory(market="std", tdxdir="/mnt/c/new_tdx64")
        daily = reader.daily(symbol=symbol)
    except Exception:
        return []
    if daily is None or daily.empty:
        return []
    bars: list[dict[str, object]] = []
    for _, row in daily.sort_index().tail(count).iterrows():
        bars.append({
            "open": _coerce_float(row.get("open")),
            "high": _coerce_float(row.get("high")),
            "low": _coerce_float(row.get("low")),
            "close": _coerce_float(row.get("close")),
            "volume": _coerce_float(row.get("volume")),
        })
    return bars


def _realtime_valuation_lookup() -> dict[tuple[str, str], dict[str, object]]:
    lookup: dict[tuple[str, str], dict[str, object]] = {}
    for group in load_industry_valuation_rows():
        for member in group.get("member_valuation_rows") or []:
            if not isinstance(member, dict):
                continue
            key = (_normalize_text(member.get("market")).lower(), _normalize_text(member.get("symbol")))
            if key[0] and key[1]:
                lookup[key] = member
    return lookup


def _parse_realtime_conditions(params: dict[str, str], defaults: dict[str, object]) -> dict[str, object]:
    conditions = {
        "gain_min_pct": _coerce_float(params.get("gain_min_pct")),
        "gain_max_pct": _coerce_float(params.get("gain_max_pct")),
        "limit_up_lookback_days": _coerce_int(params.get("limit_up_lookback_days")),
        "min_volume_ratio": _coerce_float(params.get("min_volume_ratio")),
        "max_market_cap_yi": _coerce_float(params.get("max_market_cap_yi")),
        "turnover_min_pct": _coerce_float(params.get("turnover_min_pct")),
        "turnover_max_pct": _coerce_float(params.get("turnover_max_pct")),
        "intraday_above_vwap": _coerce_bool(params.get("intraday_above_vwap", defaults.get("intraday_above_vwap"))),
        "intraday_above_vwap_min_ratio_pct": _coerce_float(params.get("intraday_above_vwap_min_ratio_pct")),
        "intraday_vwap_max_breach_pct": _coerce_float(params.get("intraday_vwap_max_breach_pct")),
        "current_above_open": _coerce_bool(params.get("current_above_open", defaults.get("current_above_open"))),
        "rps250_min": _coerce_float(params.get("rps250_min")),
        "rps120_min": _coerce_float(params.get("rps120_min")),
        "rps50_min": _coerce_float(params.get("rps50_min")),
        "rps20_min": _coerce_float(params.get("rps20_min")),
        "volume_ratio_min": _coerce_float(params.get("volume_ratio_min")),
        "overheat_ratio_max": _coerce_float(params.get("overheat_ratio_max")),
        # ── scheme_2560: 基础条件 ──
        "min_listed_days": _coerce_int(params.get("min_listed_days")),
        "min_amount_20d_yi": _coerce_float(params.get("min_amount_20d_yi")),
        "min_price": _coerce_float(params.get("min_price")),
        "price_above_ma60": _coerce_bool(params.get("price_above_ma60", defaults.get("price_above_ma60"))),
        "gain_20d_max_pct": _coerce_float(params.get("gain_20d_max_pct")),
        "ma25_trend_up_5d": _coerce_bool(params.get("ma25_trend_up_5d", defaults.get("ma25_trend_up_5d"))),
        "ma25_trend_up_5d_pct": _coerce_float(params.get("ma25_trend_up_5d_pct")),
        "ma25_above_ma10": _coerce_bool(params.get("ma25_above_ma10", defaults.get("ma25_above_ma10"))),
        "price_above_ma25": _coerce_bool(params.get("price_above_ma25", defaults.get("price_above_ma25"))),
        "price_ma25_range_pct": _coerce_float(params.get("price_ma25_range_pct")),
        "vol_ratio_5d_60d_min": _coerce_float(params.get("vol_ratio_5d_60d_min")),
        "vol_ratio_5d_60d_max": _coerce_float(params.get("vol_ratio_5d_60d_max")),
        # ── scheme_2560: 回踩买点* ──
        "pb_trend_ma25_5d": _coerce_bool(params.get("pb_trend_ma25_5d", defaults.get("pb_trend_ma25_5d"))),
        "pb_trend_ma25_5d_pct": _coerce_float(params.get("pb_trend_ma25_5d_pct")),
        "pb_vol_ratio_min": _coerce_float(params.get("pb_vol_ratio_min")),
        "pb_vol_ratio_max": _coerce_float(params.get("pb_vol_ratio_max")),
        "pb_low_max_ma25_pct": _coerce_float(params.get("pb_low_max_ma25_pct")),
        "pb_close_above_ma25": _coerce_bool(params.get("pb_close_above_ma25", defaults.get("pb_close_above_ma25"))),
        "pb_low_min_ma25_pct": _coerce_float(params.get("pb_low_min_ma25_pct")),
        "pb_kline_mid_strong": _coerce_bool(params.get("pb_kline_mid_strong", defaults.get("pb_kline_mid_strong"))),
        "pb_price_ma25_max_pct": _coerce_float(params.get("pb_price_ma25_max_pct")),
        # ── scheme_2560: 突破买点 ──
        "bo_range_10d_max_pct": _coerce_float(params.get("bo_range_10d_max_pct")),
        "bo_vol_drop_min_pct": _coerce_float(params.get("bo_vol_drop_min_pct")),
        "bo_close_break_ratio": _coerce_float(params.get("bo_close_break_ratio")),
        "bo_vol_burst_min": _coerce_float(params.get("bo_vol_burst_min")),
        "bo_vol_burst_max": _coerce_float(params.get("bo_vol_burst_max")),
        "bo_price_ma25_max_pct": _coerce_float(params.get("bo_price_ma25_max_pct")),
        "bo_ma25_trend_up_pct": _coerce_float(params.get("bo_ma25_trend_up_pct")),
        # ── scheme_2560: 强势回踩 ──
        "sp_gain_30d_min_pct": _coerce_float(params.get("sp_gain_30d_min_pct")),
        "sp_gain_30d_max_pct": _coerce_float(params.get("sp_gain_30d_max_pct")),
        "sp_above_ma25_days": _coerce_int(params.get("sp_above_ma25_days")),
        "sp_recent_revert_max_pct": _coerce_float(params.get("sp_recent_revert_max_pct")),
        "sp_close_above_ma25": _coerce_bool(params.get("sp_close_above_ma25", defaults.get("sp_close_above_ma25"))),
        "sp_low_min_ma25_pct": _coerce_float(params.get("sp_low_min_ma25_pct")),
        "sp_vol_shrink_max_ratio": _coerce_float(params.get("sp_vol_shrink_max_ratio")),
        "sp_vol_below_vma5": _coerce_bool(params.get("sp_vol_below_vma5", defaults.get("sp_vol_below_vma5"))),
        "sp_kline_mid_strong": _coerce_bool(params.get("sp_kline_mid_strong", defaults.get("sp_kline_mid_strong"))),
        "sp_vol_ratio_min": _coerce_float(params.get("sp_vol_ratio_min")),
    }
    for key, default_value in defaults.items():
        if conditions.get(key) is None:
            conditions[key] = default_value
    return conditions


def _parse_realtime_condition_enabled(params: dict[str, str]) -> dict[str, bool]:
    return {
        "gain_pct": _coerce_bool(params.get("enable_gain_pct", True)),
        "limit_up_lookback_days": _coerce_bool(params.get("enable_limit_up_lookback_days", True)),
        "min_volume_ratio": _coerce_bool(params.get("enable_min_volume_ratio", True)),
        "max_market_cap_yi": _coerce_bool(params.get("enable_max_market_cap_yi", True)),
        "turnover_pct": _coerce_bool(params.get("enable_turnover_pct", True)),
        "intraday_above_vwap": _coerce_bool(params.get("enable_intraday_above_vwap", True)),
        "current_above_open": _coerce_bool(params.get("enable_current_above_open", True)),
        # scheme_2560 module enables
        "module_basic": _coerce_bool(params.get("enable_module_basic", True)),
        "module_pullback_buy": _coerce_bool(params.get("enable_module_pullback_buy", True)),
        "module_breakout_buy": _coerce_bool(params.get("enable_module_breakout_buy", False)),
        "module_strong_pullback": _coerce_bool(params.get("enable_module_strong_pullback", False)),
    }


def _extract_intraday_points(quote: dict[str, object]) -> list[dict[str, object]]:
    for key in ("intraday_points", "minute_points", "points"):
        points = quote.get(key)
        if isinstance(points, list):
            return [point for point in points if isinstance(point, dict)]
    for value in quote.values():
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            if any("price" in item for item in value):
                return list(value)
    return []


def _point_amount_volume(point: dict[str, object]) -> tuple[float | None, float | None]:
    volume = _coerce_float(point.get("volume") if point.get("volume") not in (None, "") else point.get("vol"))
    amount = _coerce_float(point.get("amount"))
    price = _coerce_float(point.get("price"))
    if amount is None and price is not None and volume not in (None, 0.0):
        amount = price * float(volume) * 100.0
    return amount, volume


def _passes_intraday_vwap_condition(quote: dict[str, object], conditions: dict[str, object]) -> bool:
    min_ratio_pct = _coerce_float(conditions.get("intraday_above_vwap_min_ratio_pct"))
    max_breach_pct = _coerce_float(conditions.get("intraday_vwap_max_breach_pct"))
    min_ratio_pct = 80.0 if min_ratio_pct is None else min_ratio_pct
    max_breach_pct = 0.3 if max_breach_pct is None else max_breach_pct
    breach_factor = 1.0 - max_breach_pct / 100.0

    points = _extract_intraday_points(quote)
    if points:
        cumulative_amount = 0.0
        cumulative_volume = 0.0
        above_count = 0
        valid_points = 0
        for point in points:
            price = _coerce_float(point.get("price"))
            amount, volume = _point_amount_volume(point)
            if price is None or amount is None or volume in (None, 0.0):
                continue
            cumulative_amount += float(amount)
            cumulative_volume += float(volume)
            if cumulative_volume <= 0:
                continue
            cumulative_vwap = cumulative_amount / (cumulative_volume * 100.0)
            valid_points += 1
            if price >= cumulative_vwap:
                above_count += 1
                continue
            if price < cumulative_vwap * breach_factor:
                return False
        if valid_points <= 0:
            return False
        return (above_count / valid_points) * 100.0 >= min_ratio_pct

    amount = _coerce_float(quote.get("amount"))
    volume = _coerce_float(quote.get("volume"))
    low = _coerce_float(quote.get("low"))
    if amount is None or volume in (None, 0.0) or low is None:
        return False
    current_vwap = amount / (volume * 100.0)
    return low >= current_vwap * breach_factor


def _build_tail_session_matches(conditions: dict[str, object], condition_enabled: dict[str, bool]) -> list[dict[str, object]]:
    security_lookup = {_security_key(row): row for row in load_security_rows()}
    industry_lookup = {_security_key(row): row for row in load_industry_rows()}
    valuation_lookup = _realtime_valuation_lookup()
    snapshot = _load_financial_snapshot() or {}
    score_rows = snapshot.get("scores") if isinstance(snapshot, dict) else {}
    if not isinstance(score_rows, dict):
        score_rows = {}
    _market_rank_lookup, _market_universe_size, industry_rank_lookup, industry_universe_sizes, _market_score_lookup, _industry_score_lookup, _market_abs_lookup, _market_trend_lookup, _industry_abs_lookup, _industry_trend_lookup = _score_rank_lookups(
        score_rows,
        industry_lookup,
    )
    rows: list[dict[str, object]] = []
    for quote in load_realtime_quote_rows():
        market = _normalize_text(quote.get("market")).lower()
        symbol = _normalize_text(quote.get("symbol"))
        price = _coerce_float(quote.get("price"))
        last_close = _coerce_float(quote.get("last_close"))
        if not market or not symbol or price is None or last_close in (None, 0.0):
            continue
        gain_pct = round((price / float(last_close) - 1.0) * 100.0, 4)
        if condition_enabled.get("gain_pct", True) and not _passes_min_max(gain_pct, min_value=_coerce_float(conditions.get("gain_min_pct")), max_value=_coerce_float(conditions.get("gain_max_pct"))):
            continue

        valuation = valuation_lookup.get((market, symbol)) or {}
        market_cap_yi = _coerce_float(valuation.get("total_market_cap"))
        if condition_enabled.get("max_market_cap_yi", True) and not _passes_min_max(market_cap_yi, max_value=_coerce_float(conditions.get("max_market_cap_yi"))):
            continue

        lookback_days = _coerce_int(conditions.get("limit_up_lookback_days")) or 20
        if condition_enabled.get("limit_up_lookback_days", True) and not _has_recent_limit_up(market, symbol, lookback_days):
            continue

        volume = _coerce_float(quote.get("volume"))
        volume_ratio = _coerce_float(quote.get("volume_ratio"))
        if volume_ratio is None and volume is not None:
            avg_volume = _recent_avg_daily_volume(market, symbol, 5)
            if avg_volume and avg_volume > 0:
                volume_ratio = volume / avg_volume
        if condition_enabled.get("min_volume_ratio", True) and not _passes_min_max(volume_ratio, min_value=_coerce_float(conditions.get("min_volume_ratio"))):
            continue

        free_float_market_cap_yi = _coerce_float(valuation.get("free_float_market_cap")) or market_cap_yi
        turnover_pct = None
        if volume is not None and free_float_market_cap_yi and free_float_market_cap_yi > 0 and price > 0:
            turnover_pct = (volume * 100.0 * price / (free_float_market_cap_yi * 100000000.0)) * 100.0
        if condition_enabled.get("turnover_pct", True) and not _passes_min_max(turnover_pct, min_value=_coerce_float(conditions.get("turnover_min_pct")), max_value=_coerce_float(conditions.get("turnover_max_pct"))):
            continue

        if condition_enabled.get("intraday_above_vwap", True) and _coerce_bool(conditions.get("intraday_above_vwap")):
            vwap_quote = quote
            if not _extract_intraday_points(quote):
                intraday_points = load_realtime_intraday_points(market, symbol)
                if intraday_points:
                    vwap_quote = {**quote, "intraday_points": intraday_points}
            if not _passes_intraday_vwap_condition(vwap_quote, conditions):
                continue

        open_price = _coerce_float(quote.get("open"))
        if condition_enabled.get("current_above_open", True) and _coerce_bool(conditions.get("current_above_open")):
            if open_price is None or price <= open_price:
                continue

        matched_conditions = ["涨幅", "涨停基因", "量比", "市值", "换手率"]
        if condition_enabled.get("intraday_above_vwap", True) and _coerce_bool(conditions.get("intraday_above_vwap")):
            matched_conditions.extend(["全天在均价线上方", "大部分时间在均价线上方"])
        if condition_enabled.get("current_above_open", True) and _coerce_bool(conditions.get("current_above_open")):
            matched_conditions.append("当前价高于开盘价")

        score_key = f"{market}:{symbol}"
        score_entry = score_rows.get(score_key) if isinstance(score_rows.get(score_key), dict) else {}
        security = security_lookup.get((market, symbol)) or {}
        industry = industry_lookup.get((market, symbol)) or {}
        industry_level_1 = (
            _normalize_text(score_entry.get("industry_sw_level_1"))
            or _normalize_text(industry.get("industry_level_1_name"))
        )
        industry_level_2 = (
            _normalize_text(score_entry.get("industry_sw_level_2"))
            or _normalize_text(industry.get("industry_level_2_name"))
        )
        rows.append({
            "market": market,
            "symbol": symbol,
            "stock_name": _normalize_text(security.get("stock_name")) or symbol,
            "current_price": round(price, 2),
            "gain_pct": round(gain_pct, 2),
            "volume_ratio": round(float(volume_ratio), 2) if volume_ratio is not None else None,
            "market_cap_yi": round(float(market_cap_yi), 2) if market_cap_yi is not None else None,
            "turnover_pct": round(float(turnover_pct), 2) if turnover_pct is not None else None,
            "industry_level_1": industry_level_1,
            "industry_level_2": industry_level_2,
            "industry_total_score": _industry_score_lookup.get(score_key, _coerce_float(score_entry.get("ind_total_score"))),
            "industry_total_rank": _coerce_int(score_entry.get("industry_total_rank")) or industry_rank_lookup.get(score_key),
            "industry_total_universe_size": (
                _coerce_int(score_entry.get("industry_total_universe_size"))
                or industry_universe_sizes.get(industry_level_2)
            ),
            "matched_conditions": matched_conditions,
        })
    rows.sort(key=lambda row: (-float(row.get("gain_pct") or 0.0), str(row.get("market", "")), str(row.get("symbol", ""))))
    return rows


def _build_rps_pullback_matches(
    conditions: dict[str, object],
    condition_enabled: dict[str, bool],
) -> list[dict[str, object]]:
    """Build RPS pullback matches using precomputed strategy signals + user-adjustable thresholds."""
    defaults = _REALTIME_SCENARIO_DEFAULTS.get("rps_pullback", {}).get("conditions", {})
    conditions = {**defaults, **{k: v for k, v in conditions.items() if v is not None}}

    strategy_rows = load_stock_screener_strategy_rows()
    rps_rows = load_rps_rows()
    security_rows = load_security_rows()
    industry_rows = load_industry_rows()
    snapshot = _load_financial_snapshot() or {}
    score_rows: dict[str, object] = snapshot.get("scores") if isinstance(snapshot, dict) else {}
    if not isinstance(score_rows, dict):
        score_rows = {}

    security_lookup: dict[tuple[str, str], dict[str, object]] = {_security_key(r): r for r in security_rows}
    industry_lookup: dict[tuple[str, str], dict[str, object]] = {_security_key(r): r for r in industry_rows}
    valuation_lookup: dict[tuple[str, str], dict[str, object]] = _realtime_valuation_lookup()
    _market_rank_lookup, _market_universe_size, industry_rank_lookup, industry_universe_sizes, _market_score_lookup, _industry_score_lookup, _market_abs_lookup, _market_trend_lookup, _industry_abs_lookup, _industry_trend_lookup = _score_rank_lookups(
        score_rows,
        industry_lookup,
    )

    rps_lookup: dict[tuple[str, str], dict[str, object]] = {_security_key(r): r for r in rps_rows}
    score_lookup: dict[str, dict[str, object]] = score_rows

    rows: list[dict[str, object]] = []

    rps250_min = _coerce_float(conditions.get("rps250_min")) or 80.0
    rps120_min = _coerce_float(conditions.get("rps120_min")) or 85.0
    rps50_min = _coerce_float(conditions.get("rps50_min")) or 88.0
    rps20_min = _coerce_float(conditions.get("rps20_min")) or 92.0
    volume_ratio_min = _coerce_float(conditions.get("volume_ratio_min")) or 1.2
    overheat_ratio_max = _coerce_float(conditions.get("overheat_ratio_max")) or 1.08

    for row in strategy_rows:
        if row.get("strategy") != "rps_pullback":
            continue

        market = _normalize_text(row.get("market")).lower()
        symbol = _normalize_text(row.get("symbol"))
        rps_row = rps_lookup.get((market, symbol)) or {}
        score_entry = score_lookup.get(f"{market}:{symbol}") or {}
        security = security_lookup.get((market, symbol)) or {}
        industry = industry_lookup.get((market, symbol)) or {}

        rps250 = _coerce_float(rps_row.get("rps_250"))
        rps120 = _coerce_float(rps_row.get("rps_120"))
        rps50 = _coerce_float(rps_row.get("rps_50"))
        rps20 = _coerce_float(rps_row.get("rps_20"))

        if not all(v is not None for v in (rps250, rps120, rps50, rps20)):
            continue
        if not (rps250 >= rps250_min and rps120 >= rps120_min and rps50 >= rps50_min and rps20 >= rps20_min):
            continue

        # Get current_price from valuation lookup first
        valuation = valuation_lookup.get((market, symbol)) or {}
        market_cap_yi = _coerce_float(valuation.get("total_market_cap"))
        current_price = _coerce_float(valuation.get("current_price"))

        # Calculate gain_pct, volume_ratio, turnover_pct from local Tongdaxin day bars
        gain_pct: float | None = None
        volume_ratio: float | None = None
        turnover_pct: float | None = None
        bars = _recent_daily_bars(market, symbol, count=250)
        if bars and len(bars) >= 2:
            latest = bars[-1]
            prev = bars[-2]
            close_cur = latest.get("close")
            close_prev = prev.get("close")
            vol_cur = latest.get("volume")
            if close_cur and close_prev and close_prev > 0:
                gain_pct = round((close_cur - close_prev) / close_prev * 100, 2)
            if vol_cur:
                avg_vol = sum(b.get("volume") or 0 for b in bars[-20:-1]) / min(len(bars) - 1, 19)
                if avg_vol > 0:
                    volume_ratio = round(vol_cur / avg_vol, 2)
            if vol_cur and market_cap_yi and market_cap_yi > 0:
                # turnover_pct = volume * price / market_cap (price in 元, market_cap in 亿)
                # volume * close / (market_cap_yi * 1e8) * 100
                turnover_pct = round(vol_cur * (close_cur or 0) / (market_cap_yi * 1e8) * 100, 2)

        if volume_ratio is not None and volume_ratio_min is not None and volume_ratio < volume_ratio_min:
            continue
        if overheat_ratio_max is not None and rps20 is not None and rps20 > (overheat_ratio_max * 100):
            continue

        industry_level_1 = (
            _normalize_text(score_entry.get("industry_sw_level_1"))
            or _normalize_text(industry.get("industry_level_1_name"))
        )
        industry_level_2 = (
            _normalize_text(score_entry.get("industry_sw_level_2"))
            or _normalize_text(industry.get("industry_level_2_name"))
        )
        score_key = f"{market}:{symbol}"
        industry_total_score = _industry_score_lookup.get(score_key, _coerce_float(score_entry.get("ind_total_score")))
        industry_total_rank = industry_rank_lookup.get(score_key)
        industry_total_universe_size = industry_universe_sizes.get(industry_level_2)
        stock_name = _normalize_text(security.get("stock_name")) or symbol

        rows.append({
            "market": market,
            "symbol": symbol,
            "stock_name": stock_name,
            "current_price": round(current_price, 2) if current_price else None,
            "gain_pct": round(gain_pct, 2) if gain_pct else None,
            "volume_ratio": round(volume_ratio, 2) if volume_ratio else None,
            "market_cap_yi": round(market_cap_yi, 1) if market_cap_yi else None,
            "turnover_pct": round(turnover_pct, 2) if turnover_pct else None,
            "industry_level_1": industry_level_1,
            "industry_level_2": industry_level_2,
            "industry_total_score": round(industry_total_score, 1) if industry_total_score else None,
            "industry_total_rank": int(industry_total_rank) if industry_total_rank else None,
            "industry_total_universe_size": int(industry_total_universe_size) if industry_total_universe_size else None,
        })

    rows.sort(key=lambda r: (-float(r.get("gain_pct") or 0.0), str(r.get("market", "")), str(r.get("symbol", ""))))
    return rows


# ─── scheme_2560 ─────────────────────────────────────────────────────────────────

def _ma(values: list[float], period: int) -> float | None:
    """Simple moving average of the most recent `period` values (newest last)."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _sma(values: list[float], period: int, idx: int) -> float | None:
    """SMA ending at index idx (inclusive), using `period` values."""
    start = idx + 1 - period
    if start < 0:
        return None
    window = values[start:idx + 1]
    if len(window) < period:
        return None
    return sum(window) / period


def _vol_ma(bars: list[dict[str, object]], period: int) -> float | None:
    """Volume SMA over `period` bars (newest last)."""
    if len(bars) < period:
        return None
    vols = [float(bar["volume"]) for bar in bars[-period:]]
    return sum(vols) / period


def _recent_amount_ma(bars: list[dict[str, object]], period: int) -> float | None:
    """成交额 SMA (单位：元)."""
    if len(bars) < period:
        return None
    amts = [float(bar.get("amount") or (float(bar["close"]) * float(bar["volume"]) * 100.0)) for bar in bars[-period:]]
    return sum(amts) / period


def _build_scheme_2560_matches(
    conditions: dict[str, object],
    condition_enabled: dict[str, bool],
) -> list[dict[str, object]]:
    """
    2560 方案选股逻辑
    四个模块: basic / pullback_buy / breakout_buy / strong_pullback
    模块之间为 AND 关系（所有开启的模块全部满足才入选）
    模块内部为 AND 关系（所有条件满足才算模块通过）
    """
    defaults = _REALTIME_SCENARIO_DEFAULTS.get("scheme_2560", {}).get("conditions", {})
    conditions = {**defaults, **{k: v for k, v in conditions.items() if v is not None}}

    module_enabled = {
        "basic": _coerce_bool(condition_enabled.get("module_basic", True)),
        "pullback_buy": _coerce_bool(condition_enabled.get("module_pullback_buy", True)),
        "breakout_buy": _coerce_bool(condition_enabled.get("module_breakout_buy", False)),
        "strong_pullback": _coerce_bool(condition_enabled.get("module_strong_pullback", False)),
    }

    security_rows = load_security_rows()
    industry_rows = load_industry_rows()
    security_lookup: dict[tuple[str, str], dict[str, object]] = {_security_key(r): r for r in security_rows}
    industry_lookup: dict[tuple[str, str], dict[str, object]] = {_security_key(r): r for r in industry_rows}
    snapshot = _load_financial_snapshot() or {}
    score_rows: dict[str, object] = snapshot.get("scores") if isinstance(snapshot, dict) else {}
    if not isinstance(score_rows, dict):
        score_rows = {}
    _market_rank_lookup, _market_universe_size, industry_rank_lookup, industry_universe_sizes, _market_score_lookup, _industry_score_lookup, _market_abs_lookup, _market_trend_lookup, _industry_abs_lookup, _industry_trend_lookup = _score_rank_lookups(
        score_rows,
        industry_lookup,
    )
    valuation_lookup: dict[tuple[str, str], dict[str, object]] = _realtime_valuation_lookup()

    rows: list[dict[str, object]] = []

    for quote in load_realtime_quote_rows():
        market = _normalize_text(quote.get("market")).lower()
        symbol = _normalize_text(quote.get("symbol"))
        price = _coerce_float(quote.get("price"))
        last_close = _coerce_float(quote.get("last_close"))
        if not market or not symbol or price is None or last_close in (None, 0.0):
            continue

        # ── ST 过滤 ──────────────────────────────────────────────────
        security = security_lookup.get((market, symbol)) or {}
        stock_name = _normalize_text(security.get("stock_name")) or symbol
        if "ST" in stock_name or "*ST" in stock_name or stock_name.startswith("S ") or stock_name == "S":
            continue

        # ── Listed days ─────────────────────────────────────────────
        listed_date = security.get("listed_date")
        if listed_date:
            try:
                import datetime
                ld = datetime.datetime.strptime(str(listed_date)[:10], "%Y-%m-%d")
                today = datetime.date.today()
                listed_days = (today - ld.date()).days
                if listed_days < int(conditions.get("min_listed_days") or 120):
                    continue
            except Exception:
                pass

        # ── Daily bars (need 120+ for MA calculations) ───────────────
        bars = _recent_daily_bars(market, symbol, count=130)
        if len(bars) < 60:
            continue

        closes = [float(bar["close"]) for bar in bars]
        highs = [float(bar["high"]) for bar in bars]
        lows = [float(bar["low"]) for bar in bars]
        volumes = [float(bar["volume"]) for bar in bars]
        # amount in 元
        amounts = [
            float(bar.get("amount") or (closes[i] * volumes[i] * 100.0))
            for i, bar in enumerate(bars)
        ]

        current_bar = bars[-1]
        current_high = _coerce_float(current_bar.get("high"))
        current_low = _coerce_float(current_bar.get("low"))
        current_vol = _coerce_float(current_bar.get("volume"))
        current_amount = float(current_bar.get("amount") or (price * current_vol * 100.0))

        # MAs
        ma25_today = _ma(closes, 25)
        ma25_5d_ago = _sma(closes, 25, len(closes) - 1 - 5)
        ma25_10d_ago = _sma(closes, 25, len(closes) - 1 - 10)
        ma60_today = _ma(closes, 60)

        if ma25_today is None or ma25_5d_ago is None:
            continue

        # VMA5 / VMA60
        vma5_today = _vol_ma(bars, 5)
        vma60_today = _vol_ma(bars, 60)
        vma5_5d_ago = _vol_ma(bars[:len(bars) - 1], 5)  # 前5日VMA5
        vma5_max_5d = max(volumes[-5:]) if len(volumes) >= 5 else max(volumes)

        # Amount MA
        amount_ma20_today = _recent_amount_ma(bars, 20)

        gain_pct = round((price / float(last_close) - 1.0) * 100.0, 4)
        # 20日涨幅
        close_20d_ago = closes[-20] if len(closes) >= 20 else closes[0]
        gain_20d_pct = ((price / close_20d_ago) - 1.0) * 100.0 if close_20d_ago else None
        # 30日涨幅
        close_30d_ago = closes[-30] if len(closes) >= 30 else closes[0]
        gain_30d_pct = ((price / close_30d_ago) - 1.0) * 100.0 if close_30d_ago else None

        price_above_ma25_pct = ((price / ma25_today) - 1.0) * 100.0 if ma25_today else None
        ma25_trend_5d_pct = ((ma25_today / ma25_5d_ago) - 1.0) * 100.0 if ma25_5d_ago else None

        vol_ratio_5d_60d = (vma5_today / vma60_today) if (vma5_today and vma60_today and vma60_today > 0) else None

        module_passed: dict[str, bool] = {}

        # ══════════════════════════════════════════════════════════════
        # 模块1: 基础条件 (AND)
        # ══════════════════════════════════════════════════════════════
        if module_enabled["basic"]:
            ok = True

            if _coerce_bool(conditions.get("min_price")) and price < float(conditions.get("min_price", 5.0)):
                ok = False
            if ok and _coerce_bool(conditions.get("price_above_ma60")) and ma60_today is not None and price < ma60_today:
                ok = False
            if ok and gain_20d_pct is not None and gain_20d_pct > float(conditions.get("gain_20d_max_pct", 35.0)):
                ok = False
            if ok and _coerce_bool(conditions.get("ma25_trend_up_5d")):
                threshold = float(conditions.get("ma25_trend_up_5d_pct", 0.5))
                if ma25_trend_5d_pct is None or ma25_trend_5d_pct < threshold:
                    ok = False
            if ok and _coerce_bool(conditions.get("ma25_above_ma10")):
                if ma25_10d_ago is None or ma25_today <= ma25_10d_ago:
                    ok = False
            if ok and _coerce_bool(conditions.get("price_above_ma25")) and price < ma25_today:
                ok = False
            if ok and price_above_ma25_pct is not None:
                range_max = float(conditions.get("price_ma25_range_pct", 8.0))
                if price_above_ma25_pct < 0.0 or price_above_ma25_pct > range_max:
                    ok = False
            if ok and vol_ratio_5d_60d is not None:
                vr_min = float(conditions.get("vol_ratio_5d_60d_min", 1.15))
                vr_max = float(conditions.get("vol_ratio_5d_60d_max", 2.5))
                if vol_ratio_5d_60d < vr_min or vol_ratio_5d_60d > vr_max:
                    ok = False
            if ok and amount_ma20_today is not None:
                min_amount = float(conditions.get("min_amount_20d_yi", 1.0)) * 100000000.0
                if amount_ma20_today < min_amount:
                    ok = False

            module_passed["基础条件"] = ok

        # ══════════════════════════════════════════════════════════════
        # 模块2: 回踩买点* (AND)
        # ══════════════════════════════════════════════════════════════
        if module_enabled["pullback_buy"]:
            ok = True

            # 趋势: MA25 / 5日前MA25 - 1 ≥ threshold%
            if _coerce_bool(conditions.get("pb_trend_ma25_5d")):
                threshold = float(conditions.get("pb_trend_ma25_5d_pct", 0.5))
                if ma25_trend_5d_pct is None or ma25_trend_5d_pct < threshold:
                    ok = False

            # 量能: 1.15 ≤ VMA5/VMA60 ≤ 2.5
            if ok and vol_ratio_5d_60d is not None:
                vr_min = float(conditions.get("pb_vol_ratio_min", 1.15))
                vr_max = float(conditions.get("pb_vol_ratio_max", 2.5))
                if vol_ratio_5d_60d < vr_min or vol_ratio_5d_60d > vr_max:
                    ok = False

            # 回踩位置: 当日最低价 ≤ MA25 × pct
            if ok and current_low is not None:
                max_low_ratio = float(conditions.get("pb_low_max_ma25_pct", 1.03))
                if current_low > ma25_today * max_low_ratio:
                    ok = False

            # 收盘站回: C ≥ MA25
            if ok and _coerce_bool(conditions.get("pb_close_above_ma25")):
                if price < ma25_today:
                    ok = False

            # 跌破幅度限制: 当日最低价 ≥ MA25 × pct
            if ok and current_low is not None:
                min_low_ratio = float(conditions.get("pb_low_min_ma25_pct", 0.97))
                if current_low < ma25_today * min_low_ratio:
                    ok = False

            # 当日K线不能太弱: C ≥ (H+L)/2
            if ok and _coerce_bool(conditions.get("pb_kline_mid_strong")):
                if current_high is not None and current_low is not None:
                    mid = (current_high + current_low) / 2.0
                    if price < mid:
                        ok = False

            # 距离25日线: C/MA25 - 1 ≤ pct
            if ok and price_above_ma25_pct is not None:
                max_pct = float(conditions.get("pb_price_ma25_max_pct", 5.0))
                if price_above_ma25_pct > max_pct:
                    ok = False

            module_passed["回踩买点*"] = ok

        # ══════════════════════════════════════════════════════════════
        # 模块3: 突破买点 (AND)
        # ══════════════════════════════════════════════════════════════
        if module_enabled["breakout_buy"]:
            ok = True

            # 最近10天最高价和最低价的振幅不超过 X%
            if ok:
                highs_10d = highs[-10:]
                lows_10d = lows[-10:]
                if highs_10d and lows_10d:
                    h10 = max(highs_10d)
                    l10 = min(lows_10d)
                    if l10 > 0:
                        range_pct = ((h10 / l10) - 1.0) * 100.0
                        max_range = float(conditions.get("bo_range_10d_max_pct", 12.0))
                        if range_pct > max_range:
                            ok = False

            # 最近5日成交量均值比前5日低至少 X%
            if ok:
                vma5_now = vma5_today
                vma5_prev = vma5_5d_ago
                if vma5_now is not None and vma5_prev is not None and vma5_prev > 0:
                    vol_drop_pct = ((vma5_prev - vma5_now) / vma5_prev) * 100.0
                    min_drop = float(conditions.get("bo_vol_drop_min_pct", 15.0))
                    if vol_drop_pct < min_drop:
                        ok = False

            # 收盘突破: C ≥ 近10日最高 × ratio
            if ok:
                h10 = max(highs[-10:]) if len(highs) >= 10 else max(highs)
                break_ratio = float(conditions.get("bo_close_break_ratio", 1.01))
                if price < h10 * break_ratio:
                    ok = False

            # 放量: 当日成交量 ≥ VMA5 × ratio
            if ok and current_vol is not None and vma5_today:
                burst_min = float(conditions.get("bo_vol_burst_min", 1.3))
                if current_vol < vma5_today * burst_min:
                    ok = False

            # 不能爆量: 当日成交量 ≤ VMA60 × ratio
            if ok and current_vol is not None and vma60_today:
                burst_max = float(conditions.get("bo_vol_burst_max", 3.0))
                if current_vol > vma60_today * burst_max:
                    ok = False

            # 距离25日线: C/MA25 - 1 ≤ pct
            if ok and price_above_ma25_pct is not None:
                max_pct = float(conditions.get("bo_price_ma25_max_pct", 10.0))
                if price_above_ma25_pct > max_pct:
                    ok = False

            # 25日线向上: MA25 / 5日前MA25 - 1 ≥ threshold%
            if ok and _coerce_bool(conditions.get("bo_ma25_trend_up", True)):
                threshold = float(conditions.get("bo_ma25_trend_up_pct", 0.5))
                if ma25_trend_5d_pct is None or ma25_trend_5d_pct < threshold:
                    ok = False

            module_passed["突破买点"] = ok

        # ══════════════════════════════════════════════════════════════
        # 模块4: 强势回踩 (AND)
        # ══════════════════════════════════════════════════════════════
        if module_enabled["strong_pullback"]:
            ok = True

            # 近30日涨幅在 X% - Y% 之间
            if ok and gain_30d_pct is not None:
                g_min = float(conditions.get("sp_gain_30d_min_pct", 20.0))
                g_max = float(conditions.get("sp_gain_30d_max_pct", 60.0))
                if gain_30d_pct < g_min or gain_30d_pct > g_max:
                    ok = False

            # 过去20个交易日中，收盘价连续在MA25上方
            if ok:
                above_ma25_days = int(conditions.get("sp_above_ma25_days", 20))
                above_count = 0
                for i in range(-1, -21, -1):
                    if abs(i) > len(closes) - 1:
                        break
                    c = closes[i]
                    ma = _sma(closes, 25, len(closes) - 1 + i)
                    if ma is not None and c >= ma:
                        above_count += 1
                if above_count < above_ma25_days:
                    ok = False

            # 最近3日内第一次回到25日线附近3%以内
            if ok:
                revert_max = float(conditions.get("sp_recent_revert_max_pct", 1.03))
                found_revert = False
                for i in range(-1, -4, -1):
                    if abs(i) > len(closes) - 1:
                        break
                    c = closes[i]
                    ma = _sma(closes, 25, len(closes) - 1 + i)
                    if ma is not None and c <= ma * revert_max:
                        found_revert = True
                        break
                if not found_revert:
                    ok = False

            # 回踩不破: C ≥ MA25
            if ok and _coerce_bool(conditions.get("sp_close_above_ma25")):
                if price < ma25_today:
                    ok = False

            # 回踩幅度: 最低价 ≥ MA25 × pct
            if ok and current_low is not None:
                min_low_ratio = float(conditions.get("sp_low_min_ma25_pct", 0.97))
                if current_low < ma25_today * min_low_ratio:
                    ok = False

            # 缩量: 当日成交量 ≤ 近5日最大成交量 × ratio
            if ok and current_vol is not None and vma5_max_5d:
                shrink_max = float(conditions.get("sp_vol_shrink_max_ratio", 0.7))
                if current_vol > vma5_max_5d * shrink_max:
                    ok = False

            # 不放量下跌: 当日成交量 ≤ VMA5
            if ok and _coerce_bool(conditions.get("sp_vol_below_vma5")):
                if current_vol is not None and vma5_today and current_vol > vma5_today:
                    ok = False

            # K线位置: C ≥ (H+L)/2
            if ok and _coerce_bool(conditions.get("sp_kline_mid_strong")):
                if current_high is not None and current_low is not None:
                    mid = (current_high + current_low) / 2.0
                    if price < mid:
                        ok = False

            # 量能基础: VMA5/VMA60 ≥ ratio
            if ok and vol_ratio_5d_60d is not None:
                min_ratio = float(conditions.get("sp_vol_ratio_min", 1.15))
                if vol_ratio_5d_60d < min_ratio:
                    ok = False

            module_passed["强势回踩"] = ok

        # ══════════════════════════════════════════════════════════════
        # 所有开启的模块必须全部通过
        # ══════════════════════════════════════════════════════════════
        enabled_modules = list(module_passed.keys())
        if not enabled_modules:
            continue
        if not all(module_passed.values()):
            continue

        # ── Build result row ────────────────────────────────────────────
        score_key = f"{market}:{symbol}"
        score_entry = score_rows.get(score_key) if isinstance(score_rows.get(score_key), dict) else {}
        industry = industry_lookup.get((market, symbol)) or {}
        industry_level_1 = (
            _normalize_text(score_entry.get("industry_sw_level_1"))
            or _normalize_text(industry.get("industry_level_1_name"))
        )
        industry_level_2 = (
            _normalize_text(score_entry.get("industry_sw_level_2"))
            or _normalize_text(industry.get("industry_level_2_name"))
        )
        valuation = valuation_lookup.get((market, symbol)) or {}
        market_cap_yi = _coerce_float(valuation.get("total_market_cap"))
        turnover_pct = None
        if current_vol is not None and market_cap_yi and market_cap_yi > 0 and price > 0:
            turnover_pct = (current_vol * 100.0 * price / (market_cap_yi * 100000000.0)) * 100.0

        rows.append({
            "market": market,
            "symbol": symbol,
            "stock_name": stock_name,
            "current_price": round(price, 2),
            "gain_pct": round(gain_pct, 2),
            "gain_20d_pct": round(gain_20d_pct, 2) if gain_20d_pct is not None else None,
            "gain_30d_pct": round(gain_30d_pct, 2) if gain_30d_pct is not None else None,
            "volume_ratio": round(float(vol_ratio_5d_60d), 2) if vol_ratio_5d_60d is not None else None,
            "market_cap_yi": round(float(market_cap_yi), 1) if market_cap_yi is not None else None,
            "turnover_pct": round(float(turnover_pct), 2) if turnover_pct is not None else None,
            "industry_level_1": industry_level_1,
            "industry_level_2": industry_level_2,
            "industry_total_score": round(_industry_score_lookup.get(score_key, _coerce_float(score_entry.get("ind_total_score"))), 1) if _industry_score_lookup.get(score_key) is not None or score_entry.get("ind_total_score") is not None else None,
            "industry_total_rank": _coerce_int(score_entry.get("industry_total_rank")) or industry_rank_lookup.get(score_key),
            "industry_total_universe_size": (
                _coerce_int(score_entry.get("industry_total_universe_size"))
                or industry_universe_sizes.get(industry_level_2)
            ),
            "matched_conditions": enabled_modules,
        })

    rows.sort(key=lambda r: (-float(r.get("gain_pct") or 0.0), str(r.get("market", "")), str(r.get("symbol", ""))))
    return rows


def _build_ma_cross_matches(
    conditions: dict[str, object],
    condition_enabled: dict[str, bool],
) -> list[dict[str, object]]:
    """均线选股：MA5上穿MA20 + MA30>MA5>MA20>MA10 + 阳线 + MA5/MA10上升 + 均线粘合<10%"""
    del conditions, condition_enabled  # fixed conditions, not user-configurable
    from mootdx.reader import Reader

    reader = Reader.factory(market="std", tdxdir="/mnt/c/new_tdx64")
    quotes = load_realtime_quote_rows()
    security_lookup = {_security_key(row): row for row in load_security_rows()}
    industry_lookup = {_security_key(row): row for row in load_industry_rows()}
    snapshot = _load_financial_snapshot() or {}
    score_rows = snapshot.get("scores") or {}
    market_rank_lookup, market_universe_size, industry_rank_lookup, industry_universe_sizes, market_score_lookup, industry_score_lookup, market_abs_lookup, market_trend_lookup, industry_abs_lookup, industry_trend_lookup = _score_rank_lookups(
        score_rows if isinstance(score_rows, dict) else {},
        industry_lookup,
    )

    rows: list[dict[str, object]] = []
    for q in quotes:
        symbol = str(q.get("symbol", "")).strip()
        market = str(q.get("market", "")).strip().lower()
        if not symbol or not market:
            continue
        price = _coerce_float(q.get("price"))
        open_p = _coerce_float(q.get("open"))
        if price is None or open_p is None or price <= 0 or open_p <= 0:
            continue

        try:
            daily = reader.daily(symbol=symbol)
        except Exception:
            continue
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        closes = daily["close"].astype(float).tolist()
        if len(closes) < 35:
            continue

        # Compute MAs
        def _ma(values, period, idx):
            if idx < period - 1:
                return None
            return sum(values[idx - period + 1 : idx + 1]) / period

        ti = len(closes) - 1   # today's index
        yi = ti - 1             # yesterday's index

        ma5_t = _ma(closes, 5, ti)
        ma10_t = _ma(closes, 10, ti)
        ma20_t = _ma(closes, 20, ti)
        ma30_t = _ma(closes, 30, ti)
        ma5_y = _ma(closes, 5, yi)
        ma10_y = _ma(closes, 10, yi)
        ma20_y = _ma(closes, 20, yi)

        if None in (ma5_t, ma10_t, ma20_t, ma30_t, ma5_y, ma10_y, ma20_y):
            continue

        # COND1: CROSS(MA5, MA20) — today MA5 > MA20, yesterday MA5 <= MA20
        cross = ma5_t > ma20_t and ma5_y <= ma20_y

        # COND2: MA30 > MA5 > MA20 > MA10
        order_ok = ma30_t > ma5_t > ma20_t > ma10_t

        # COND3: CLOSE > OPEN (阳线) — use realtime price vs open
        bullish = price > open_p

        # COND4: MA5 > REF(MA5,1) and MA10 > REF(MA10,1)
        rising = ma5_t > ma5_y and ma10_t > ma10_y

        # COND5: (MAXMA - MINMA) / MINMA * 100 < 10
        mas = [ma5_t, ma10_t, ma20_t, ma30_t]
        max_ma = max(mas)
        min_ma = min(mas)
        spread = (max_ma - min_ma) / min_ma * 100.0
        sticky = spread < 10.0

        if not (cross and order_ok and bullish and rising and sticky):
            continue

        # Build result row
        key = (market, symbol)
        security = security_lookup.get(key) or {}
        industry = industry_lookup.get(key) or {}
        score_key = f"{market}:{symbol}"
        score_entry = score_rows.get(score_key) or {}
        industry_level_2 = (
            _normalize_text(score_entry.get("industry_sw_level_2"))
            or _normalize_text(industry.get("industry_level_2_name"))
        )
        stock_name = _normalize_text(security.get("stock_name")) or symbol

        gain_pct = ((price - open_p) / open_p * 100.0) if open_p > 0 else 0.0

        rows.append({
            "market": market,
            "symbol": symbol,
            "stock_name": stock_name,
            "current_price": round(price, 2),
            "gain_pct": round(gain_pct, 2),
            "volume_ratio": None,
            "market_cap_yi": None,
            "turnover_pct": None,
            "industry_level_1": (
                _normalize_text(score_entry.get("industry_sw_level_1"))
                or _normalize_text(industry.get("industry_level_1_name"))
            ),
            "industry_level_2": industry_level_2,
            "industry_total_score": round(_coerce_float(score_entry.get("ind_total_score")), 1) if score_entry.get("ind_total_score") is not None else None,
            "industry_total_rank": _coerce_int(score_entry.get("industry_total_rank")) or industry_rank_lookup.get(score_key),
            "industry_total_universe_size": (
                _coerce_int(score_entry.get("industry_total_universe_size"))
                or industry_universe_sizes.get(industry_level_2)
            ),
            "matched_conditions": ["均线金叉"],
        })

    rows.sort(key=lambda r: (-float(r.get("gain_pct") or 0.0), str(r.get("market", "")), str(r.get("symbol", ""))))
    return rows


def realtime_screener_response(params: dict[str, str]) -> dict[str, object]:
    scenario = _normalize_text(params.get("scenario")) or "tail_session"
    scenario_spec = _REALTIME_SCENARIO_DEFAULTS.get(scenario) or _REALTIME_SCENARIO_DEFAULTS["tail_session"]
    if scenario not in _REALTIME_SCENARIO_DEFAULTS:
        scenario = "tail_session"
    defaults = dict(scenario_spec.get("conditions") or {})

    refresh_seconds = _coerce_int(params.get("refresh_seconds"))
    if refresh_seconds is None or refresh_seconds <= 0:
        refresh_seconds = 30

    monitor = _coerce_bool(params.get("monitor"))
    if scenario == "rps_pullback":
        conditions = _parse_realtime_conditions(params, defaults)
        condition_enabled = _parse_realtime_condition_enabled(params)
        rows = _build_rps_pullback_matches(conditions, condition_enabled) if monitor else []
    elif scenario == "scheme_2560":
        conditions = _parse_realtime_conditions(params, defaults)
        condition_enabled = _parse_realtime_condition_enabled(params)
        rows = _build_scheme_2560_matches(conditions, condition_enabled) if monitor else []
    elif scenario == "ma_cross":
        conditions = _parse_realtime_conditions(params, defaults)
        condition_enabled = _parse_realtime_condition_enabled(params)
        rows = _build_ma_cross_matches(conditions, condition_enabled) if monitor else []
    else:
        conditions = _parse_realtime_conditions(params, defaults)
        condition_enabled = _parse_realtime_condition_enabled(params)
        rows = _build_tail_session_matches(conditions, condition_enabled) if monitor else []

    return {
        "ok": True,
        "scenario": scenario,
        "scenario_label": str(scenario_spec.get("label") or scenario),
        "refresh_seconds": refresh_seconds,
        "conditions": conditions,
        "condition_enabled": condition_enabled,
        "rows": rows,
        "data_note": "实时行情已接入通达信接口。" if monitor else "实时行情监控未启动，当前返回空结果占位。",
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

    # profitability — ROE使用TTM扣非净利润（近12个月），更准确反映真实盈利水平
    ttm_ex_profit_wan = _pick(frow.get("近一年扣非净利润（万元）"))
    if equity and ttm_ex_profit_wan is not None and ttm_ex_profit_wan != 0 and equity != 0:
        # 万元 → 元
        ttm_ex_profit_yuan = ttm_ex_profit_wan * 10000.0
        out["roe_ex"] = ttm_ex_profit_yuan / equity * 100.0
    elif equity and ex_net_prof is not None and equity != 0:
        # 回退：使用累计扣非净利润
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

    # cashflow — 使用TTM口径（近12个月），使Q1/Q2/Q3/Q4可互相比较
    ttm_ocf   = _pick(frow.get("近一年经营活动现金流净额"))  # 元
    ttm_np_wan = _pick(frow.get("近一年归母净利润（万元）"))    # 万元
    if ttm_ocf is not None and ttm_np_wan is not None and ttm_np_wan != 0:
        out["ocf_to_profit"] = ttm_ocf / (ttm_np_wan * 10000.0)
    elif op_cf is not None and net_profit and net_profit != 0:
        out["ocf_to_profit"] = op_cf / net_profit
    else:
        out["ocf_to_profit"] = None
    out["ocf_to_rev"] = vv("经营活动产生的现金流量净额/营业收入")
    # free_cf: 用TTM经营现金流，capex暂无TTM字段，暂用累计值近似
    if ttm_ocf is not None and capex is not None:
        out["free_cf"] = ttm_ocf - capex
    elif op_cf is not None and capex is not None:
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

# ── Trend scoring (YoY change percentile) ──────────────────────────────────

_trend_scores_cache: dict | None = None

def _compute_trend_scores_from_snapshot(snap: dict) -> dict:
    """Compute YoY-change percentile scores for all sub-indicators from the snapshot.

    Returns: {sub_indicators: {key_str: {sub_key: pct}}, ind_sub_indicators: {key_str: {sub_key: pct}}}
    where pct is 0-100, higher = better improvement.
    """
    global _trend_scores_cache
    if _trend_scores_cache is not None:
        return _trend_scores_cache
    # Collect all raw YoY changes per sub-indicator
    market_yoy: dict[str, dict[str, float]] = {}  # {key_str: {sub_key: yoy_pct}}
    industry_map = _load_industry_map()
    # Group stocks by industry for industry-level percentile
    industry_stocks: dict[str, list[str]] = {}  # {ind2: [key_str]}

    for key_str, entry in (snap.get("scores", {}) or {}).items():
        raw = entry.get("raw_sub_indicators", {})
        prev = entry.get("prev_raw_sub_indicators", {})
        if not raw or not prev:
            continue

        market_yoy[key_str] = {}
        for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
            cur = raw.get(sub_key)
            prv = prev.get(sub_key)
            if cur is not None and prv is not None and prv != 0:
                yoy = (cur - prv) / abs(prv) * 100.0
            else:
                yoy = None
            market_yoy[key_str][sub_key] = yoy

        # Industry grouping
        parts = key_str.split(":", 1)
        if len(parts) == 2:
            ind2, _ = industry_map.get((parts[0], parts[1]), ("", ""))
            if ind2:
                industry_stocks.setdefault(ind2, []).append(key_str)

    # Percentile-rank YoY changes within full market
    market_sub_pct: dict[str, dict[str, float]] = {}
    for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
        values = []
        for key_str in market_yoy:
            v = market_yoy[key_str].get(sub_key)
            if v is not None:
                values.append((key_str, v))
        # Sort: for higher_better=True, higher YoY → higher percentile
        # For higher_better=False (e.g., debt_ratio), more negative YoY (improvement) → higher percentile
        if higher_better:
            values.sort(key=lambda x: x[1])
        else:
            values.sort(key=lambda x: -x[1])
        n = len(values)
        for rank, (key_str, _) in enumerate(values):
            pct = round((rank + 1) / n * 100.0, 4)
            market_sub_pct.setdefault(key_str, {})[sub_key] = pct

    # Percentile-rank YoY changes within each industry
    ind_sub_pct: dict[str, dict[str, float]] = {}
    for ind2, stocks in industry_stocks.items():
        for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
            values = []
            for key_str in stocks:
                v = market_yoy.get(key_str, {}).get(sub_key)
                if v is not None:
                    values.append((key_str, v))
            if not values:
                continue
            if higher_better:
                values.sort(key=lambda x: x[1])
            else:
                values.sort(key=lambda x: -x[1])
            n = len(values)
            for rank, (key_str, _) in enumerate(values):
                pct = round((rank + 1) / n * 100.0, 4)
                ind_sub_pct.setdefault(key_str, {})[sub_key] = pct

    result = {"sub_indicators": market_sub_pct, "ind_sub_indicators": ind_sub_pct}
    _trend_scores_cache = result
    return result

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
        # ── Pre-compute trend scores from full snapshot ──
        trend_payload = _compute_trend_scores_from_snapshot(snap)
        all_trend_sub = trend_payload["sub_indicators"]  # {key_str: {sub_key: percentile}}
        all_trend_ind_sub = trend_payload.get("ind_sub_indicators", {})  # {key_str: {sub_key: percentile}}

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
                absolute_total = round(sum(weighted.values()), 2)

                # ── Trend scores ──
                trend_sub = blend_market_scores_with_industry(
                    all_trend_sub.get(key_str, {}),
                    all_trend_ind_sub.get(key_str, {}),
                )
                trend_dim_raw = {}
                for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
                    trend_dim_raw.setdefault(dim, []).append(trend_sub.get(sub_key, 0.0))
                trend_weighted = {}
                for dim, vals in trend_dim_raw.items():
                    avg = sum(vals) / len(vals) if vals else 0.0
                    trend_weighted[dim] = round(avg * _DIM_WEIGHTS.get(dim, 0.0), 2)
                trend_total = round(sum(trend_weighted.values()), 2)

                # ── Blended total (60% absolute + 40% trend) ──
                blended_total = round(absolute_total * 0.6 + trend_total * 0.4, 2)

                # ── Divergence warning ──
                divergence = abs(absolute_total - trend_total) >= 10.0
                divergence_label = (
                    "⚠️ 绝对评分与趋势评分背离" if divergence else ""
                )

                # ── Industry blended scores ──
                ind_abs_total = entry.get("ind_total_score", 0.0)
                ind_trend_dim = {}
                for sub_key, dim, field, higher_better, zero_penalty in _SUB_DEFS:
                    ind_trend_dim.setdefault(dim, []).append(
                        float(all_trend_ind_sub.get(key_str, {}).get(sub_key, 0.0) or 0.0)
                    )
                ind_trend_weighted = {}
                for dim, vals in ind_trend_dim.items():
                    avg = sum(vals) / len(vals) if vals else 0.0
                    ind_trend_weighted[dim] = round(avg * _DIM_WEIGHTS.get(dim, 0.0), 2)
                ind_trend_total = round(sum(ind_trend_weighted.values()), 2)
                ind_blended = round(float(ind_abs_total) * 0.6 + ind_trend_total * 0.4, 2)

                scores[(market, symbol)] = {
                    "report_date": entry.get("report_date", ""),
                    "announce_date": entry.get("announce_date", ""),
                    **{k: v for k, v in sub_indicators.items()},
                    "dim_scores": weighted,
                    "total_score": blended_total,
                    "absolute_total_score": absolute_total,
                    "trend_total_score": trend_total,
                    "trend_dim_scores": trend_weighted,
                    "divergence_warning": divergence,
                    "divergence_label": divergence_label,
                    "ind_sub_indicators": industry_sub_indicators,
                    "ind_dim_scores": entry.get("ind_dim_scores", {}),
                    "ind_trend_dim_scores": ind_trend_weighted,
                    "ind_trend_total_score": ind_trend_total,
                    "ind_total_score": ind_blended,
                    "ind_absolute_total_score": ind_abs_total,
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
        # ── Absolute score ──
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
        absolute_total = round(sum(weighted.values()), 4)

        # ── Trend score (blend with absolute) ──
        trend_payload = _compute_trend_scores_from_snapshot(snap)
        trend_sub = blend_market_scores_with_industry(
            trend_payload["sub_indicators"].get(key_str, {}),
            trend_payload["ind_sub_indicators"].get(key_str, {}),
        )
        trend_dim_raw: dict[str, list[float]] = {}
        for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
            trend_dim_raw.setdefault(dim, []).append(float(trend_sub.get(sub_key, 0.0) or 0.0))
        trend_weighted = {}
        for dim, vals in trend_dim_raw.items():
            avg = sum(vals) / len(vals) if vals else 0.0
            trend_weighted[dim] = avg * _DIM_WEIGHTS.get(dim, 0.0)
        trend_total = round(sum(trend_weighted.values()), 4)

        total = round(absolute_total * 0.6 + trend_total * 0.4, 4)
        market_rows.append((total, market, symbol))

        # ── Industry blended score for ranking ──
        ind_abs = entry.get("ind_total_score")
        try:
            ind_abs_val = float(ind_abs)
        except (TypeError, ValueError):
            ind_abs_val = None

        # Compute industry trend score
        ind_trend_dim = {}
        for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
            ind_trend_dim.setdefault(dim, []).append(
                float(trend_payload["ind_sub_indicators"].get(key_str, {}).get(sub_key, 0.0) or 0.0)
            )
        ind_t_w = {}
        for dim, vals in ind_trend_dim.items():
            avg = sum(vals) / len(vals) if vals else 0.0
            ind_t_w[dim] = avg * _DIM_WEIGHTS.get(dim, 0.0)
        ind_trend_val = round(sum(ind_t_w.values()), 4)

        ind2, _ind1 = industry_map.get((market, symbol), ("", ""))
        if ind2 and ind_abs_val is not None:
            ind_blended = round(ind_abs_val * 0.6 + ind_trend_val * 0.4, 4)
            industry_rows.setdefault(ind2, []).append((ind_blended, market, symbol))

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
    from app.relative_valuation import data_loader as valuation_data_loader

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
            "industry_weighted_pe_ttm": None,
            "industry_weighted_ps_ttm": None,
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
    industry_valuation_snapshot = valuation_data_loader.load_industry_valuation_snapshot(ind2) if ind2 else None
    member_valuation_lookup: dict[tuple[str, str], dict[str, object]] = {}
    for valuation_row in (industry_valuation_snapshot or {}).get("member_valuation_rows", []):
        if not isinstance(valuation_row, dict):
            continue
        row_market = str(valuation_row.get("market") or "").strip().lower()
        row_symbol = str(valuation_row.get("symbol") or "").strip()
        if row_market and row_symbol:
            member_valuation_lookup[(row_market, row_symbol)] = valuation_row
    rows: list[dict[str, object]] = []

    # Pre-compute trend scores for blended industry total
    trend_payload = _compute_trend_scores_from_snapshot(snap)
    ind_trend_sub = trend_payload.get("ind_sub_indicators", {})

    for peer_market, peer_symbol, entry in peer_entries:
        key_str = f"{peer_market}:{peer_symbol}"
        ind_dim_scores = entry.get("ind_dim_scores", {})
        valuation_inputs = member_valuation_lookup.get((peer_market, peer_symbol)) or {}
        if not valuation_inputs:
            valuation_inputs = valuation_data_loader.load_stock_relative_valuation_inputs(peer_market, peer_symbol) or {}
        dimension_scores: dict[str, float | None] = {}
        for dim, weight in _DIM_WEIGHTS.items():
            raw_score = _safe_float(ind_dim_scores.get(dim)) if isinstance(ind_dim_scores, dict) else None
            if raw_score is None or not weight:
                dimension_scores[dim] = None
                continue
            dimension_scores[dim] = round(raw_score / weight, 4)

        # Blended industry total
        ind_abs = _safe_float(entry.get("ind_total_score")) or 0.0
        ind_t_dim = {}
        for sub_key, dim, _field, _higher_better, _zero_penalty in _SUB_DEFS:
            ind_t_dim.setdefault(dim, []).append(
                float(ind_trend_sub.get(key_str, {}).get(sub_key, 0.0) or 0.0)
            )
        ind_t_w = {}
        for dim, vals in ind_t_dim.items():
            avg = sum(vals) / len(vals) if vals else 0.0
            ind_t_w[dim] = avg * _DIM_WEIGHTS.get(dim, 0.0)
        ind_t = round(sum(ind_t_w.values()), 4)
        blended = round(ind_abs * 0.6 + ind_t * 0.4, 2)

        rows.append(
            {
                "stock_name": name_lookup.get((peer_market, peer_symbol), peer_symbol),
                "market": peer_market,
                "symbol": peer_symbol,
                "current_price": _safe_float(valuation_inputs.get("current_price")) or latest_close_prices.get((peer_market, peer_symbol)),
                "total_market_cap": _safe_float(valuation_inputs.get("total_market_cap")),
                "free_float_market_cap": _safe_float(valuation_inputs.get("free_float_market_cap")),
                "ps_ttm": _safe_float(valuation_inputs.get("ps_ttm")),
                "pe_ttm": _safe_float(valuation_inputs.get("pe_ttm")),
                "total_score": blended,
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
        "industry_weighted_pe_ttm": _safe_float((industry_valuation_snapshot or {}).get("weighted_pe_ttm")),
        "industry_weighted_ps_ttm": _safe_float((industry_valuation_snapshot or {}).get("weighted_ps_ttm")),
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
    ind_absolute_total_score = score_data.pop("ind_absolute_total_score", None) if score_data else None
    ind_trend_total_score = score_data.pop("ind_trend_total_score", None) if score_data else None
    # Promoted market-rank fields to top level for the "全市场" radar
    total_score = score_data.pop("total_score", 0.0) if score_data else 0.0
    dim_scores = score_data.pop("dim_scores", {}) if score_data else {}
    sub_indicators = score_data.pop("sub_indicators", {}) if score_data else {}
    absolute_total_score = score_data.pop("absolute_total_score", None) if score_data else None
    trend_total_score = score_data.pop("trend_total_score", None) if score_data else None
    divergence_label = score_data.pop("divergence_label", "") if score_data else ""
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
        "absolute_total_score": absolute_total_score,
        "trend_total_score": trend_total_score,
        "divergence_label": divergence_label,
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
        "ind_absolute_total_score": ind_absolute_total_score,
        "ind_trend_total_score": ind_trend_total_score,
    }
