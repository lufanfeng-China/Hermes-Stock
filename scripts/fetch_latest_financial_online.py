#!/usr/bin/env python3
"""
fetch_latest_financial_online.py
================================
从新浪财经线上接口批量拉取最新财报，补充本地 Parquet 仓库的空白。

接口：新浪财经 CompanyFinanceService.getFinanceReport2022
  - source: fzb(资产负债表) / lrb(利润表) / llb(现金流量表)
  - 返回每期所有财务科目字段 + publish_date（公告日期）

工作流程：
  1. 识别候选股票（快照 latest_period == 2025Q3）
  2. 调用新浪三表接口获取最新已发布报告
  3. 将新报告写入 Parquet 仓库（按报告期追加）
  4. 重建快照

用法：
    # 预览：哪些股票可以线上补数据
    python3 scripts/fetch_latest_financial_online.py --dry-run --max 5

    # 批量拉取（真实请求）
    python3 scripts/fetch_latest_financial_online.py --batch --max 10

    # 全量运行（1728 只，耗时约 40 分钟）
    python3 scripts/fetch_latest_financial_online.py --batch

    # 单股票测试
    python3 scripts/fetch_latest_financial_online.py --test 002498
"""

import argparse
import json
import sys
import time
import random
import ssl
from pathlib import Path
from collections import defaultdict

# ── 全局配置 ────────────────────────────────────────────────────────────────
import requests  # noqa: E402

PROJECT = Path(__file__).parent.parent.resolve()
PARQUET_DIR = PROJECT / "data/derived/financial_ts/by_quarter"
SNAPSHOT_FILE = PROJECT / "data/derived/datasets/final/financial_snapshot_2026Q1.json"
PYTHON_TDX = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"

# 新浪 API（系统 Python3 可稳定访问）
BASE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
SOURCE_MAP = {"lrb": "利润表", "zcfz": "资产负债表", "llb": "现金流量表"}


def _make_session() -> requests.Session:
    """创建带重试的 requests session"""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    sess = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])
    )
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


# ── 工具函数 ────────────────────────────────────────────────────────────────
def normalize_code(code: str) -> str:
    """去掉 sh:/sz:/bj: 前缀"""
    code = str(code).strip()
    for p in ("sh:", "sz:", "bj:"):
        code = code.replace(p, "")
    return code.lstrip("0") or "0"


def build_sina_code(code: str) -> str:
    """纯数字 -> 新浪格式 sz002498 / sh600519"""
    c = normalize_code(code).zfill(6)
    if c.startswith("6") or c.startswith("5"):
        return f"sh{c}"
    elif c.startswith("92"):
        return f"bj{c}"
    else:
        return f"sz{c}"


def parse_period_from_date(report_date_str: str) -> str:
    """从 YYYYMMDD 解析报告期"""
    year = int(report_date_str[:4])
    month = int(report_date_str[4:6])
    if month == 3:
        return f"{year}Q1"
    if month == 6:
        return f"{year}Q2"
    if month == 9:
        return f"{year}Q3"
    if month == 12:
        return f"{year}A"
    q = (month - 1) // 3
    return f"{year}Q{q}" if 1 <= q <= 4 else f"{year}A"


def period_to_yyyymmdd(period: str) -> int:
    """2025A -> 20251231, 2025Q3 -> 20250930"""
    year = int(period[:4])
    if "A" in period:
        return year * 10000 + 1231
    q = int(period[-1])
    month_map = {1: 331, 2: 630, 3: 930}
    return year * 10000 + month_map.get(q, 1231)


def period_order(p: str) -> tuple:
    """报告期排序键"""
    year = int(p[:4])
    q = 5 if "A" in p else int(p[-1])
    return (year, q)


# ── 核心抓取 ────────────────────────────────────────────────────────────────
def fetch_three_tables(sina_code: str, timeout: int = 20) -> dict | None:
    """
    拉取某只股票三表全部历史报告期数据。
    返回: {
        "20260331": {
          "tables": {"lrb": [...], "zcfz": [...], "llb": [...]},
          "publish_date": "20260429"
        },
        ...
    }
    """
    import requests

    result = {}
    sess = _make_session()

    for src, name in SOURCE_MAP.items():
        params = {"paperCode": sina_code, "source": src, "type": "0", "page": "1", "num": "1000"}
        try:
            r = sess.get(BASE_URL, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            print(f"    [{name}] 请求失败: {e}")
            continue
        except Exception as e:
            print(f"    [{name}] 解析失败: {e}")
            continue

        try:
            rl = data.get("result", {}).get("data", {}).get("report_list", {})
            if not isinstance(rl, dict):
                continue
        except (TypeError, AttributeError):
            continue

        for date_str, entry in rl.items():
            if date_str == "report_date":
                continue
            period = parse_period_from_date(date_str)
            if period not in result:
                result[period] = {"tables": {}, "publish_date": ""}
            # 公告日期以第一个表为准
            if not result[period]["publish_date"]:
                result[period]["publish_date"] = entry.get("publish_date", "")
            result[period]["tables"][src] = entry.get("data", [])

        # 两次请求之间随机等待，避免频率限制
        time.sleep(random.uniform(0.2, 0.5))

    return result if result else None


def pick_latest_available(all_reports: dict) -> dict | None:
    """
    从所有报告中选择可用（有利润表）的最新报告期。
    lrb 是必需要的（包含营收、净利润等核心字段）。
    zcfz / llb 缺失时用空列表代替。
    """
    valid_periods = [
        p for p in all_reports
        if all_reports[p].get("tables", {}).get("lrb")
    ]
    if not valid_periods:
        return None

    latest = max(valid_periods, key=period_order)
    # 补全缺失的表为空列表
    for src in ("lrb", "zcfz", "llb"):
        all_reports[latest]["tables"].setdefault(src, [])
    all_reports[latest]["period"] = latest
    return all_reports[latest]


def flatten_tables_to_row(tables: dict, period: str) -> dict:
    """
    将三表字段拍平为一维字典。
    字段命名: lrb_xxx / zcfz_xxx / llb_xxx
    """
    report_date = period_to_yyyymmdd(period)

    # 从 publish_date 解析公告日期（格式: 20260429）
    announce_date = 0

    row = {
        "report_date": report_date,
        "announce_date": announce_date,
        "period": period,
    }

    for table_src, items in tables.items():
        for item in items:
            title = item.get("item_title", "")
            value = item.get("item_value")
            if title and value is not None:
                row[f"{table_src}_{title}"] = value

    return row


# ── Parquet 写入 ─────────────────────────────────────────────────────────────
def write_to_parquet(period: str, records: list[dict], code: str):
    """用 TDX Python 环境写入单条记录到 Parquet"""
    import subprocess

    fp = PARQUET_DIR / f"{period}.parquet"
    # 先从已有文件读取 announce_date 映射（如有）
    existing_announce = {}
    if fp.exists():
        import pyarrow.parquet as pq

        tbl = pq.read_table(str(fp))
        df = tbl.to_pandas().reset_index()
        if "announce_date" in df.columns:
            existing_announce = dict(zip(df["code"].astype(str), df["announce_date"].astype(int)))

    code_str = f"""
import pandas as pd
import pyarrow.parquet as pq

fp = "{fp}"
period = "{period}"
code = "{code}"

new_record = {records[0]}

# announce_date 处理：若为 0 则从现有文件继承
announce_dates = {existing_announce}
if new_record.get("announce_date", 0) == 0:
    new_record["announce_date"] = announce_dates.get(code, 0)

# 解析 period -> report_date
year = int(period[:4])
if "A" in period:
    new_record["report_date"] = year * 10000 + 1231
else:
    q = int(period[-1])
    month_map = {{1: 331, 2: 630, 3: 930}}
    new_record["report_date"] = year * 10000 + month_map.get(q, 1231)

new_df = pd.DataFrame([new_record])

if fp.exists():
    existing = pd.read_parquet(fp)
    # 如果该 code 已存在则更新
    if code in existing["code"].astype(str).values:
        existing = existing[existing["code"].astype(str) != code]
    combined = pd.concat([existing, new_df], ignore_index=False)
    combined.to_parquet(fp, index=False, engine="pyarrow", compression="snappy")
else:
    new_df.to_parquet(fp, index=False, engine="pyarrow", compression="snappy")

print(f"写入 {code} period={period} to {{fp.name}}")
"""

    result = subprocess.run([PYTHON_TDX, "-c", code_str], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Parquet 写入失败: {result.stderr[:200]}")
    else:
        print(f"  → {result.stdout.rstrip()}")


# ── 候选列表 ────────────────────────────────────────────────────────────────
def get_stale_stocks() -> list[tuple[str, str, str]]:
    """
    返回 (key, code, industry) 元组列表，最新期 = 2025Q3 的股票。
    key 格式: "sh:600519" / "sz:002498"
    """
    if not SNAPSHOT_FILE.exists():
        return []

    with open(SNAPSHOT_FILE, encoding="utf-8") as f:
        snap = json.load(f)

    result = []
    for key, entry in snap["scores"].items():
        if entry.get("latest_period") == "2025Q3":
            # key 格式为 "sh:600519" 或 "sz:002498"
            code = key.split(":")[1] if ":" in key else key
            ind2 = entry.get("industry_sw_level_2", "")
            result.append((key, code, ind2))

    return result


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    import requests  # 确保全局可用

    ap = argparse.ArgumentParser()
    ap.add_argument("--test", type=str, metavar="CODE", help="测试单只股票，如 002498")
    ap.add_argument("--batch", action="store_true", help="批量处理 latest_period=2025Q3 的股票")
    ap.add_argument("--codes-file", type=Path, metavar="F", help="每行一个 code 的文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印预览，不写 Parquet")
    ap.add_argument("--max", type=int, default=None, metavar="N", help="最多处理 N 只（调试）")
    ap.add_argument("--delay", type=float, default=0.6, metavar="SEC", help="请求间隔秒数")
    args = ap.parse_args()

    # ── 单股票测试 ──────────────────────────────────────────────────────────
    if args.test:
        code = normalize_code(args.test).zfill(6)
        sina_code = build_sina_code(code)
        print(f"测试 {code} ({sina_code}) ...")
        reports = fetch_three_tables(sina_code)
        if not reports:
            print("  无数据")
            return
        latest = pick_latest_available(reports)
        if not latest:
            print("  无有效报告")
            return
        print(f"  最新可用: {latest['period']} 公告 {latest['publish_date']}")
        row = flatten_tables_to_row(latest["tables"], latest["period"])
        row["code"] = code
        print(f"  字段数: {len(row)}")
        print(f"  lrb_净利润: {row.get('lrb_净利润')}")
        print(f"  zcfz_资产总计: {row.get('zcfz_资产总计')}")
        return

    # ── 候选列表 ────────────────────────────────────────────────────────────
    if args.codes_file:
        raw_codes = [l.strip() for l in args.codes_file.read_text().splitlines() if l.strip()]
        candidates = [(f"sz:{c}", c, "") for c in raw_codes]
    elif args.batch:
        candidates = get_stale_stocks()
        print(f"候选股票（latest_period=2025Q3）: {len(candidates)} 只")
    else:
        ap.print_help()
        return

    if args.max:
        candidates = candidates[: args.max]

    print(f"待处理: {len(candidates)} 只 | 间隔 {args.delay}s | {'DRY RUN' if args.dry_run else 'LIVE'}")

    # ── 批量拉取 ─────────────────────────────────────────────────────────────
    results_by_period = defaultdict(list)
    errors = []
    success = 0
    skipped_already_stale = 0

    for i, (key, code, ind2) in enumerate(candidates):
        sina_code = build_sina_code(code)
        display = f"[{i+1}/{len(candidates)}] {code}"

        try:
            reports = fetch_three_tables(sina_code)
        except Exception as e:
            print(f"{display}: 请求异常 {e}")
            errors.append(code)
            time.sleep(args.delay)
            continue

        if not reports:
            print(f"{display}: 线上无数据")
            errors.append(code)
            time.sleep(args.delay)
            continue

        latest = pick_latest_available(reports)
        if not latest:
            print(f"{display}: 线上无有效报告（2025Q3 跳过的无三表数据）")
            errors.append(code)
            time.sleep(args.delay)
            continue

        period = latest["period"]
        pub_date_str = latest.get("publish_date", "")

        # 换算 announce_date (YYYYMMDD -> int)
        try:
            announce_date = int(pub_date_str.replace("-", ""))
        except (ValueError, AttributeError):
            announce_date = 0

        # 已经是 2025Q3 且公告日期不超过本地已知日期，不处理
        if period == "2025Q3":
            skipped_already_stale += 1
            print(f"{display}: 线上最新仍是 {period}，跳过")
            time.sleep(args.delay)
            continue

        # 过滤：只接受 > 2025Q3
        if period_order(period) <= period_order("2025Q3"):
            print(f"{display}: 线上 period={period} <= 2025Q3，跳过")
            time.sleep(args.delay)
            continue

        row = flatten_tables_to_row(latest["tables"], period)
        row["code"] = code
        row["announce_date"] = announce_date

        results_by_period[period].append(row)
        success += 1
        print(
            f"{display}: {key.split(':')[0]} 最新={period} 公告={pub_date_str}"
            f" {'→ 写入' if not args.dry_run else '→ (dry-run)'}"
        )

        time.sleep(args.delay + random.uniform(0, 0.2))

    print()
    print(f"成功: {success} | 失败: {len(errors)} | 跳过(stale): {skipped_already_stale} | 总: {len(candidates)}")

    if errors:
        print(f"失败: {errors[:20]}{'...' if len(errors) > 20 else ''}")

    if args.dry_run:
        print("\n[DRY RUN] 不写入 Parquet")
        return

    if not results_by_period:
        print("无新数据")
        return

    # ── 写入 Parquet ──────────────────────────────────────────────────────────
    print("\n=== 写入 Parquet ===")
    total_new = 0
    for period, records in sorted(results_by_period.items(), key=lambda x: period_order(x[0])):
        print(f"  {period}: {len(records)} 条")
        for rec in records:
            write_to_parquet(period, [rec], rec["code"])
            total_new += 1

    print(f"总计写入 {total_new} 条记录")

    # ── 重建快照 ──────────────────────────────────────────────────────────────
    if success > 0:
        latest_period = max(results_by_period.keys(), key=period_order)
        print(f"\n=== 重建快照: {latest_period} ===")
        import subprocess

        result = subprocess.run(
            [PYTHON_TDX, str(PROJECT / "scripts/build_financial_snapshot_from_warehouse.py"), latest_period],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(result.stdout[-500:] if result.stdout else "快照重建成功")
        else:
            print(f"快照重建失败: {result.stderr[-300:]}")


if __name__ == "__main__":
    main()
