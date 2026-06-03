"""Watchlist persistence."""
import json
from pathlib import Path

WATCHLIST_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "derived" / "watchlist.json"

def _load_watchlist() -> dict:
    """Load watchlist, return {'stocks': [...]}."""
    if not WATCHLIST_PATH.exists():
        return {"stocks": []}
    try:
        with open(WATCHLIST_PATH) as f:
            data = json.load(f)
        if not isinstance(data.get("stocks"), list):
            return {"stocks": []}
        return data
    except Exception:
        return {"stocks": []}

def _save_watchlist(data: dict) -> None:
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

