"""Stock competitive edge analysis — cached data for #1/#2 rankings and bottleneck capabilities.

Cache files in data/derived/cache/competitive_edge/, keyed by market_symbol.json.
Stale threshold: 180 days. Data is populated externally (e.g. by Hermes agent).
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "derived" / "cache" / "competitive_edge"
_STALE_DAYS = 180
_CACHE: dict[str, dict] = {}


def get_stock_competitive_edge(market: str, symbol: str, stock_name: str = "") -> dict:
    """Return cached competitive edge info. Returns empty text if no cache."""
    cached = _load_cache(market, symbol)

    if cached:
        refreshed_str = cached.get("refreshed_at", "")
        try:
            refreshed = datetime.fromisoformat(refreshed_str)
            is_stale = (datetime.now(timezone.utc) - refreshed) >= timedelta(days=_STALE_DAYS)
        except (ValueError, TypeError):
            is_stale = True
    else:
        is_stale = False

    if not cached:
        return {
            "market": market, "symbol": symbol, "stock_name": stock_name,
            "text": "", "refreshed_at": "", "stale": False,
        }
    return {**cached, "stale": is_stale}


def save_competitive_edge(market: str, symbol: str, text: str, stock_name: str = "") -> dict:
    """Save competitive edge data to cache (called by Hermes agent)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "market": market, "symbol": symbol, "stock_name": stock_name,
        "text": text, "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    key = f"{market}:{symbol}"
    _CACHE[key] = data
    path = _CACHE_DIR / f"{market}_{symbol}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _load_cache(market: str, symbol: str) -> dict | None:
    key = f"{market}:{symbol}"
    if key in _CACHE:
        return _CACHE[key]
    path = _CACHE_DIR / f"{market}_{symbol}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _CACHE[key] = data
        return data
    except Exception:
        return None
