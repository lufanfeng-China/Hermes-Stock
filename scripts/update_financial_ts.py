#!/usr/bin/env python3
"""
update_financial_ts.py
======================
增量更新财务时间序列数据。

工作逻辑：
1. 读取 meta.json 获取每只股票已知最新报告期
2. 扫描最新的 gpcw zip，检测哪些股票有更新的财报（compare announce_date）
3. 对检测到新财报的股票：
   a. 从 zip 中提取完整行数据
   b. 按报告期追加到对应 by_quarter/*.parquet（不存在则创建）
   c. 更新 meta.json 中该股票的 periods 条目
4. 重算指定报告期的百分位排名快照（调用仓库版快照引擎）

用法：
    python scripts/update_financial_ts.py [--dry-run]
    python scripts/update_financial_ts.py [--full]   # 全量重建（调用 builder）
    python scripts/update_financial_ts.py [--rebuild-period 2025A]   # 重建指定期次快照
    python scripts/update_financial_ts.py [--rebuild-period latest] # 重建最新期快照

前置依赖：
    meta.json 已由 financial_ts_builder.py 初始化
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

# ── 路径配置 ────────────────────────────────────────────────────────────────
PROJECT = Path(__file__).parent.parent.resolve()
TDX_CW  = Path(os.environ.get("TDX_CW_DIR", "/mnt/c/new_tdx64/vipdoc/cw"))
OUT_DIR = PROJECT / "data/derived/financial_ts/by_quarter"
META_FP = PROJECT / "data/derived/financial_ts/meta.json"

sys.path.insert(0, "/home/lufanfeng/.venvs/moontdx-china-stock-data/lib/python3.12/site-packages")

# ── 报告期解析（与 builder 保持一致） ───────────────────────────────────────
def parse_period(report_date: int) -> str:
    s = str(report_date)
    year, month = int(s[:4]), int(s[4:6])
    if month == 3:  return f"{year}Q1"
    if month == 6:  return f"{year}Q2"
    if month == 9:  return f"{year}Q3"
    if month == 12: return f"{year}A"
    q = (month - 1) // 3
    return f"{year}Q{q}" if 1 <= q <= 4 else f"{year}A"


def format_announce_date(raw) -> int:
    """通达信 '财报公告日期' 格式为 YYMMDD 浮点数，如 260422.0 = 2026-04-22。"""
    try:
        v = float(raw)
        if np.isnan(v) or v == 0:
            return 0
        yymmdd = int(v)
        yy = yymmdd // 10000
        mm = (yymmdd % 10000) // 100
        dd = yymmdd % 100
        yy += 2000 if yy < 50 else 1900
        return yy * 10000 + mm * 100 + dd
    except (TypeError, ValueError):
        return 0


def canonical_code(idx_val) -> str:
    s = str(idx_val).strip().lower()
    for p in ("sh:", "sz:", "bj:"):
        s = s.replace(p, "")
    return s


def _period_order(p: str) -> tuple:
    """将 '2023A' / '2023Q1' 转为排序键 (year, q)。年报 q=5 排在 Q3 之后。"""
    if not p:
        return (0, 0)
    year = int(p[:4])
    if "A" in p:
        q = 5
    else:
        q = int(p[-1])
    return (year, q)


# ── Meta 读写 ────────────────────────────────────────────────────────────────
def load_meta() -> dict:
    if not META_FP.exists():
        print("ERROR: meta.json 不存在，请先运行 financial_ts_builder.py 全量初始化", file=sys.stderr)
        sys.exit(1)
    with open(META_FP) as f:
        return json.load(f)


def save_meta(meta: dict):
    meta["last_updated"] = pd.Timestamp.now().isoformat()
    with open(META_FP, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ── 从 gpcw zip 读取目标股票记录 ───────────────────────────────────────────
def read_stock_records_from_zip(zpath: Path, target_codes: set[str]) -> dict[str, dict]:
    """从 zip 中提取目标股票的数据记录。"""
    from mootdx.financial.financial import FinancialReader
    try:
        df = FinancialReader.to_data(str(zpath))
    except Exception:
        return {}

    if df.empty:
        return {}

    df = df.reset_index()
    code_col = df.columns[0]
    df = df.rename(columns={code_col: "code"})
    df["code"] = df["code"].astype(str).apply(canonical_code)

    # 清洗列名
    df.columns = [c.rsplit(".", 1)[0] if "." in c else c for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated(keep="first")]

    # 只保留目标股票
    df = df[df["code"].isin(target_codes)]
    if df.empty:
        return {}

    # 同代码取最新 report_date
    df = df.sort_values("report_date").drop_duplicates(subset="code", keep="last")
    df = df.set_index("code")

    result = {}
    for code, row in df.iterrows():
        rd = int(row.get("report_date", 0))
        ad = format_announce_date(row.get("财报公告日期", 0))
        if rd == 0 or pd.isna(rd):
            continue
        record = row.to_dict()
        record["code"] = code
        record["report_date"] = rd
        record["announce_date"] = ad
        result[code] = record
    return result


# ── Parquet 读写 ─────────────────────────────────────────────────────────────
def read_quarter_parquet(period: str) -> pd.DataFrame:
    fp = OUT_DIR / f"{period}.parquet"
    if not fp.exists():
        return pd.DataFrame()
    return pd.read_parquet(fp)


def append_to_quarter_parquet(period: str, new_records: list[dict]):
    """将新记录追加到已有季度文件（去重：同股票代码保留最新）。"""
    fp = OUT_DIR / f"{period}.parquet"
    if fp.exists():
        existing = pd.read_parquet(fp)
        new_df = pd.DataFrame(new_records).set_index("code")
        combined = pd.concat([existing, new_df])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")
    else:
        df = pd.DataFrame(new_records).set_index("code")
        df.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")
    size_kb = fp.stat().st_size / 1024
    print(f"  → {fp.name}: {len(new_records)} 条新记录, 总 {size_kb:.0f} KB")


# ── 增量检测（修复版）────────────────────────────────────────────────────────
def detect_updates(meta: dict) -> list[tuple[str, str, int, int, dict]]:
    """检测哪些股票有新的财报。

    修复：所有 zip 收集完毕后统一去重，写入 meta 前不更新 meta 状态，
    确保同股票多 period 都能被正确写入各自的 parquet 文件。

    Returns:
        [(code, new_period, report_date, announce_date, full_record), ...]
    """
    # 保存原始 meta 状态用于候选判断（不依赖写入中间态）
    orig_latest: dict[str, str] = {
        code: info["latest_period"]
        for code, info in meta["stocks"].items()
        if info.get("latest_period")
    }

    # 扫描最新 5 个 zip
    zips = sorted(TDX_CW.glob("gpcw*.zip"), reverse=True)[:5]

    all_records: list[tuple[str, str, int, int, dict]] = []

    for zpath in zips:
        zip_period_str = parse_period(int(zpath.stem[-8:]))
        print(f"  扫描 {zpath.name} (zip_period={zip_period_str})", end=" ... ", flush=True)

        # 以 zip 文件名的 period 为参考，找出 meta 中已知旧于该 zip 的股票
        # 注意：zip 里可能同时包含多个报告期数据（如同一天发布的 Q3 + A），全部纳入
        candidates = {
            code: latest
            for code, latest in orig_latest.items()
            if _period_order(latest) < _period_order(zip_period_str)
        }
        if not candidates:
            print("无候选股票")
            continue

        records = read_stock_records_from_zip(zpath, set(candidates.keys()))
        print(f"获取 {len(records)} 条记录", end="", flush=True)

        found = 0
        for code, record in records.items():
            rd = record["report_date"]
            ad = record["announce_date"]
            new_period = parse_period(int(rd))
            orig_prev = orig_latest.get(code, "")
            # 以原始 meta 状态判断是否真正更新（不在写入过程中动态判断）
            if _period_order(new_period) > _period_order(orig_prev):
                all_records.append((code, new_period, rd, ad, record))
                found += 1

        print(f", 其中 {found} 条为新增记录")

    # 去重策略：同 (code, period) 保留 announce_date 最新的一条
    # 允许同一只股票保留多个不同 period 的记录
    def record_key(x):
        code, period, rd, ad, _ = x
        return (code, period, -ad, -rd)

    all_records.sort(key=record_key)
    seen: dict[tuple[str, str], bool] = {}
    updates: list[tuple[str, str, int, int, dict]] = []
    for rec in all_records:
        code, period = rec[0], rec[1]
        if (code, period) not in seen:
            seen[(code, period)] = True
            updates.append(rec)

    return updates


# ── Snapshot rebuild ──────────────────────────────────────────────────────────
SNAPSHOT_SCRIPT = PROJECT / "scripts/build_financial_snapshot_from_warehouse.py"


def rebuild_snapshot(period: str = "latest"):
    """Call the warehouse-based snapshot builder to regenerate a snapshot."""
    import subprocess
    cmd = [
        sys.executable, str(SNAPSHOT_SCRIPT), period,
    ]
    print(f"\n=== 重建快照: {period} ===")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"快照重建失败:\n{result.stderr}", file=sys.stderr)
        return False
    print(result.stdout)
    return True


# ── Main流程 ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检测，不写入")
    ap.add_argument("--full", action="store_true", help="全量重建模式（调用 builder）")
    ap.add_argument("--rebuild-period", type=str, default=None,
                    help="重建指定报告期的快照（如 2025A, latest）")
    args = ap.parse_args()

    # 单独重建快照模式
    if args.rebuild_period:
        ok = rebuild_snapshot(args.rebuild_period)
        sys.exit(0 if ok else 1)

    print("增量更新财务时间序列\n")
    meta = load_meta()
    print(f"Meta: {meta['stock_count']} 只股票, last_updated={meta.get('last_updated', 'N/A')}\n")

    if args.full:
        print("[FULL MODE] 请使用 financial_ts_builder.py 进行全量重建")
        sys.exit(0)

    # 增量检测
    print("=== 检测新财报 ===")
    t0 = time.time()
    updates = detect_updates(meta)
    print(f"\n发现 {len(updates)} 只股票有新财报 (检测耗时 {time.time()-t0:.1f}s)\n")

    if not updates:
        print("无需更新，退出")
        sys.exit(0)

    if args.dry_run:
        print("=== DRY RUN ===")
        for code, period, rd, ad, _ in sorted(updates, key=lambda x: x[1], reverse=True):
            prev = meta["stocks"].get(code, {}).get("latest_period", "N/A")
            print(f"  {code}: {prev} → {period} (report_date={rd}, announce={ad})")
        sys.exit(0)

    # 增量写入：按 period 从旧到新写（确保新 period 数据不覆盖旧 period）
    # 关键：所有 parquet 写完之前不更新 meta，避免写入中间态影响判断
    print("=== 写入更新 ===")
    by_period: dict[str, list[dict]] = defaultdict(list)
    for code, period, rd, ad, record in updates:
        by_period[period].append(record)

    for period, records in sorted(by_period.items(), key=lambda x: _period_order(x[0])):
        append_to_quarter_parquet(period, records)

    # 所有 parquet 写入完毕后再一次性更新 meta
    for code, period, rd, ad, record in updates:
        if code not in meta["stocks"]:
            meta["stocks"][code] = {"name": "", "periods": {}, "latest_period": ""}
        period_key = period
        if period_key not in meta["stocks"][code]["periods"]:
            meta["stocks"][code]["periods"][period_key] = {
                "report_date": rd,
                "announce_date": ad,
                "file": f"{period_key}.parquet",
            }
        prev = meta["stocks"][code]["latest_period"]
        if _period_order(period_key) >= _period_order(prev):
            meta["stocks"][code]["latest_period"] = period_key

    save_meta(meta)
    print(f"\nMeta 已更新: {meta['stock_count']} 只股票")
    print(f"本次新增 {len(updates)} 条股票-报告期记录")

    # 重建最新期快照
    # 找出本次更新涉及的最新年份
    if updates:
        latest_period = max((u[1] for u in updates), key=_period_order)
        rebuild_snapshot(latest_period)


if __name__ == "__main__":
    main()
