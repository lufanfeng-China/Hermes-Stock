"""Helpers and data loading for the second-level industry heatmap."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
DEFAULT_INDUSTRY_DATASET = DEFAULT_DATASET_DIR / "dataset_stock_industry_current.json"
DEFAULT_HEATMAP_CACHE_DIR = PROJECT_ROOT / "data" / "derived" / "cache"
TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"
DEFAULT_INDUSTRY_LIMIT: int | None = None
DEFAULT_LOOKBACK_SESSIONS = 40


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"dataset must be a JSON array: {path}")
    return [row for row in rows if isinstance(row, dict)]


def _build_dataset_signature(dataset_path: str | Path = DEFAULT_INDUSTRY_DATASET) -> str:
    path = Path(dataset_path)
    stat = path.stat()
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def build_heatmap_cache_path(
    *,
    limit: int | None,
    lookback_sessions: int,
    cache_dir: str | Path = DEFAULT_HEATMAP_CACHE_DIR,
    cache_day: str | None = None,
    dataset_signature: str | None = None,
) -> Path:
    resolved_cache_day = str(cache_day or datetime.now().astimezone().date().isoformat())
    resolved_signature = str(dataset_signature or _build_dataset_signature()).strip()
    limit_token = "all" if limit is None else str(max(1, int(limit)))
    return Path(cache_dir) / (
        f"industry_heatmap_{resolved_cache_day}_limit-{limit_token}_"
        f"lookback-{int(lookback_sessions)}_{resolved_signature}.json"
    )


def write_cached_heatmap_payload(cache_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cached_heatmap_payload(cache_path: str | Path) -> dict[str, Any] | None:
    path = Path(cache_path)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"cached heatmap payload must be a JSON object: {path}")
    return payload


def _display_cache_path(cache_path: str | Path) -> str:
    path = Path(cache_path)
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


@lru_cache(maxsize=2)
def load_industry_rows(dataset_path: str | Path = DEFAULT_INDUSTRY_DATASET) -> list[dict[str, Any]]:
    return _load_json_rows(Path(dataset_path))


def select_default_industries(
    industry_rows: list[dict[str, Any]],
    *,
    limit: int | None = DEFAULT_INDUSTRY_LIMIT,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in industry_rows:
        code = str(row.get("industry_level_2_code", "")).strip()
        name = str(row.get("industry_level_2_name", "")).strip()
        market = str(row.get("market", "")).strip()
        symbol = str(row.get("symbol", "")).strip()
        if not code or not name or not market or not symbol:
            continue
        item = grouped.setdefault(
            code,
            {
                "industry_level_2_code": code,
                "industry_level_2_name": name,
                "members": set(),
            },
        )
        if not item["industry_level_2_name"]:
            item["industry_level_2_name"] = name
        item["members"].add((market, symbol))

    selected: list[dict[str, Any]] = []
    for item in grouped.values():
        members = item.pop("members")
        selected.append(
            {
                "industry_level_2_code": item["industry_level_2_code"],
                "industry_level_2_name": item["industry_level_2_name"],
                "member_count": len(members),
            }
        )
    selected.sort(
        key=lambda item: (
            -int(item["member_count"]),
            str(item["industry_level_2_code"]),
            str(item["industry_level_2_name"]),
        )
    )
    if limit is None:
        return selected
    return selected[: max(1, limit)]


def _build_industry_member_keys(
    selected_industries: list[dict[str, Any]],
    industry_rows: list[dict[str, Any]],
) -> dict[str, list[str]]:
    selected_codes = {str(item.get("industry_level_2_code", "")).strip() for item in selected_industries}
    members: dict[str, set[str]] = defaultdict(set)
    for row in industry_rows:
        code = str(row.get("industry_level_2_code", "")).strip()
        market = str(row.get("market", "")).strip()
        symbol = str(row.get("symbol", "")).strip()
        if code not in selected_codes or not market or not symbol:
            continue
        members[code].add(f"{market}:{symbol}")
    return {code: sorted(keys) for code, keys in members.items()}


def select_year_to_date_trading_days(
    trading_days: list[str],
    *,
    anchor_day: str | None = None,
) -> list[str]:
    if not trading_days:
        return []

    latest_day = str(anchor_day or max(trading_days)).strip()
    latest_date = datetime.strptime(latest_day, "%Y-%m-%d").date()
    year_start = latest_date.replace(month=1, day=1)

    selected = []
    for trading_day in trading_days:
        current_day = str(trading_day).strip()
        if not current_day:
            continue
        current_date = datetime.strptime(current_day, "%Y-%m-%d").date()
        if year_start <= current_date <= latest_date:
            selected.append(current_day)
    return sorted(set(selected), reverse=True)


def build_heatmap_rows(
    *,
    selected_industries: list[dict[str, Any]],
    industry_rows: list[dict[str, Any]],
    stock_returns: dict[str, dict[str, float]],
    trading_days: list[str],
) -> list[dict[str, Any]]:
    member_keys = _build_industry_member_keys(selected_industries, industry_rows)
    rows: list[dict[str, Any]] = []
    for industry in selected_industries:
        code = str(industry.get("industry_level_2_code", "")).strip()
        name = str(industry.get("industry_level_2_name", "")).strip()
        symbols = member_keys.get(code, [])
        cells: list[dict[str, Any]] = []
        for trading_day in trading_days:
            values = []
            for symbol_key in symbols:
                pct_change = stock_returns.get(symbol_key, {}).get(trading_day)
                if pct_change is None:
                    continue
                values.append(float(pct_change))
            avg_pct = round(sum(values) / len(values), 4) if values else None
            cells.append(
                {
                    "trading_day": trading_day,
                    "pct_change": avg_pct,
                    "stock_count": len(values),
                }
            )
        rows.append(
            {
                "industry_level_2_code": code,
                "industry_level_2_name": name,
                "member_count": int(industry.get("member_count", len(symbols)) or 0),
                "cells": cells,
            }
        )
    return rows


def _fetch_stock_returns(
    stock_refs: list[dict[str, str]],
    *,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
) -> tuple[list[str], dict[str, dict[str, float]]]:
    if not stock_refs:
        return [], {}

    request_payload = {
        "tdxdir": TONGDAXIN_DIR,
        "lookback_sessions": lookback_sessions,
        "stocks": stock_refs,
    }
    script = r"""
import json
import sys

from mootdx.reader import Reader

payload = json.load(sys.stdin)
reader = Reader.factory(market="std", tdxdir=payload["tdxdir"])
all_days = set()
stock_returns = {}

for stock in payload["stocks"]:
    market = str(stock.get("market", "")).strip()
    symbol = str(stock.get("symbol", "")).strip()
    if not market or not symbol:
        continue
    daily = reader.daily(symbol=symbol)
    if daily is None or daily.empty:
        continue
    closes = daily.sort_index()["close"].astype(float)
    pct = closes.pct_change() * 100.0
    daily_returns = {}
    for index, value in pct.dropna().items():
        trading_day = index.strftime("%Y-%m-%d")
        daily_returns[trading_day] = round(float(value), 4)
        all_days.add(trading_day)
    if daily_returns:
        stock_returns[f"{market}:{symbol}"] = daily_returns

response = {
    "trading_days": sorted(all_days),
    "stock_returns": stock_returns,
}
print(json.dumps(response, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [TONGDAXIN_PYTHON, "-c", script],
        input=json.dumps(request_payload, ensure_ascii=False),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "unknown subprocess error").strip()
        raise RuntimeError(stderr)
    payload = json.loads(result.stdout or "{}")
    trading_days = payload.get("trading_days", [])
    stock_returns = payload.get("stock_returns", {})
    if not isinstance(trading_days, list) or not isinstance(stock_returns, dict):
        raise RuntimeError("invalid Tongdaxin heatmap response")
    _ = lookback_sessions
    return [str(day) for day in trading_days], {
        str(symbol_key): {str(day): float(value) for day, value in values.items()}
        for symbol_key, values in stock_returns.items()
        if isinstance(values, dict)
    }


@lru_cache(maxsize=4)
def industry_heatmap_response(
    limit: int | None = DEFAULT_INDUSTRY_LIMIT,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    refresh_cache: bool = False,
) -> dict[str, Any]:
    cache_path = build_heatmap_cache_path(
        limit=limit,
        lookback_sessions=lookback_sessions,
    )
    if not refresh_cache:
        cached_payload = load_cached_heatmap_payload(cache_path)
        if cached_payload is not None:
            meta = cached_payload.get("meta")
            if isinstance(meta, dict):
                meta["cache"] = {
                    "status": "hit",
                    "path": _display_cache_path(cache_path),
                }
            return cached_payload

    industry_rows = load_industry_rows()
    selected = select_default_industries(industry_rows, limit=limit)
    requested_symbols = []
    seen: set[str] = set()
    for code, symbol_keys in _build_industry_member_keys(selected, industry_rows).items():
        _ = code
        for symbol_key in symbol_keys:
            if symbol_key in seen:
                continue
            seen.add(symbol_key)
            market, symbol = symbol_key.split(":", 1)
            requested_symbols.append({"market": market, "symbol": symbol})

    trading_days, stock_returns = _fetch_stock_returns(
        requested_symbols,
        lookback_sessions=lookback_sessions,
    )
    trading_days = select_year_to_date_trading_days(trading_days)
    rows = build_heatmap_rows(
        selected_industries=selected,
        industry_rows=industry_rows,
        stock_returns=stock_returns,
        trading_days=trading_days,
    )
    if not trading_days:
        raise RuntimeError("no trading-day returns available for selected industries")

    payload = {
        "ok": True,
        "selected_industries": selected,
        "trading_days": trading_days,
        "rows": rows,
        "meta": {
            "methodology": "equal_weight_average_of_constituent_stock_daily_pct_changes",
            "description": "Each cell is the equal-weight average of constituent stock daily percentage changes for that second-level industry, shown newest-to-oldest for the current year to date.",
            "lookback_sessions": len(trading_days),
            "color_scale_pct": {"min": -5.0, "mid": 0.0, "max": 5.0},
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_dataset": str(DEFAULT_INDUSTRY_DATASET.relative_to(PROJECT_ROOT)),
            "source_data": "Tongdaxin local daily bars via mootdx subprocess",
            "cache": {
                "status": "refresh_miss" if refresh_cache else "miss",
                "path": _display_cache_path(cache_path),
            },
        },
    }
    write_cached_heatmap_payload(cache_path, payload)
    return payload
