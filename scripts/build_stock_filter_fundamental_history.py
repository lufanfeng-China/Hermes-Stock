#!/usr/bin/env python3
"""Materialize an announcement-date-correct historical fundamental filter snapshot."""
from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.financial.reports import _load_raw_daily_bars
from app.search import index as search_index
from app.stock_filter_fundamental_history import build_historical_fundamental_snapshot
from app.stock_filter_history_progress import write_progress
from app.stock_filter_market_snapshot import build_market_metrics

WAREHOUSE = ROOT / "data" / "derived" / "financial_ts" / "by_quarter"
OUT_DIR = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_fundamental_history"
QFQ_DAILY = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_qfq_daily.parquet"


def _market_by_symbol() -> dict[str, str]:
    result = {}
    for item in search_index.load_security_rows():
        symbol = str(item.get("symbol") or "").zfill(6)
        market = "sh" if symbol.startswith("6") else "sz" if symbol.startswith(("00", "30")) else "bj" if symbol.startswith("92") else ""
        if market:
            result[symbol] = market
    return result


def _industry_by_key() -> dict[tuple[str, str], tuple[str | None, str | None]]:
    result = {}
    for item in search_index.load_industry_rows():
        market = str(item.get("market") or "").lower()
        market = "bj" if market == "2" else market
        symbol = str(item.get("symbol") or "").zfill(6)
        result[(market, symbol)] = (str(item.get("industry_level_1_name") or "").strip() or None, str(item.get("industry_level_2_name") or "").strip() or None)
    return result


def _raw_closes(as_of_date: str, symbols: list[str], on_progress=None) -> dict[str, float]:
    closes = {}
    for count, symbol in enumerate(symbols, 1):
        bars = _load_raw_daily_bars(search_index, symbol)
        matches = [bar for bar in bars if str(bar.get("trading_day")) == as_of_date]
        if matches:
            close = matches[-1].get("close")
            try:
                close = float(close)
                if close > 0:
                    closes[symbol] = close
            except (TypeError, ValueError):
                pass
        if count % 500 == 0:
            print(f"[raw close {count}/{len(symbols)}]", flush=True)
        if on_progress is not None and (count % 50 == 0 or count == len(symbols)):
            on_progress(count, len(symbols))
    return closes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-day", required=True, help="YYYY-MM-DD; must be an available raw daily trading day")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    lock = OUT_DIR / f"{args.trading_day}.building"
    atexit.register(lambda: lock.unlink(missing_ok=True))
    pd.Timestamp(args.trading_day)  # validate date shape
    write_progress(OUT_DIR, args.trading_day, stage="读取历史财报版本", percent=1)
    frames = {path.stem: pd.read_parquet(path) for path in WAREHOUSE.glob("*.parquet") if path.stem != "latest"}
    markets = _market_by_symbol()
    write_progress(OUT_DIR, args.trading_day, stage="读取信号日原始收盘价", percent=5, completed=0, total=len(markets))
    closes = _raw_closes(args.trading_day, sorted(markets), on_progress=lambda done, total: write_progress(OUT_DIR, args.trading_day, stage="读取信号日原始收盘价", percent=5 + 45 * done / total, completed=done, total=total))
    if not closes:
        raise SystemExit(f"{args.trading_day} is not an available raw-price trading day")
    write_progress(OUT_DIR, args.trading_day, stage="读取前复权量价数据", percent=51)
    qfq = pd.read_parquet(QFQ_DAILY, columns=["date", "market", "symbol", "open", "close", "volume", "free_float_shares"])
    qfq["date"] = pd.to_datetime(qfq["date"])
    qfq = qfq[qfq["date"] <= pd.Timestamp(args.trading_day)]
    write_progress(OUT_DIR, args.trading_day, stage="计算历史爆量突破量价与趋势", percent=55)
    market_payload = build_market_metrics(qfq, on_progress=lambda done, total: write_progress(OUT_DIR, args.trading_day, stage="计算历史爆量突破量价与趋势", percent=55 + 40 * done / total, completed=done, total=total) and None)
    write_progress(OUT_DIR, args.trading_day, stage="合并 point-in-time 财务与量价快照", percent=96)
    payload = build_historical_fundamental_snapshot(
        as_of_date=args.trading_day, period_frames=frames, raw_close_by_symbol=closes,
        market_by_symbol=markets, industry_by_key=_industry_by_key(), market_metrics_by_key=market_payload["metrics"],
    )
    output = args.output or OUT_DIR / f"{args.trading_day}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_progress(OUT_DIR, args.trading_day, stage="写入历史快照", percent=99)
    with NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        temp = Path(handle.name)
    os.replace(temp, output)
    write_progress(OUT_DIR, args.trading_day, stage="快照完成", percent=100)
    print(json.dumps({"output": str(output), "trading_day": args.trading_day, "stocks": len(payload["stocks"]), "priced_stocks": len(closes), "market_metrics": market_payload["stocks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
