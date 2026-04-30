#!/usr/bin/env python3
"""
financial_ts_builder.py
========================
从通达信本地财务包 (vipdoc/cw/gpcwYYYYMMDD.zip) 一次性抽取所有历史财报数据，
写入 data/derived/financial_ts/by_quarter/*.parquet 季度文件，同时维护 meta.json。

用法：
    python scripts/financial_ts_builder.py [--force]

    --force   跳过已有季度文件的检查，强制全量重建
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
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 通达信 Python 环境 ───────────────────────────────────────────────────────
PYTHON_TDX = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
sys.path.insert(0, "/home/lufanfeng/.venvs/moontdx-china-stock-data/lib/python3.12/site-packages")

# ── 报告期解析 ──────────────────────────────────────────────────────────────
def parse_period(report_date: int) -> str:
    """从 YYYYMMDD 整数解析财务报告所属期字符串。

    规则：
        0331 → Q1,  0630 → Q2,  0930 → Q3,  1231 → A
        其余月份按 (month-1)//3 推算季度。
    """
    s = str(report_date)
    year  = int(s[:4])
    month = int(s[4:6])
    if month == 3:  return f"{year}Q1"
    if month == 6:  return f"{year}Q2"
    if month == 9:  return f"{year}Q3"
    if month == 12: return f"{year}A"
    q = (month - 1) // 3
    return f"{year}Q{q}" if 1 <= q <= 4 else f"{year}A"


def format_announce_date(raw) -> int:
    """把财报公告日期字段规范化为 YYYYMMDD 整数。

    通达信 '财报公告日期' 字段格式为 YYMMDD 浮点数 (260422.0 = 2026-04-22)。
    注意这是两位数年份，需要加 2000 偏移。
    """
    try:
        v = float(raw)
        if np.isnan(v) or v == 0:
            return 0
        yymmdd = int(v)
        yy = yymmdd // 10000
        mm = (yymmdd % 10000) // 100
        dd = yymmdd % 100
        # 两位年 → 四位年（20xx）
        if yy < 50:
            yy += 2000
        else:
            yy += 1900
        return yy * 10000 + mm * 100 + dd
    except (TypeError, ValueError):
        return 0


def canonical_code(idx_val) -> str:
    """把通达信股票代码索引规范化为 '600519' / '000001' 等纯数字字符串。
    去掉 'sh:' / 'sz:' 等前缀。
    """
    s = str(idx_val).strip()
    for prefix in ("sh:", "sz:", "bj:", "SH:", "SZ:", "BJ:"):
        s = s.replace(prefix, "")
    return s


# ── 读取单个 gpcw zip ────────────────────────────────────────────────────────
def load_cw_zip(zpath: Path) -> pd.DataFrame | None:
    """加载并清洗单个 gpcw*.zip 文件，返回 (股票数, DataFrame)。"""
    from mootdx.financial.financial import FinancialReader
    try:
        df = FinancialReader.to_data(str(zpath))
    except Exception as e:
        print(f"  [WARN] 解析失败 {zpath.name}: {e}", file=sys.stderr)
        return None

    if df.empty:
        return None

    # 清洗 index → code
    # reset_index() 后第一列就是原 index（列名='code'）
    df = df.reset_index()
    code_col = df.columns[0]  # 就是 'code'
    df = df.rename(columns={code_col: 'code'})
    df['code'] = df['code'].astype(str).apply(canonical_code)

    # 按 code + report_date 去重（保留最新）
    df = df.sort_values("report_date").drop_duplicates(subset="code", keep="last")

    # 清洗列名：去掉末尾 .1 / .2 编号，合并同名列（取第一个非 NaN）
    df.columns = [c.rsplit(".", 1)[0] if "." in c else c for c in df.columns]
    # 先取第一行来判断哪些列是重复的
    dup_cols = df.columns[df.columns.duplicated(keep=False)]
    if not dup_cols.empty:
        df = df.loc[:, ~df.columns.duplicated(keep="first")]

    df = df.set_index("code")
    return df


# ── 季度数据写入 ─────────────────────────────────────────────────────────────
def write_quarter_parquet(period: str, records: list[dict]):
    """将一个季度内所有股票记录写入 Parquet，按 period 分文件。"""
    fp = OUT_DIR / f"{period}.parquet"
    df = pd.DataFrame(records).set_index("code")
    df.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")
    size_kb = fp.stat().st_size / 1024
    print(f"  → {period}.parquet  ({len(records)} 股票, {size_kb:.0f} KB)")


# ── Meta 维护 ────────────────────────────────────────────────────────────────
def load_meta() -> dict:
    if META_FP.exists():
        with open(META_FP) as f:
            return json.load(f)
    return {
        "version": "1.0",
        "last_updated": "",
        "data_dir": "by_quarter",
        "stock_count": 0,
        "stocks": {},
    }


def save_meta(meta: dict):
    meta["last_updated"] = pd.Timestamp.now().isoformat()
    META_FP.parent.mkdir(parents=True, exist_ok=True)
    with open(META_FP, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="强制全量重建，跳过已有检查")
    args = ap.parse_args()

    print(f"通达信财务目录 : {TDX_CW}")
    print(f"输出目录       : {OUT_DIR}")
    print()

    # 扫描所有 gpcw zip，按文件名排序（由新到旧）
    # 只处理 2022 年及以后的包（之前的财报历史对当前分析价值有限）
    zips = sorted(TDX_CW.glob("gpcw*.zip"), reverse=True)
    zips = [z for z in zips if int(z.stem[-8:][:4]) >= 2022]
    if not zips:
        print("ERROR: 找不到 2022 年以后的 gpcw*.zip 文件", file=sys.stderr)
        sys.exit(1)

    print(f"发现 {len(zips)} 个 2022 年以后的 gpcw 压缩包\n")

    # 按报告期聚合：period → [(announce_date, report_date, code, row_dict), ...]
    period_data: dict[str, list[dict]] = defaultdict(list)
    periods_seen: set[str] = set()
    total_stocks = 0

    meta = load_meta()

    for zpath in zips:
        period_str = parse_period(int(zpath.stem[-8:]))  # 从文件名提取日期
        if period_str in periods_seen and not args.force:
            print(f"  跳过 {zpath.name} (period={period_str} 已处理)")
            continue

        print(f"处理 {zpath.name}  (period={period_str})")
        t0 = time.time()
        df = load_cw_zip(zpath)
        elapsed = time.time() - t0

        if df is None or df.empty:
            print(f"  → 空包或解析失败，跳过")
            continue

        for code, row in df.iterrows():
            rd = int(row.get("report_date", 0))
            ad = format_announce_date(row.get("财报公告日期", 0))

            # 只保留有报告期的记录
            if rd == 0 or pd.isna(rd):
                continue

            row_dict = {**row.to_dict(), "report_date": rd, "announce_date": ad, "code": code}

            # 更新 meta
            if code not in meta["stocks"]:
                meta["stocks"][code] = {"name": "", "periods": {}, "latest_period": ""}

            period_key = parse_period(int(rd))
            if period_key not in meta["stocks"][code]["periods"]:
                meta["stocks"][code]["periods"][period_key] = {
                    "report_date":   rd,
                    "announce_date": ad,
                    "file":          f"{period_key}.parquet",
                }
            # 始终更新最新期
            prev = meta["stocks"][code]["latest_period"]
            if _period_order(period_key) >= _period_order(prev):
                meta["stocks"][code]["latest_period"] = period_key

            period_data[period_key].append(row_dict)

        periods_seen.add(period_str)
        total_stocks += len(df)
        print(f"  → {len(df)} 只股票, {elapsed:.1f}s")

    print(f"\n写入季度文件...")
    for period, records in sorted(period_data.items()):
        write_quarter_parquet(period, records)

    # 写入 latest symlink（最新季度）
    latest_period = max(period_data.keys(), key=_period_order)
    latest_fp = OUT_DIR / "latest.parquet"
    if latest_fp.exists() or latest_fp.is_symlink():
        latest_fp.unlink()
    latest_fp.symlink_to(f"{latest_period}.parquet", target_is_directory=False)

    # 更新 meta
    meta["stock_count"] = len(meta["stocks"])
    save_meta(meta)

    print(f"\n完成！共处理 {total_stocks} 条股票记录，{len(period_data)} 个季度")
    print(f"Meta 已写入 {META_FP}")


def _period_order(p: str) -> tuple:
    """将 '2023A' / '2023Q1' 转为排序键 (year, q)"""
    if not p:
        return (0, 0)
    year = int(p[:4])
    if "A" in p:
        q = 5  # 年报排在 Q3 之后
    else:
        q = int(p[-1])
    return (year, q)


if __name__ == "__main__":
    main()
