#!/usr/bin/env python3
"""Materialize an announcement-date-correct historical fundamental filter snapshot."""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.financial.reports import _load_raw_daily_bars
from app.search import index as search_index
from app.stock_filter_fundamental_history import build_historical_fundamental_snapshot
from app.relative_valuation.pe_percentile_snapshot import compute_for_stock, load_disclosures_bulk
from app.stock_filter_history_progress import write_progress
from app.stock_filter_market_snapshot import build_market_metrics

WAREHOUSE = ROOT / "data" / "derived" / "financial_ts" / "by_quarter"
OUT_DIR = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_fundamental_history"
QFQ_DAILY = ROOT / "data" / "derived" / "datasets" / "final" / "stock_filter_qfq_daily.parquet"


def resolve_latest_day() -> str:
    """Resolve at task execution, and refuse to publish mismatched raw/QFQ days."""
    from app.pipeline.commands import _latest_trading_day_for_refresh
    from app.pipeline.task_freshness import task_freshness

    raw_day = _latest_trading_day_for_refresh()
    if not raw_day:
        raise ValueError("无法核验原始日线最新交易日，PIT快照未发布")
    raw_day = date.fromisoformat(raw_day).isoformat()
    qfq_day = task_freshness('build_stock_filter_qfq_daily', ROOT / 'data' / 'derived')['data_date']
    market_day = task_freshness('build_stock_filter_market_snapshot', ROOT / 'data' / 'derived')['data_date']
    if raw_day != qfq_day or raw_day != market_day:
        raise ValueError(f"PIT源日期未对齐：原始日线 {raw_day}，前复权日线 {qfq_day or '未知'}，行情快照 {market_day or '未知'}；拒绝发布")
    return raw_day


def financial_warehouse_signature(warehouse: Path = WAREHOUSE) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in Path(warehouse).glob('20*.parquet') if path.is_file())
    for path in files:
        stat = path.stat()
        digest.update(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}\n'.encode())
    return digest.hexdigest()


def reusable_snapshot(path: Path, day: str, financial_signature: str | None = None) -> bool:
    """Reuse only an atomically published, parseable current-schema PIT file."""
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    stocks = payload.get('stocks') if isinstance(payload, dict) else None
    return (isinstance(payload, dict)
            and payload.get('schema_version') == 'stock-filter-fundamental-history-v7'
            and payload.get('as_of_date') == day
            and payload.get('financial_information_cutoff') == day
            and (financial_signature is None
                 or payload.get('financial_warehouse_signature') == financial_signature)
            and payload.get('valuation_price_basis') == 'raw_unadjusted_close'
            and isinstance(stocks, dict) and bool(stocks)
            and all(isinstance(key, str) and ':' in key and isinstance(row, dict)
                    for key, row in stocks.items()))


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


def _raw_closes(as_of_date: str, symbols: list[str], on_progress=None, on_bars=None) -> dict[str, float]:
    closes = {}
    cutoff = (pd.Timestamp(as_of_date) - pd.DateOffset(years=5)).date().isoformat()
    for count, symbol in enumerate(symbols, 1):
        bars = _load_raw_daily_bars(search_index, symbol)
        if on_bars is not None:
            history = []
            before_cutoff = None
            for bar in bars:
                day = str(bar.get('trading_day') or '')
                if day > as_of_date:
                    continue
                try:
                    close = float(bar.get('close'))
                    if close <= 0:
                        continue
                    point = (pd.Timestamp(day).date(), close)
                    if day < cutoff:
                        before_cutoff = point
                    else:
                        history.append(point)
                except (TypeError, ValueError):
                    pass
            on_bars(symbol, ([before_cutoff] if before_cutoff else []) + history)
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
    dates = parser.add_mutually_exclusive_group(required=True)
    dates.add_argument("--trading-day", help="YYYY-MM-DD; must be an available raw daily trading day")
    dates.add_argument("--latest-trading-day", action="store_true", help="resolve matching raw and QFQ dates at task execution")
    parser.add_argument("--adopt-lock", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.adopt_lock and not args.trading_day:
        parser.error('--adopt-lock requires --trading-day')
    day = resolve_latest_day() if args.latest_trading_day else date.fromisoformat(args.trading_day).isoformat()
    args.trading_day = day
    output = args.output or OUT_DIR / f"{day}.json"
    warehouse_signature = financial_warehouse_signature()
    if args.output is None and reusable_snapshot(output, day, financial_signature=warehouse_signature):
        print(json.dumps({'output': str(output), 'trading_day': day, 'reused': True}, ensure_ascii=False), flush=True)
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lock = OUT_DIR / f"{args.trading_day}.building"
    if args.adopt_lock:
        if not lock.exists():
            raise SystemExit(f"预置历史快照锁已消失：{lock}")
    else:
        try:
            with lock.open('x', encoding='utf-8') as handle:
                handle.write(str(os.getpid()))
        except FileExistsError:
            raise SystemExit(f"{day} PIT快照构建中或遗留锁未清理：{lock}；拒绝重复启动，请核查进程和日志")
    atexit.register(lambda: lock.unlink(missing_ok=True))
    write_progress(OUT_DIR, args.trading_day, stage="读取历史财报版本", percent=1)
    frames = {path.stem: pd.read_parquet(path) for path in WAREHOUSE.glob("*.parquet") if path.stem != "latest"}
    markets = _market_by_symbol()
    disclosures = load_disclosures_bulk(WAREHOUSE, args.trading_day)
    pe_by_key = {}
    def on_stock_bars(symbol, bars):
        pe_by_key[f'{markets[symbol]}:{symbol}'] = compute_for_stock(bars, disclosures.get(symbol, []), args.trading_day)
    write_progress(OUT_DIR, args.trading_day, stage="读取信号日原始收盘价", percent=5, completed=0, total=len(markets))
    closes = _raw_closes(args.trading_day, sorted(markets), on_progress=lambda done, total: write_progress(OUT_DIR, args.trading_day, stage="读取信号日原始收盘价", percent=5 + 45 * done / total, completed=done, total=total), on_bars=on_stock_bars)
    if not closes:
        raise SystemExit(f"{args.trading_day} is not an available raw-price trading day")
    write_progress(OUT_DIR, args.trading_day, stage="读取前复权量价数据", percent=51)
    qfq = pd.read_parquet(QFQ_DAILY, columns=["date", "market", "symbol", "open", "close", "volume", "free_float_shares"])
    qfq["date"] = pd.to_datetime(qfq["date"])
    qfq = qfq[qfq["date"] <= pd.Timestamp(args.trading_day)]
    write_progress(OUT_DIR, args.trading_day, stage="计算历史爆量突破量价与趋势", percent=55)
    market_payload = build_market_metrics(qfq, on_progress=lambda done, total: write_progress(OUT_DIR, args.trading_day, stage="计算历史爆量突破量价与趋势", percent=55 + 40 * done / total, completed=done, total=total) and None)
    from app.stock_filter_turnover_snapshot import build_turnover_snapshot, reports_from_frames
    turnover_payload, _ = build_turnover_snapshot(
        qfq, reports_from_frames(frames), as_of_date=args.trading_day,
        universe_keys={f'{market}:{symbol}' for symbol, market in markets.items()},
        on_daily=lambda batch: None,
    )
    write_progress(OUT_DIR, args.trading_day, stage="合并 point-in-time 财务与量价快照", percent=96)
    payload = build_historical_fundamental_snapshot(
        as_of_date=args.trading_day, period_frames=frames, raw_close_by_symbol=closes,
        market_by_symbol=markets, industry_by_key=_industry_by_key(), market_metrics_by_key=market_payload["metrics"], pe_by_key=pe_by_key,
        turnover_by_key=turnover_payload['stocks'],
    )
    payload['financial_warehouse_signature'] = warehouse_signature
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
