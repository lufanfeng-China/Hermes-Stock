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
TDX_CW  = Path(os.environ.get("TDX_CW_DIR", "/home/lufanfeng/tdx_data/vipdoc/cw"))
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


# ── 季度数据写入（支持增量追加）──────────────────────────────────────────────
def write_quarter_parquet(period: str, records: list[dict]):
    """将一个季度内所有股票记录写入 Parquet，按 period 分文件。
    去重：同一 code 保留第一条（因为 zip 按新旧顺序处理，第一条 = 最新数据）。"""
    fp = OUT_DIR / f"{period}.parquet"
    df = pd.DataFrame(records).set_index("code")
    df = df[~df.index.duplicated(keep="first")]
    df.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")
    size_kb = fp.stat().st_size / 1024
    print(f"  → {period}.parquet  ({len(df)} 股票, {size_kb:.0f} KB)")


def append_quarter_parquet(period: str, records: list[dict]):
    """增量追加记录到已有 parquet 文件。跳过已存在的 code。
    返回实际新增的股票数。"""
    fp = OUT_DIR / f"{period}.parquet"
    new_df = pd.DataFrame(records).set_index("code")
    new_df = new_df[~new_df.index.duplicated(keep="first")]

    if fp.exists():
        existing = pd.read_parquet(fp)
        # 只保留新 code
        new_codes = new_df.index.difference(existing.index)
        new_df = new_df.loc[new_codes]
        if new_df.empty:
            return 0
        combined = pd.concat([existing, new_df])
        combined.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")
    else:
        new_df.to_parquet(fp, index=True, engine="pyarrow", compression="snappy")

    return len(new_df)


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
    zips = sorted(TDX_CW.glob("gpcw*.zip"), reverse=True)
    zips = [z for z in zips if int(z.stem[-8:][:4]) >= 2010]
    if not zips:
        print("ERROR: 找不到 2010 年以后的 gpcw*.zip 文件", file=sys.stderr)
        sys.exit(1)

    print(f"发现 {len(zips)} 个 2010 年以后的 gpcw 压缩包\n")

    # ── 流式处理：每个 zip 处理完立即写 parquet，释放内存
    periods_seen: set[str] = set()
    total_stocks = 0
    period_new_counts: dict[str, int] = defaultdict(int)

    meta = load_meta()

    # --force 时清空已有 parquet 文件
    if args.force:
        for existing in OUT_DIR.glob("*.parquet"):
            existing.unlink()
        periods_seen.clear()

    for zpath in zips:
        period_str = parse_period(int(zpath.stem[-8:]))
        if period_str in periods_seen:
            print(f"  跳过 {zpath.name} (period={period_str} 已处理)")
            continue

        print(f"处理 {zpath.name}  (period={period_str})")
        t0 = time.time()
        df = load_cw_zip(zpath)
        elapsed = time.time() - t0

        if df is None or df.empty:
            print(f"  → 空包或解析失败，跳过")
            continue

        # ── 按实际 report_date 分组
        period_batches: dict[str, list[dict]] = defaultdict(list)

        for code, row in df.iterrows():
            rd = int(row.get("report_date", 0))
            if rd == 0 or pd.isna(rd):
                continue

            ad = format_announce_date(row.get("财报公告日期", 0))
            row_dict = {**row.to_dict(), "report_date": rd, "announce_date": ad, "code": code}

            # ── 提取通达信预计算 TTM 字段（万元 → 亿）──
            _ttm_net = row.get("近一年归母净利润（万元）", None)
            try:
                _ttm_net = float(_ttm_net)
                if not pd.isna(_ttm_net) and _ttm_net > 0:
                    row_dict["ttm_net_profit_yi"] = _ttm_net / 1_0000.0
            except (TypeError, ValueError):
                pass

            _ttm_rev = row.get("营业总收入TTM(万元)", None)
            try:
                _ttm_rev = float(_ttm_rev)
                if not pd.isna(_ttm_rev) and _ttm_rev > 0:
                    row_dict["ttm_revenue_yi"] = _ttm_rev / 1_0000.0
            except (TypeError, ValueError):
                pass

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
            prev = meta["stocks"][code]["latest_period"]
            if _period_order(period_key) >= _period_order(prev):
                meta["stocks"][code]["latest_period"] = period_key

            period_batches[period_key].append(row_dict)

        # ── 立即写入各期 parquet，释放内存
        for period_key, records in period_batches.items():
            n = append_quarter_parquet(period_key, records)
            period_new_counts[period_key] += n
            if n > 0:
                print(f"  → {period_key}.parquet  +{n} 只新股票")

        periods_seen.add(period_str)
        total_stocks += len(df)
        print(f"  → 处理了 {len(df)} 只股票, {elapsed:.1f}s")

        # 释放内存：删掉大的 DataFrame 和批次数据
        del df, period_batches
        import gc; gc.collect()

    # ── 汇总写入结果
    n_periods = len(period_new_counts)
    n_new_records = sum(period_new_counts.values())
    print(f"\n写入完成！共 {n_periods} 个季度，{n_new_records} 条新记录")

    # ── 写入 latest symlink
    all_periods = sorted(OUT_DIR.glob("*.parquet"))
    all_periods = [p for p in all_periods if p.stem != "latest"]
    if all_periods:
        latest_period = max((p.stem for p in all_periods), key=_period_order)
        latest_fp = OUT_DIR / "latest.parquet"
        if latest_fp.exists() or latest_fp.is_symlink():
            latest_fp.unlink()
        latest_fp.symlink_to(f"{latest_period}.parquet", target_is_directory=False)
        print(f"latest → {latest_period}.parquet")

    # 更新 meta
    meta["stock_count"] = len(meta["stocks"])
    save_meta(meta)

    print(f"\n完成！共处理 {total_stocks} 条股票记录")
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
