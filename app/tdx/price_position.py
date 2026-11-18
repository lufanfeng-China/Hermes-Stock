"""Read one stock's audited QFQ price position from the published market snapshot."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parents[2] / "data/derived/datasets/final/stock_filter_market_metrics_current.json"


@lru_cache(maxsize=2)
def _read_snapshot(path: str, mtime_ns: int) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def price_position(market: str, symbol: str, *, path: Path = SNAPSHOT) -> dict[str, Any]:
    """Expose a single published record; never calculate from raw/unadjusted prices."""
    market = str(market or "").lower().strip()
    symbol = str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"} or len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("market/symbol 参数不合法")
    data = _read_snapshot(str(path), path.stat().st_mtime_ns)
    row = (data.get("metrics") or {}).get(f"{market}:{symbol}") or {}
    basis = row.get("price_percentile_5y_basis")
    value = row.get("price_percentile_5y")
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
    valid = (row.get("price_basis") == "tdx_export_qfq" and basis in {"five_year", "since_listing"}
             and value is not None and math.isfinite(value) and 0 <= value <= 100)
    return {
        "ok": True, "market": market, "symbol": symbol,
        "price_percentile": value if valid else None,
        "scope": basis if valid else "unavailable", "price_basis": row.get("price_basis"),
        "as_of_date": row.get("price_percentile_5y_as_of"),
        "window_start": row.get("price_percentile_5y_window_start"),
        "window_end": row.get("price_percentile_5y_window_end"),
        "first_valid_date": row.get("price_percentile_5y_first_valid_date"),
        "sample_count": row.get("price_percentile_5y_sample_count"),
    }
