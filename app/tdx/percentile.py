"""Stock price percentile computed on Tongdaxin front-adjusted (QFQ) closes.

History: this module used to read raw ``vipdoc/*.day`` bars through mootdx, which
silently disagreed with the QFQ five-year percentile on the equity-analysis
valuation card (688019: raw 63.70% vs QFQ 91.83% over the same 1212-bar window,
because front-adjustment lowers历史价格 while the latest bar is the anchor).
Raw prices are never used here: the published QFQ snapshot is authoritative and
the QFQ export is the recompute fallback.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.tdx.price_position import price_position
from app.tdx.qfq_kline import load_tdx_qfq_daily

PRICE_BASIS = "tdx_export_qfq"
MIN_SAMPLES = 30
_BANDS = ((20, "极低"), (40, "低"), (60, "中"), (80, "高"), (float("inf"), "极高"))


def _band(percentile: float) -> str:
    return next(label for upper, label in _BANDS if percentile < upper)


def _closes(frame: pd.DataFrame) -> pd.Series:
    """Positive, finite QFQ closes indexed by trading day."""
    if "close" not in frame.columns:
        raise ValueError("QFQ export frame has no close column")
    closes = pd.to_numeric(frame["close"], errors="coerce").set_axis(pd.to_datetime(frame.index))
    return closes[np.isfinite(closes) & (closes > 0)].sort_index()


def _published_percentile(market: str, symbol: str, scope: str, as_of: str) -> tuple[float | None, str | None]:
    """Reuse the published QFQ snapshot when it covers the same day and scope."""
    try:
        published = price_position(market, symbol)
    except (OSError, ValueError, KeyError):
        return None, None
    if not published.get("ok"):
        return None, published.get("as_of_date")
    raw = published.get("price_percentile")
    value = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    aligned = (value is not None and published.get("price_basis") == PRICE_BASIS
               and published.get("scope") == scope
               and published.get("as_of_date") == as_of
               and math.isfinite(value) and 0 <= value <= 100)
    return (value if aligned else None), published.get("as_of_date")


def compute_stock_price_percentile(market: str, symbol: str, *, years: int = 5) -> dict[str, Any]:
    """Percentile of the latest QFQ close inside its own N-year QFQ history.

    Empirical definition, identical to the published market snapshot: share of
    window closes <= latest close.  Never falls back to unadjusted prices.
    """
    market, symbol = str(market or "").lower().strip(), str(symbol or "").strip()
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")
    if market not in {"sh", "sz", "bj"}:
        raise ValueError(f"unsupported market: {market}")

    closes = _closes(load_tdx_qfq_daily(symbol))
    if closes.empty:
        raise ValueError(f"QFQ export has no valid closes for {symbol}")

    as_of_date = str(closes.index[-1].date())
    cutoff = closes.index[-1] - pd.DateOffset(years=years)
    five_year = years == 5 and bool(closes.index[0] <= cutoff)
    scope = "five_year" if five_year else "since_listing"
    window = closes.loc[closes.index >= cutoff] if five_year else closes
    if len(window) < MIN_SAMPLES:
        raise ValueError(f"only {len(window)} QFQ trading days in the {years}-year window for {symbol}")

    latest = float(window.iloc[-1])
    percentile = float((window <= latest).sum()) / len(window) * 100
    published, snapshot_as_of = _published_percentile(market, symbol, scope, as_of_date)
    if published is not None:
        percentile = published

    return {
        "ok": True,
        "market": market,
        "symbol": symbol,
        "years": years,
        "price_basis": PRICE_BASIS,
        "scope": scope,
        "bar_count": int(len(window)),
        "sample_count": int(len(window)),
        "window_start": str(window.index[0].date()),
        "window_end": as_of_date,
        "as_of_date": as_of_date,
        "first_valid_date": str(closes.index[0].date()),
        "latest_close": round(latest, 2),
        "price_percentile": round(percentile, 2),
        "price_band": _band(percentile),
        "price_min": round(float(window.min()), 2),
        "price_max": round(float(window.max()), 2),
        "price_mean": round(float(window.mean()), 2),
        "price_std": round(float(window.std(ddof=1)), 2) if len(window) > 1 else 0.0,
        "percentile_source": "published_qfq_snapshot" if published is not None else "qfq_export_recomputed",
        "snapshot_as_of_date": snapshot_as_of,
    }
