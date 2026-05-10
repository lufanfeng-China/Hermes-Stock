#!/usr/bin/env python3
"""同步东方财富资金流向数据到本地 Parquet。
用法:
  python scripts/sync_capital_flow.py              # 增量：只拉新日期
  python scripts/sync_capital_flow.py --full       # 全量：拉所有股票全部可用数据
  python scripts/sync_capital_flow.py --test 3     # 测试：只拉前3只
"""

import argparse
import http.client
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
ARCHIVE_DIR = PROJECT_ROOT / "data" / "archive"
CHECKPOINT_FILE = DATA_DIR / ".capital_flow_checkpoint"
DATASET_FILE = DATA_DIR / "dataset_stock_capital_flow.parquet"
STOCK_LIST_FILE = DATA_DIR / "dataset_stock_industry_current.json"

MAX_DAYS = 30  # 每只股票保留最近 N 天
RATE_LIMIT_SEC = 15.0  # 东方财富强限速，安全值 15s（提速需验证）
BATCH_SIZE = 200  # 每 N 只股票后额外休息
BATCH_PAUSE_SEC = 120  # 批次间额外暂停
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF = 60  # 被断连后等待秒数

FIELDS = [
    "trading_day", "net_main_force", "net_small", "net_medium",
    "net_large", "net_super_large", "pct_main_force", "pct_small",
    "pct_medium", "pct_large", "pct_super_large", "close", "gain_pct",
    "reserved_1", "reserved_2",
]


def load_stock_universe():
    """从 industry_current 数据集加载股票池，返回 [(symbol, stock_name, market)]"""
    if STOCK_LIST_FILE.exists():
        with open(STOCK_LIST_FILE) as f:
            data = json.load(f)
        stocks = []
        # dataset_stock_industry_current.json format: list of stock objects
        if isinstance(data, list):
            for s in data:
                symbol = str(s.get("symbol", "")).zfill(6)
                name = s.get("stock_name") or symbol
                mkt = s.get("market", "")
                if not mkt and symbol.startswith(("60", "68")):
                    mkt = "sh"
                elif not mkt:
                    mkt = "sz"
                if len(symbol) == 6 and symbol.isdigit():
                    stocks.append((symbol, name, mkt))
        elif isinstance(data, dict):
            # Try common formats
            for key in ["stocks", "data", "records"]:
                if key in data and isinstance(data[key], list):
                    for s in data[key]:
                        symbol = str(s.get("symbol", "")).zfill(6)
                        name = s.get("stock_name", symbol)
                        mkt = s.get("market", "sz")
                        if len(symbol) == 6 and symbol.isdigit():
                            stocks.append((symbol, name, mkt))
                    break
        return stocks
    return []


def load_stock_universe_from_serve():
    """Fallback: get stock list from the running server API"""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8765/api/stock-search?q=&limit=10000",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        if data.get("ok") and data.get("results"):
            stocks = []
            for s in data["results"]:
                symbol = str(s.get("symbol", "")).zfill(6)
                name = s.get("stock_name", symbol)
                mkt = s.get("market", "sz")
                if len(symbol) == 6 and symbol.isdigit():
                    stocks.append((symbol, name, mkt))
            return stocks
    except Exception as e:
        print(f"[WARN] Could not load from server API: {e}")
    return []


def eastmoney_market(symbol, mkt):
    """东方财富市场代码: 深市=0, 沪市=1"""
    if mkt == "sh" or symbol.startswith(("60", "68")):
        return 1
    return 0


def fetch_one_stock(symbol, em_market):
    """抓取单只股票资金流向，返回 DataFrame 或 None"""
    secid = f"{em_market}.{symbol}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        f"?lmt=0&klt=1&secid={secid}"
        f"&fields1=f1,f2,f3,f7"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
    )
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            data = json.loads(resp.read())
            raw = data.get("data", {}).get("klines") or []
            if not raw:
                return None
            rows = []
            for line in raw:
                parts = line.split(",")
                if len(parts) >= 15:
                    row = dict(zip(FIELDS, [parts[0]] + [float(x) for x in parts[1:]]))
                    row["symbol"] = symbol
                    rows.append(row)
            if rows:
                df = pd.DataFrame(rows)
                df["trading_day"] = df["trading_day"].astype(str)
                df["symbol"] = df["symbol"].astype(str)
                return df
            return None
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF)
            else:
                pass  # silently skip after max retries
    return None


def save_checkpoint(index):
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(str(index))


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            return int(CHECKPOINT_FILE.read_text().strip())
        except Exception:
            pass
    return 0


def clear_checkpoint():
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


def _check_connectivity(sample_stock):
    """测试 API 是否可达。返回 True/False。"""
    symbol, _, mkt = sample_stock
    em = eastmoney_market(symbol, mkt)
    try:
        url = f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=1&klt=1&secid={em}.{symbol}&fields1=f1,f2,f3,f7&fields2=f51"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return bool(data.get("data", {}).get("klines"))
    except Exception:
        return False


def run_sync(stocks, mode="incremental"):
    """执行同步。"""
    # 启动前连通性检查
    if not _check_connectivity(stocks[0]):
        print("[FATAL] 东方财富 API 不可达（IP 可能被限速），等待 30 分钟后重试...")
        print("[FATAL] 脚本将退出，请稍后手动重跑或等待 cron 触发。")
        sys.exit(1)

    total = len(stocks)
    # 加载已有数据
    existing = None
    existing_dates = set()
    if DATASET_FILE.exists() and mode == "incremental":
        existing = pd.read_parquet(DATASET_FILE)
        existing_dates = set(existing["trading_day"].unique())

    start_idx = load_checkpoint()
    if start_idx > 0:
        print(f"[RESUME] 从第 {start_idx + 1}/{total} 只继续...")

    all_new = []
    ok = 0
    failed = 0
    empty = 0
    t0 = time.time()

    for i in range(start_idx, total):
        symbol, name, mkt = stocks[i]
        em_market = eastmoney_market(symbol, mkt)
        time.sleep(RATE_LIMIT_SEC)

        df = fetch_one_stock(symbol, em_market)
        if df is None:
            empty += 1
            if (i + 1) % 100 == 0:
                _progress(i, total, ok, failed, empty, t0)
            continue

        df["stock_name"] = name
        df["market"] = mkt
        df["data_source"] = "eastmoney"

        # 只保留最近 MAX_DAYS 天
        if len(df) > MAX_DAYS:
            df = df.sort_values("trading_day", ascending=False).head(MAX_DAYS)

        # 增量模式：过滤已有日期
        if mode == "incremental" and existing_dates:
            df = df[~df["trading_day"].isin(existing_dates)]

        if len(df) > 0:
            all_new.append(df)

        ok += 1

        # 每 100 只保存断点 + 阶段性写入
        if (i + 1) % 100 == 0:
            _progress(i, total, ok, failed, empty, t0)
            save_checkpoint(i + 1)
            _write_batch(all_new, mode)
            all_new = []

        # 每 BATCH_SIZE 只额外休息
        if (i + 1) % BATCH_SIZE == 0 and i + 1 < total:
            print(f"  [BATCH PAUSE] {BATCH_PAUSE_SEC}s at stock {i+1}/{total}")
            time.sleep(BATCH_PAUSE_SEC)

    # 最后一批写入
    if all_new:
        _write_batch(all_new, mode)

    clear_checkpoint()
    elapsed = time.time() - t0
    print(f"\n[DONE] OK={ok} FAILED={failed} EMPTY={empty}/{total} 耗时 {elapsed/3600:.1f}h")
    _print_summary()


def _progress(i, total, ok, failed, empty, t0):
    elapsed = time.time() - t0
    rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
    eta = (total - i - 1) / rate if rate > 0 else 0
    print(f"  [{i+1}/{total}] OK={ok} FAIL={failed} EMPTY={empty}  "
          f"{rate:.0f}只/min ETA={eta:.0f}min")


def _write_batch(dfs, mode):
    """批量写入 Parquet，与已有数据合并去重"""
    if not dfs:
        return
    new_df = pd.concat(dfs, ignore_index=True)

    # 去重：同一 symbol + trading_day 保留最新
    new_df = new_df.drop_duplicates(subset=["symbol", "trading_day"], keep="last")

    if DATASET_FILE.exists():
        old_df = pd.read_parquet(DATASET_FILE)
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["symbol", "trading_day"], keep="last")
        # 每个 symbol 只保留最近 MAX_DAYS
        combined["_rank"] = combined.groupby("symbol")["trading_day"].rank(
            ascending=False, method="dense"
        )
        combined = combined[combined["_rank"] <= MAX_DAYS].drop(columns=["_rank"])
    else:
        combined = new_df

    DATASET_FILE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(DATASET_FILE, index=False)
    print(f"  [WRITE] {len(combined)} rows, {combined['symbol'].nunique()} stocks → {DATASET_FILE}")


def _print_summary():
    if not DATASET_FILE.exists():
        print("[SUMMARY] No data file.")
        return
    df = pd.read_parquet(DATASET_FILE)
    print(f"[SUMMARY] {len(df)} rows, {df['symbol'].nunique()} stocks, "
          f"{df['trading_day'].nunique()} trading days")
    print(f"  Date range: {df['trading_day'].min()} ~ {df['trading_day'].max()}")
    print(f"  File: {DATASET_FILE} ({DATASET_FILE.stat().st_size / 1024 / 1024:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Sync Eastmoney capital flow data")
    parser.add_argument("--full", action="store_true", help="Full sync, ignore existing data")
    parser.add_argument("--test", type=int, default=0, help="Test mode: only fetch N stocks")
    parser.add_argument("--reset", action="store_true", help="Delete existing data and start fresh")
    args = parser.parse_args()

    if args.reset and DATASET_FILE.exists():
        DATASET_FILE.unlink()
        clear_checkpoint()
        print("[RESET] Cleared existing data and checkpoint.")

    # 加载股票池
    stocks = load_stock_universe()
    if not stocks:
        stocks = load_stock_universe_from_serve()
    if not stocks:
        print("[ERROR] Cannot load stock universe. Make sure server is running or dataset exists.")
        sys.exit(1)

    if args.test > 0:
        stocks = stocks[: args.test]
        print(f"[TEST] Limited to {len(stocks)} stocks.")

    mode = "full" if args.full or args.reset or not DATASET_FILE.exists() else "incremental"
    print(f"[START] mode={mode} stocks={len(stocks)} max_days={MAX_DAYS} rate_limit={RATE_LIMIT_SEC}s")

    # 检查 venv
    if "moontdx" not in sys.executable:
        print("[WARN] Not running in moontdx venv. Some features may not work.")

    run_sync(stocks, mode)


if __name__ == "__main__":
    main()
