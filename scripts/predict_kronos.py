#!/usr/bin/env python3
"""Build Kronos prediction dataset for all A-share stocks.

Reads daily K-line data via mootdx, runs Kronos-small model to predict
next 20 trading days, outputs a JSON lookup keyed by "market:symbol".

Usage:
  python scripts/predict_kronos.py                          # predict all
  python scripts/predict_kronos.py --limit 100              # predict 100 stocks
  python scripts/predict_kronos.py --symbols sh:600519,sz:000858  # specific stocks
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, "/home/lufanfeng/Kronos")

from app.search.index import load_rps_rows

DEFAULT_TDX_DIR = "/home/lufanfeng/tdx_data"
DEFAULT_OUTPUT = PROJECT_ROOT / "data/derived/datasets/final/dataset_kronos_prediction.json"
LOOKBACK = 400      # input bars
PRED_LEN = 20       # predict future bars
MIN_BARS = 450      # skip stocks with fewer bars

# ── helpers ──────────────────────────────────────────────────────────


def _coerce_float(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _predict_stock(
    predictor: Any,
    reader: Any,
    market: str,
    symbol: str,
) -> dict[str, object] | None:
    """Predict one stock. Returns dict with prediction fields, or None on failure."""
    try:
        daily = reader.daily(symbol=symbol)
    except Exception:
        return None
    if daily is None or daily.empty or len(daily) < MIN_BARS:
        return None

    daily = daily.sort_index()
    n = len(daily)
    start = max(0, n - LOOKBACK)
    df = daily[["open", "high", "low", "close", "volume"]].iloc[start:].copy()
    df["amount"] = (df["close"] * df["volume"] / 100).round(2)
    x_ts = pd.Series(daily.index[start:], name="timestamps")

    last_date = daily.index[-1]
    y_dates = pd.date_range(start=last_date, periods=PRED_LEN + 1, freq="B")[1:]
    y_ts = pd.Series(y_dates, name="timestamps")

    try:
        pred_df = predictor.predict(
            df=df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=PRED_LEN,
            T=1.0,
            top_p=0.9,
            sample_count=1,
            verbose=False,
        )
    except Exception:
        return None

    last_close = float(df["close"].iloc[-1])
    pred_5 = float(pred_df["close"].iloc[4]) if len(pred_df) > 4 else float(pred_df["close"].iloc[-1])
    pred_20 = float(pred_df["close"].iloc[-1])

    pct_5 = round((pred_5 / last_close - 1) * 100, 2)
    pct_20 = round((pred_20 / last_close - 1) * 100, 2)

    direction = "up" if pct_20 > 2 else ("down" if pct_20 < -2 else "flat")

    # Save predicted OHLC bars for chart overlay
    pred_bars = []
    for i in range(len(pred_df)):
        pred_bars.append({
            "open": round(float(pred_df["open"].iloc[i]), 2),
            "high": round(float(pred_df["high"].iloc[i]), 2),
            "low": round(float(pred_df["low"].iloc[i]), 2),
            "close": round(float(pred_df["close"].iloc[i]), 2),
            "volume": round(float(pred_df.get("volume", pd.Series([0]*len(pred_df))).iloc[i]), 0),
        })

    return {
        "market": market,
        "symbol": symbol,
        "last_close": round(last_close, 2),
        "pred_5d_pct": pct_5,
        "pred_20d_pct": pct_20,
        "pred_direction": direction,
        "pred_bars": pred_bars,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _build_batch(reader: Any, stocks: list[tuple[str, str]], predictor: Any) -> list[dict[str, object]]:
    """Predict a list of stocks, return results."""
    results: list[dict[str, object]] = []
    total = len(stocks)
    t0 = time.time()

    for i, (market, symbol) in enumerate(stocks):
        result = _predict_stock(predictor, reader, market, symbol)
        if result is not None:
            results.append(result)

        if (i + 1) % 10 == 0 or i == total - 1:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            print(f"  [{i + 1}/{total}] {rate:.1f} stock/s  ETA {eta:.0f}s  results={len(results)}", flush=True)

    return results


# ── main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Kronos prediction dataset")
    parser.add_argument("--tdxdir", default=DEFAULT_TDX_DIR)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=0, help="Max stocks to predict (0=all)")
    parser.add_argument("--symbols", default="", help="Comma-separated market:symbol pairs")
    args = parser.parse_args()

    # ── Load model (once) ─────────────────────────────────────────
    print("[1/3] Loading Kronos model...", flush=True)
    from model import Kronos, KronosTokenizer, KronosPredictor

    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(model, tokenizer, max_context=LOOKBACK)
    print("  Model ready", flush=True)

    # ── Init reader ─────────────────────────────────────────────────
    from mootdx.reader import Reader

    reader = Reader.factory(market="std", tdxdir=args.tdxdir)

    # ── Build stock list ────────────────────────────────────────────
    print("[2/3] Building stock list...", flush=True)
    stocks: list[tuple[str, str]] = []

    if args.symbols:
        for pair in args.symbols.split(","):
            parts = pair.strip().split(":")
            if len(parts) == 2:
                stocks.append((parts[0].strip().lower(), parts[1].strip()))
    else:
        rps_rows = load_rps_rows()
        for row in rps_rows:
            mkt = str(row.get("market", "")).strip().lower()
            sym = str(row.get("symbol", "")).strip()
            if mkt and sym:
                stocks.append((mkt, sym))

    if args.limit > 0:
        stocks = stocks[: args.limit]

    print(f"  {len(stocks)} stocks to predict", flush=True)

    # ── Run predictions ─────────────────────────────────────────────
    print(f"[3/3] Predicting (CPU, ~1.5 stock/s)...", flush=True)
    results = _build_batch(reader, stocks, predictor)

    # ── Save ────────────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Merge with existing
    existing: dict[str, dict[str, object]] = {}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    for r in results:
        key = f"{r['market']}:{r['symbol']}"
        existing[key] = r

    output_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    up = sum(1 for r in results if r["pred_direction"] == "up")
    down = sum(1 for r in results if r["pred_direction"] == "down")
    flat = sum(1 for r in results if r["pred_direction"] == "flat")
    print(f"\nDone. {len(results)} stocks predicted.")
    print(f"  🟢 up: {up}  🔴 down: {down}  ⚪ flat: {flat}")
    print(f"  Saved to {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
