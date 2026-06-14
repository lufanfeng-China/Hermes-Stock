"""Stock competitive edge analysis — cached web-search for #1/#2 rankings and bottleneck capabilities.

Cache files in data/derived/cache/competitive_edge/, keyed by market_symbol.json.
Stale threshold: 180 days.

When no cache exists, returns placeholder immediately and triggers async background search.
"""
import json
import re
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "derived" / "cache" / "competitive_edge"
_STALE_DAYS = 180
_CACHE: dict[str, dict] = {}
_BG_SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "_search_competitive_edge.py")


def _cache_path(market: str, symbol: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{market}_{symbol}.json"


def get_stock_competitive_edge(market: str, symbol: str, stock_name: str = "", force_refresh: bool = False) -> dict:
    """Return cached competitive edge info. Triggers background search if no cache or stale."""
    cached = _load_cache(market, symbol)
    now = datetime.now(timezone.utc)

    is_fresh = False
    if cached and not force_refresh:
        refreshed_str = cached.get("refreshed_at", "")
        try:
            refreshed = datetime.fromisoformat(refreshed_str)
            if (now - refreshed) < timedelta(days=_STALE_DAYS):
                is_fresh = True
        except (ValueError, TypeError):
            pass

    if force_refresh or not is_fresh:
        # Trigger background search
        _trigger_background_search(market, symbol, stock_name)

    if not cached:
        return {
            "market": market,
            "symbol": symbol,
            "stock_name": stock_name,
            "text": "",
            "refreshed_at": "",
            "pending": True,
        }

    return {**cached, "pending": False}


def _load_cache(market: str, symbol: str) -> dict | None:
    key = f"{market}:{symbol}"
    if key in _CACHE:
        return _CACHE[key]
    path = _cache_path(market, symbol)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _CACHE[key] = data
        return data
    except Exception:
        return None


def _save_cache(market: str, symbol: str, data: dict) -> None:
    key = f"{market}:{symbol}"
    _CACHE[key] = data
    path = _cache_path(market, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _trigger_background_search(market: str, symbol: str, stock_name: str) -> None:
    """Spawn a background subprocess to search and populate cache."""
    try:
        venv_python = sys.executable
        subprocess.Popen(
            [venv_python, _BG_SCRIPT, market, symbol, stock_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
