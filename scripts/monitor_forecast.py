#!/usr/bin/env python3
"""业绩预告监控脚本
每日运行，读取通达信最新财报文件中的业绩预告数据，
与昨日快照对比，发现新增预告并输出到桌面。
"""
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

import pandas as pd
from mootdx.financial.financial import FinancialReader
from mootdx.quotes import Quotes

# ========== 配置 ==========
TDX_DIR = "/mnt/c/new_tdx64"
PROJECT_DIR = Path("/home/lufanfeng/Project-Hermes-Stock")
SNAPSHOT_DIR = PROJECT_DIR / "data/derived/financial_ts/forecast_snapshots"
DESKTOP_DIR = Path("/mnt/c/Users/Sky.Lu/Desktop/output")
OUTPUT_FILE = DESKTOP_DIR / "业绩预告_新增.txt"

# TDX 财务数据字段
FCAST_DATE_COL = "业绩预告公告日期 "
FCAST_FIELDS = [
    "业绩预告公告日期 ",
    "业绩预告-本期净利润同比增幅下限%",
    "业绩预告-本期净利润同比增幅上限%",
    "业绩预告-本期净利润下限(万元)",
    "业绩预告-本期净利润上限(万元)",
]
# 补充字段（用于判断报告期归属）
EXTRA_FIELDS = [
    "财报公告日期",
    "净利润增长率(%)",
]


def get_stock_names() -> dict:
    """从 TDX 在线 API 获取股票代码→名称映射"""
    client = Quotes.factory(market="std")
    names = {}

    # SZ: 深圳个股 (000-004, 300-301)
    try:
        df_sz = client.stocks(market=0)
        mask = df_sz["code"].astype(str).str.match(r"^(00[0-4]|30[01])\d{3}$")
        for _, row in df_sz[mask].iterrows():
            code = str(row["code"])
            name = str(row["name"]).strip().replace("\x00", "")
            names[code] = name
    except Exception as e:
        print(f"  ⚠ 获取深圳股票列表失败: {e}", file=sys.stderr)

    # SH: 上海个股 (600-609, 688-689)
    try:
        df_sh = client.stocks(market=1)
        mask = df_sh["code"].astype(str).str.match(r"^(6[0-9]{2}|68[89])\d{3}$")
        for _, row in df_sh[mask].iterrows():
            code = str(row["code"])
            name = str(row["name"]).strip().replace("\x00", "")
            # 不覆盖（同代码优先保留 SZ 的结果）
            if code not in names:
                names[code] = name
    except Exception as e:
        print(f"  ⚠ 获取上海股票列表失败: {e}", file=sys.stderr)

    return names


def find_latest_cw_file() -> Path | None:
    """找到最新的非空 gpcw*.zip 文件"""
    cw_dir = Path(TDX_DIR) / "vipdoc" / "cw"
    # 按文件名倒序（较新的在前面），取非空的
    files = sorted(cw_dir.glob("gpcw*.zip"), reverse=True)
    for fp in files:
        if fp.stat().st_size > 1000:  # 跳过占位包(~164 bytes)
            return fp
    return None


def extract_forecasts(cw_file: Path, names: dict) -> pd.DataFrame:
    """从 gpcw*.zip 中提取业绩预告数据"""
    df = FinancialReader.to_data(str(cw_file))

    if df.empty or FCAST_DATE_COL not in df.columns:
        return pd.DataFrame()

    # 筛选有预告日期的行
    has_fcast = df[FCAST_DATE_COL].notna() & (df[FCAST_DATE_COL] != 0)
    fcast_df = df.loc[has_fcast].copy()

    if fcast_df.empty:
        return pd.DataFrame()

    # 提取需要的列
    cols = FCAST_FIELDS + EXTRA_FIELDS
    available = [c for c in cols if c in fcast_df.columns]
    result = fcast_df[available].copy()

    # 添加股票名称
    result["name"] = result.index.map(lambda c: names.get(c, ""))
    result.index.name = "code"

    # 转换日期格式
    result["预告日期"] = result[FCAST_DATE_COL].apply(
        lambda x: f"{int(x)//10000}-{(int(x)%10000)//100:02d}-{int(x)%100:02d}"
        if pd.notna(x) and x != 0 else ""
    )

    # 转换 财报公告日期
    if "财报公告日期" in result.columns:
        result["财报公告日"] = result["财报公告日期"].apply(
            lambda x: f"{int(x)//10000}-{(int(x)%10000)//100:02d}-{int(x)%100:02d}"
            if pd.notna(x) and x != 0 else ""
        )

    return result


def load_snapshot() -> pd.DataFrame:
    """加载最近一次快照"""
    snapshots = sorted(SNAPSHOT_DIR.glob("forecast_*.parquet"))
    if not snapshots:
        return pd.DataFrame()
    return pd.read_parquet(snapshots[-1])


def save_snapshot(df: pd.DataFrame):
    """保存今日快照"""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = SNAPSHOT_DIR / f"forecast_{today}.parquet"
    df.to_parquet(path, index=True)
    print(f"快照已保存: {path}")
    return path


def detect_new(
    current: pd.DataFrame, previous: pd.DataFrame
) -> pd.DataFrame:
    """对比两份快照，发现新增的预告"""
    if previous.empty:
        return current  # 首次运行，全量

    prev_codes = set(previous.index)
    curr_codes = set(current.index)

    new_codes = curr_codes - prev_codes

    if not new_codes:
        return pd.DataFrame()

    new_df = current.loc[list(new_codes)].copy()

    # 按预告日期降序排列
    if FCAST_DATE_COL in new_df.columns:
        new_df = new_df.sort_values(FCAST_DATE_COL, ascending=False)

    return new_df


def format_output(new_df: pd.DataFrame, cw_file: Path) -> str:
    """格式化输出到文本"""
    lines = []
    today_str = date.today().isoformat()

    # 提取报告期
    period = cw_file.stem.replace("gpcw", "")
    year = period[:4]
    q = period[4:]
    if q == "0331":
        period_label = f"{year}Q1"
    elif q == "0630":
        period_label = f"{year}Q2 (半年报)"
    elif q == "0930":
        period_label = f"{year}Q3"
    elif q == "1231":
        period_label = f"{year}年报"
    else:
        period_label = period

    lines.append(f"{'='*60}")
    lines.append(f"📊 业绩预告新增 | {today_str} | 数据文件: {period_label}")
    lines.append(f"{'='*60}")

    # 判断预告对应报告期
    total_new = len(new_df)
    # 根据预告日期判断 —— Q1截止4/30，半年报截止7/15
    h1_count = 0
    q1_count = 0
    for _, row in new_df.iterrows():
        dt_val = row.get(FCAST_DATE_COL, 0)
        if pd.notna(dt_val) and dt_val != 0:
            m = (int(dt_val) % 10000) // 100
            if m >= 5:
                h1_count += 1
            else:
                q1_count += 1

    if h1_count > 0:
        lines.append(f"其中半年报(H1)预告: {h1_count} 只")
    if q1_count > 0:
        lines.append(f"其中Q1预告: {q1_count} 只")
    lines.append(f"共新增 {total_new} 只\n")

    for code, row in new_df.iterrows():
        name = row.get("name", "")
        fcast_date = row.get("预告日期", "")
        lo_pct = row.get("业绩预告-本期净利润同比增幅下限%", "")
        hi_pct = row.get("业绩预告-本期净利润同比增幅上限%", "")
        lo_amt = row.get("业绩预告-本期净利润下限(万元)", "")
        hi_amt = row.get("业绩预告-本期净利润上限(万元)", "")

        # 格式化净利
        def fmt_amt(v):
            if pd.isna(v) or v == 0:
                return "—"
            v = float(v)
            if abs(v) >= 10000:
                return f"{v/10000:.1f}亿"
            return f"{v:.0f}万"

        lo_amt_str = fmt_amt(lo_amt)
        hi_amt_str = fmt_amt(hi_amt)

        # 格式化增幅
        def fmt_pct(v):
            if pd.isna(v) or v == 0:
                return "—"
            v = float(v)
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:.1f}%"

        lo_pct_str = fmt_pct(lo_pct)
        hi_pct_str = fmt_pct(hi_pct)

        lines.append(f"{code} {name}")
        lines.append(f"  预告日: {fcast_date}")
        lines.append(f"  净利增幅: {lo_pct_str} ~ {hi_pct_str}")
        lines.append(f"  预告净利: {lo_amt_str} ~ {hi_amt_str}")
        lines.append("")

    return "\n".join(lines)


def main():
    print(f"=== 业绩预告监控 {date.today().isoformat()} ===")

    # 1. 获取股票名称
    print("[1/5] 获取股票名称...")
    names = get_stock_names()
    print(f"  已获取 {len(names)} 只股票名称")

    # 2. 找到最新财务文件
    print("[2/5] 定位最新财务数据文件...")
    cw_file = find_latest_cw_file()
    if not cw_file:
        print("  ❌ 未找到非空 gpcw*.zip 文件", file=sys.stderr)
        sys.exit(1)
    print(f"  使用文件: {cw_file.name}")

    # 3. 提取预告数据
    print("[3/5] 提取业绩预告数据...")
    current = extract_forecasts(cw_file, names)
    print(f"  当前共有 {len(current)} 只股票有业绩预告")

    if current.empty:
        print("  无预告数据，跳过")
        return

    # 4. 对比昨日快照
    print("[4/5] 对比昨日快照...")
    previous = load_snapshot()
    print(f"  昨日快照: {len(previous)} 条")

    new_forecasts = detect_new(current, previous)
    print(f"  新增预告: {len(new_forecasts)} 只")

    # 5. 保存今日快照
    print("[5/5] 保存今日快照...")
    save_snapshot(current)

    # 6. 输出新增到桌面
    if not new_forecasts.empty:
        DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
        output_text = format_output(new_forecasts, cw_file)
        OUTPUT_FILE.write_text(output_text, encoding="utf-8")
        print(f"  ✅ 新增预告已输出到: {OUTPUT_FILE}")
        print(f"\n{'='*60}")
        print(output_text)
    else:
        print("  ✅ 无新增预告")

    print(f"\n完成。下次运行将对比今日快照。")


if __name__ == "__main__":
    main()
