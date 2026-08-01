"""Read front-adjusted daily OHLCV exported by the Tongdaxin desktop client."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.config import TDX_QFQ_EXPORT_DIR

_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]
_DATE_RE = re.compile(r"\d{4}/\d{2}/\d{2}")


def _export_market_prefix(code: str) -> str:
    """Map a six-digit A-share code to Tongdaxin export filename prefix."""
    normalized = str(code).zfill(6)
    if normalized.startswith("92"):
        return "BJ"
    if normalized.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def qfq_export_path(code: str, export_dir: Path = TDX_QFQ_EXPORT_DIR) -> Path:
    normalized = str(code).zfill(6)
    return Path(export_dir) / f"{_export_market_prefix(normalized)}#{normalized}.txt"


def load_tdx_qfq_daily(code: str, export_dir: Path = TDX_QFQ_EXPORT_DIR) -> pd.DataFrame:
    """Load one Tongdaxin-exported *front-adjusted* daily OHLCV series.

    Tongdaxin adds two GB18030 metadata/header lines and may append a textual
    source footer.  Only YYYY/MM/DD rows are accepted, so the returned frame
    cannot accidentally include metadata as an OHLCV bar.
    """
    path = qfq_export_path(code, export_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Tongdaxin QFQ export not found for {str(code).zfill(6)}: {path}")

    raw = pd.read_csv(
        path,
        encoding="gb18030",
        sep="\t",
        skiprows=2,
        header=None,
        names=_COLUMNS,
        dtype=str,
    )
    raw = raw[raw["date"].fillna("").str.strip().str.fullmatch(_DATE_RE.pattern)].copy()
    if raw.empty:
        raise ValueError(f"Tongdaxin QFQ export contains no daily bars: {path}")

    raw["date"] = pd.to_datetime(raw["date"].str.strip(), format="%Y/%m/%d", errors="raise")
    for column in _COLUMNS[1:]:
        raw[column] = pd.to_numeric(
            raw[column].fillna("").str.replace(",", "", regex=False).str.strip(), errors="coerce"
        )
    frame = raw.dropna(subset=["open", "high", "low", "close"]).set_index("date").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    if frame.empty:
        raise ValueError(f"Tongdaxin QFQ export contains no valid OHLCV bars: {path}")

    frame = frame[_COLUMNS[1:]].astype(float)
    frame.attrs["price_basis"] = "tdx_export_qfq"
    frame.attrs["source_file"] = str(path)
    return frame


def align_qfq_signal_with_raw_execution(raw: pd.DataFrame, qfq: pd.DataFrame) -> pd.DataFrame:
    """Align QFQ signal closes with raw prices used for executable orders/MTM."""
    raw_required = ["open", "high", "low", "close", "volume", "amount"]
    missing_raw = [column for column in raw_required if column not in raw.columns]
    if missing_raw:
        raise ValueError(f"Raw daily frame is missing columns: {', '.join(missing_raw)}")
    if "close" not in qfq.columns:
        raise ValueError("QFQ daily frame is missing close")

    raw_frame = raw[raw_required].copy().rename(columns={
        "open": "raw_open", "high": "raw_high", "low": "raw_low", "close": "raw_close",
        "volume": "raw_volume", "amount": "raw_amount",
    })
    qfq_frame = qfq[["close"]].copy().rename(columns={"close": "signal_close"})
    bars = raw_frame.join(qfq_frame, how="inner").sort_index()
    if bars.empty:
        raise ValueError("Raw and QFQ daily frames have no overlapping dates")
    bars.attrs["signal_price_basis"] = "tdx_export_qfq"
    bars.attrs["execution_price_basis"] = "tdx_raw"
    return bars
