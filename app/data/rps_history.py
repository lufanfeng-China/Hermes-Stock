"""Cross-sectional RPS history data loading."""
import functools
import json
from pathlib import Path

from app.tdx.kline import infer_market

DERIVED_FINAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "derived" / "datasets" / "final"
STOCK_RPS_HISTORY_DATASET = DERIVED_FINAL_DIR / "dataset_stock_rps_history.json"


@functools.lru_cache(maxsize=1)
def _load_rps_history_dataset() -> list[dict[str, object]]:
    """Load the precomputed cross-sectional RPS history dataset (cached in memory)."""
    if not STOCK_RPS_HISTORY_DATASET.exists():
        return []
    return json.loads(STOCK_RPS_HISTORY_DATASET.read_text(encoding="utf-8"))


def load_stock_rps_history(symbol: str) -> dict[str, object]:
    """Return cross-sectional RPS history for one stock from the precomputed dataset."""
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")
    market, _suffix = infer_market(symbol)

    all_rows = _load_rps_history_dataset()
    history = [
        {
            "trading_day": str(row.get("trading_day", "")),
            "rps_20": row.get("rps_20"),
            "rps_50": row.get("rps_50"),
            "rps_120": row.get("rps_120"),
            "rps_250": row.get("rps_250"),
        }
        for row in all_rows
        if row.get("symbol") == symbol and row.get("market") == market
    ]
    history.sort(key=lambda item: str(item.get("trading_day", "")))
    return {"ok": True, "symbol": symbol, "market": market, "history": history}
