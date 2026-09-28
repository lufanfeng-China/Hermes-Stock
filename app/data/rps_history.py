"""Cross-sectional RPS history data loading from the authoritative Parquet dataset."""
import functools
from pathlib import Path

import pandas as pd

from app.tdx.kline import infer_market

DERIVED_FINAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "derived" / "datasets" / "final"
STOCK_RPS_HISTORY_DATASET = DERIVED_FINAL_DIR / "dataset_stock_rps_history.parquet"


@functools.lru_cache(maxsize=1)
def _load_rps_history_dataset() -> list[dict[str, object]]:
    """Load the precomputed cross-sectional RPS history dataset (cached in memory)."""
    dataset_path = DERIVED_FINAL_DIR / STOCK_RPS_HISTORY_DATASET.name
    if not dataset_path.exists():
        return []
    frame = pd.read_parquet(dataset_path)
    return frame.to_dict(orient="records")


def load_stock_rps_history(symbol: str) -> dict[str, object]:
    """Return cross-sectional RPS history for one stock from authoritative Parquet."""
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")
    market, _suffix = infer_market(symbol)
    history = [
        {
            "trading_day": str(row.get("trading_day", "")),
            "rps_20": row.get("rps_20"),
            "rps_50": row.get("rps_50"),
            "rps_120": row.get("rps_120"),
            "rps_250": row.get("rps_250"),
        }
        for row in _load_rps_history_dataset()
        if str(row.get("symbol", "")) == symbol and str(row.get("market", "")) == market
    ]
    history.sort(key=lambda item: str(item.get("trading_day", "")))
    return {"ok": True, "symbol": symbol, "market": market, "history": history}
