"""Cross-sectional RPS history data loading from the authoritative Parquet dataset."""
import functools
from pathlib import Path

import pandas as pd

from app.tdx.kline import infer_market

DERIVED_FINAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "derived" / "datasets" / "final"
STOCK_RPS_HISTORY_DATASET = DERIVED_FINAL_DIR / "dataset_stock_rps_history.parquet"


@functools.lru_cache(maxsize=512)
def _load_stock_rps_history_dataset(symbol: str, market: str) -> list[dict[str, object]]:
    """Load one stock's RPS history without materialising the whole Parquet file."""
    dataset_path = DERIVED_FINAL_DIR / STOCK_RPS_HISTORY_DATASET.name
    if not dataset_path.exists():
        return []
    frame = pd.read_parquet(
        dataset_path,
        columns=["trading_day", "market", "symbol", "rps_20", "rps_50", "rps_120", "rps_250"],
        filters=[("market", "=", market), ("symbol", "=", symbol)],
    )
    return frame.to_dict(orient="records")


@functools.lru_cache(maxsize=1)
def _load_rps_history_dataset() -> list[dict[str, object]]:
    """Compatibility hook for pipeline cache clearing; full-history loads are forbidden."""
    return []


@functools.lru_cache(maxsize=1)
def _load_rps_trading_days() -> list[str]:
    """Load the unique RPS calendar without materialising the full dataset."""
    dataset_path = DERIVED_FINAL_DIR / STOCK_RPS_HISTORY_DATASET.name
    if not dataset_path.exists():
        return []
    frame = pd.read_parquet(dataset_path, columns=["trading_day"])
    return sorted({str(day) for day in frame["trading_day"] if pd.notna(day)})


def load_rps_trading_days() -> list[str]:
    """Return the authoritative RPS trading-day calendar."""
    return _load_rps_trading_days()


def load_stock_rps_history(symbol: str):
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
        for row in _load_stock_rps_history_dataset(symbol, market)
        if str(row.get("symbol", "")) == symbol and str(row.get("market", "")) == market
    ]
    history.sort(key=lambda item: str(item.get("trading_day", "")))
    return {"ok": True, "symbol": symbol, "market": market, "history": history}
