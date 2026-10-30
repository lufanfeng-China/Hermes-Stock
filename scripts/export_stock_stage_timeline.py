"""Export one symbol's lifecycle-stage history to Excel.

Every row is produced by re-running the scalar classifier on the bars up to and
including that day, so the sheet shows exactly the evidence and the reason text
the API/UI would report — no separate re-implementation of the rules.

Usage:
  ~/.venvs/moontdx-china-stock-data/bin/python scripts/export_stock_stage_timeline.py \
      --symbol 600309 --months 12 --output /mnt/c/Users/Sky.Lu/Desktop/output/600309-stage.xlsx
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.stage_classify import (  # noqa: E402
    BASE_MAX_RANGE_POS,
    BIAS_CLIMAX,
    EVENT_STAGES,
    FLAT_SLOPE,
    MIN_DAYS,
    TOP_MAX_DIST_FROM_HIGH,
    VOL_BREAKOUT,
    classify_stage,
    prepare_bars,
)
from app.tdx.qfq_kline import load_tdx_qfq_daily  # noqa: E402

FINAL = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
HISTORY = FINAL / "stage_history.parquet"

REGION_FILL = {
    "上涨": "1F7A5A", "底部": "3F5C63", "顶部": "8A6A1F", "下跌": "8A2F2F",
}
REGION_NAMES = {"up": "上升区", "base": "底部区", "top": "顶部区", "down": "下跌区"}

EVIDENCE_FIELDS = [
    ("close", "收盘价"), ("ma5", "MA5"), ("ma10", "MA10"), ("ma20", "MA20"), ("ma60", "MA60"),
    ("slope20", "MA20五日斜率"), ("slope60", "MA60十日斜率"), ("bias20", "MA20乖离率"),
    ("range_pos_60", "60日区间位置"), ("pos_high_60", "距60日高点"), ("vol_ratio", "量比(前5日)"),
]


def classify_window(symbol: str, months: int) -> tuple[pd.DataFrame, str, str]:
    """Return per-bar rows for the last `months` of one symbol."""
    bars = prepare_bars(load_tdx_qfq_daily(symbol))
    if len(bars) < MIN_DAYS:
        raise SystemExit(f"{symbol}: only {len(bars)} usable bars, need >= {MIN_DAYS}")

    as_of = bars.index[-1]
    window_start = as_of - pd.DateOffset(months=months)
    records: list[dict[str, object]] = []
    for position in range(len(bars)):
        stamp = bars.index[position]
        if stamp < window_start:
            continue
        result = classify_stage(bars.iloc[: position + 1])
        if result.get("status") != "ok":
            continue
        evidence = result["evidence"]
        records.append({
            "trading_day": stamp.strftime("%Y-%m-%d"),
            "close": float(bars["close"].iloc[position]),
            "region": result["region"],
            "region_label": result["region_label"],
            "stage": result["stage"],
            "stage_label": result["stage_label"],
            "is_event": bool(result["is_event"]),
            "detail": result["detail"],
            "ma5": evidence["ma5"], "ma10": evidence["ma10"],
            "ma20": evidence["ma20"], "ma60": evidence["ma60"],
            "slope20": evidence["slope20"], "slope60": evidence["slope60"],
            "bias20": evidence["bias20"],
            "range_pos_60": evidence["range_pos_60"],
            "pos_high_60": evidence["pos_high_60"],
            "vol_ratio": evidence["vol_ratio"],
        })
    frame = pd.DataFrame(records)
    if frame.empty:
        raise SystemExit(f"{symbol}: no bars inside the last {months} months")
    return frame, as_of.strftime("%Y-%m-%d"), str(frame["trading_day"].iloc[0])


def cross_check(symbol: str, frame: pd.DataFrame) -> tuple[int, list[str]]:
    """Compare recomputed stages with the published history library."""
    if not HISTORY.exists():
        return -1, ["历史库不存在，跳过对拍"]
    code = str(symbol).zfill(6)
    published = pd.read_parquet(HISTORY, columns=["symbol", "trading_day", "stage"],
                                filters=[("symbol", "==", code)])
    if published.empty:
        return -1, [f"历史库里没有 {code} 的行，跳过对拍"]
    merged = frame.merge(published.rename(columns={"stage": "published_stage"}),
                         on="trading_day", how="inner")
    mismatches = merged[merged["stage"] != merged["published_stage"]]
    rows = [f"{r.trading_day}: 本次 {r.stage} vs 库内 {r.published_stage}" for r in mismatches.itertuples()]
    return len(mismatches), rows


def build_segments(frame: pd.DataFrame) -> pd.DataFrame:
    segments: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        if segments and segments[-1]["阶段代码"] == row.stage:
            current = segments[-1]
            current["结束日"] = row.trading_day
            current["交易日数"] = int(current["交易日数"]) + 1
            current["段末判断说明"] = row.detail
            explanations = current["段内判断说明"]
            if isinstance(explanations, list) and row.detail not in explanations:
                explanations.append(row.detail)
            for field, _ in EVIDENCE_FIELDS:
                current[f"段末{field}"] = getattr(row, field)
        else:
            item = {
                "序号": len(segments) + 1,
                "开始日": row.trading_day,
                "结束日": row.trading_day,
                "交易日数": 1,
                "区域": row.region_label,
                "阶段": row.stage_label,
                "阶段代码": row.stage,
                "事件型": "是" if row.is_event else "",
                "起始判断说明": row.detail,
                "段末判断说明": row.detail,
                "段内判断说明": [row.detail],
            }
            for field, _ in EVIDENCE_FIELDS:
                item[f"段末{field}"] = getattr(row, field)
            segments.append(item)

    out = pd.DataFrame(segments)
    out["段内判断说明"] = out["段内判断说明"].apply(lambda items: "\n".join(dict.fromkeys(items)))
    out["段末距60日高点"] = out["段末pos_high_60"].map(lambda value: f"{value * 100:.1f}%")
    out["段末MA20乖离"] = out["段末bias20"].map(lambda value: f"{value * 100:.1f}%")
    out["段末MA60斜率"] = out["段末slope60"].map(lambda value: f"{value * 100:.2f}%")
    out["段末区间位置"] = out["段末range_pos_60"].map(lambda value: f"{value * 100:.0f}%")
    out = out.rename(columns={"段末close": "段末收盘价", "段末vol_ratio": "段末量比(前5日)"})
    columns = ["序号", "开始日", "结束日", "交易日数", "区域", "阶段", "阶段代码", "事件型",
               "起始判断说明", "段末判断说明", "段内判断说明",
               "段末收盘价", "段末ma5", "段末ma10", "段末ma20", "段末ma60",
               "段末区间位置", "段末距60日高点", "段末MA60斜率", "段末MA20乖离", "段末量比(前5日)"]
    return out[columns]


def criteria_sheet(symbol: str, as_of: str, window_start: str, bars: int) -> pd.DataFrame:
    rows = [
        ("标的", f"{symbol}（前复权日线，TDX export）"),
        ("区间", f"{window_start} ~ {as_of}，共 {bars} 个交易日"),
        ("判定口径", "逐日只用当日及以前的 bar（无未来数据）；0 价停牌占位行先剔除"),
        ("阶段数", "11 个阶段 / 4 个区域；B2、D1 为事件型状态"),
        ("", ""),
        ("【阈值】", ""),
        ("FLAT_SLOPE", f"{FLAT_SLOPE:.3f}（0.5%），斜率绝对值小于它算走平"),
        ("BIAS_CLIMAX", f"{BIAS_CLIMAX:.2f}（18%），MA20 乖离达到即加速赶顶"),
        ("VOL_BREAKOUT", f"{VOL_BREAKOUT:.1f}，当日量 / 前 5 日均量（不含当日）"),
        ("MIN_DAYS", f"{MIN_DAYS}，最少可用交易日"),
        ("BASE_MAX_RANGE_POS", f"{BASE_MAX_RANGE_POS:.2f}，底部区只收 60 日区间下半"),
        ("TOP_MAX_DIST_FROM_HIGH", f"{TOP_MAX_DIST_FROM_HIGH:.2f}（10%），顶部区只收距高点 10% 内"),
        ("", ""),
        ("【变量】", ""),
        ("MA5/10/20/60", "收盘价简单移动平均"),
        ("slope60", "(MA60 − 10 个交易日前 MA60) ÷ 10 个交易日前 MA60"),
        ("slope20", "(MA20 − 5 个交易日前 MA20) ÷ 5 个交易日前 MA20"),
        ("slope20_prev", "5 个交易日前那一刻的 slope20，用于判断“刚拐头”"),
        ("high_60 / low_60", "最近 60 根的最高价最大 / 最低价最小"),
        ("mid_60", "(high_60 + low_60) ÷ 2"),
        ("range_pos", "(收盘 − low_60) ÷ (high_60 − low_60)，60 日区间位置"),
        ("pos_high", "(收盘 − high_60) ÷ high_60"),
        ("bias20", "(收盘 − MA20) ÷ MA20"),
        ("vol_ratio", "当日成交量 ÷ 前 5 日平均成交量（不含当日）"),
        ("", ""),
        ("【判定顺序 1：事件型状态优先】", ""),
        ("B2 探底回升", "收盘 > MA20 且 量比 ≥ 1.5 且 slope20 > 0 → 强制归底部区"),
        ("B3 回踩确认", "low_20 > low_60 且 high_20 > MA20 且 收盘 < MA20 且 slope60 ≤ 0.5% → 强制归底部区"),
        ("", ""),
        ("【判定顺序 2：区域】", ""),
        ("slope60 > +0.5%", "收盘 > MA60 → 上升区；否则 range_pos > 0.50 → 上升区（趋势回抽）；否则 → 底部区"),
        ("slope60 < −0.5%", "收盘 < MA60 → 下跌区；否则 pos_high < −10% → 下跌区；否则 → 顶部区"),
        ("|slope60| ≤ 0.5%", "slope20 > +0.5% 且 收盘 > MA60 → 上升区；slope20 < −0.5% 且 收盘 < MA60 → 下跌区；否则 收盘 < mid_60 → 底部区，反之顶部区"),
        ("", ""),
        ("【判定顺序 3：阶段】", ""),
        ("D3 下跌中继", "下跌区内 MA5 > MA10（短期反弹）"),
        ("D1 破位下跌", "下跌区内 slope20 < 0 且 slope20_prev ≥ 0（MA20 刚拐头向下）"),
        ("D2 主跌", "下跌区其余情形"),
        ("B1 底部盘整", "底部区默认状态"),
        ("U4 加速赶顶", "上升区内 bias20 ≥ 18%"),
        ("U3 上升中继", "上升区内 MA5 < MA10；或 上升区内收盘 ≤ MA20（两条入口）"),
        ("U1 上升初期", "上升区内 slope20 > 0 且 11 个交易日前收盘 ≤ 当时 MA60（刚站上 MA60）"),
        ("U2 主升", "上升区其余：收盘 > MA20 且 MA5 ≥ MA10 且 乖离 < 18% 且 非刚站上 MA60"),
        ("T1 高位震荡", "顶部区默认状态（含 MA60 走平时区间中上部的少量样本）"),
        ("", ""),
        ("【事件型】", "B2、D1 只反映当天动作；全市场实测平均持续 1.51 / 2.79 个交易日，不宜作为持仓状态"),
    ]
    return pd.DataFrame(rows, columns=["项目", "说明"])


def style_workbook(path: Path, segments: pd.DataFrame, detail: pd.DataFrame) -> None:
    from openpyxl import load_workbook

    workbook = load_workbook(path)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1B3A46")

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for index, column in enumerate(sheet.iter_cols(min_row=1, max_row=1), start=1):
            width = max(12, min(48, int(len(str(column[0].value or "")) * 2.4)))
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.row_dimensions[1].height = 30

    summary = workbook["阶段汇总"]
    summary.column_dimensions["I"].width = 46
    summary.column_dimensions["J"].width = 46
    summary.column_dimensions["K"].width = 60
    region_column = 5
    event_column = 8
    for row_index in range(2, summary.max_row + 1):
        region_label = str(summary.cell(row=row_index, column=region_column).value or "")
        fill_key = "上涨" if region_label.startswith("上升") else (
            "底部" if region_label.startswith("底部") else (
                "顶部" if region_label.startswith("顶部") else "下跌"))
        summary.cell(row=row_index, column=region_column).fill = PatternFill(
            "solid", fgColor=REGION_FILL[fill_key])
        summary.cell(row=row_index, column=region_column).font = Font(color="FFFFFF", bold=True)
        if summary.cell(row=row_index, column=event_column).value == "是":
            for column in range(1, summary.max_column + 1):
                summary.cell(row=row_index, column=column).fill = PatternFill("solid", fgColor="3A2E14")
        for column in (9, 10, 11):
            summary.cell(row=row_index, column=column).alignment = Alignment(wrap_text=True, vertical="top")

    detail_sheet = workbook["逐日明细"]
    detail_sheet.column_dimensions[get_column_letter(detail_sheet.max_column)].width = 52
    for row_index in range(2, detail_sheet.max_row + 1):
        detail_sheet.cell(row=row_index, column=detail_sheet.max_column).alignment = Alignment(
            wrap_text=True, vertical="top")

    criteria = workbook["判定标准"]
    criteria.column_dimensions["A"].width = 26
    criteria.column_dimensions["B"].width = 96
    for row_index in range(2, criteria.max_row + 1):
        criteria.cell(row=row_index, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        if criteria.cell(row=row_index, column=1).value and str(
                criteria.cell(row=row_index, column=1).value).startswith("【"):
            criteria.cell(row=row_index, column=1).font = Font(bold=True, color="7CE0C3")

    workbook.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a symbol's stage timeline to Excel")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    frame, as_of, window_start = classify_window(args.symbol, args.months)
    segments = build_segments(frame)
    mismatches, notes = cross_check(args.symbol, frame)

    frame_out = frame.rename(columns={
        "trading_day": "日期", "region_label": "区域", "stage_label": "阶段", "stage": "阶段代码",
        "is_event": "事件型", "detail": "判断说明", "close": "收盘价", "vol_ratio": "量比(前5日)",
        "range_pos_60": "60日区间位置", "pos_high_60": "距60日高点",
        "slope20": "MA20五日斜率", "slope60": "MA60十日斜率", "bias20": "MA20乖离率",
    })
    frame_out["事件型"] = frame_out["事件型"].map(lambda value: "是" if value else "")
    frame_out = frame_out[[
        "日期", "收盘价", "区域", "阶段", "阶段代码", "事件型", "判断说明",
        "ma5", "ma10", "ma20", "ma60", "MA20五日斜率", "MA60十日斜率",
        "MA20乖离率", "60日区间位置", "距60日高点", "量比(前5日)",
    ]]

    output = Path(args.output) if args.output else (
        Path("/mnt/c/Users/Sky.Lu/Desktop/output")
        / f"{args.symbol}-阶段历史-{datetime.now():%Y%m%d-%H%M}.xlsx")
    output.parent.mkdir(parents=True, exist_ok=True)

    criteria = criteria_sheet(args.symbol, as_of, window_start, len(frame))
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        segments.to_excel(writer, sheet_name="阶段汇总", index=False)
        frame_out.to_excel(writer, sheet_name="逐日明细", index=False)
        criteria.to_excel(writer, sheet_name="判定标准", index=False)
    style_workbook(output, segments, frame_out)

    print(f"file        : {output}")
    print(f"window      : {window_start} ~ {as_of} ({len(frame)} bars)")
    print(f"segments    : {len(segments)} (event segments: {int((segments['事件型'] == '是').sum())})")
    print(f"sheets      : 阶段汇总 / 逐日明细 / 判定标准")
    if mismatches >= 0:
        print(f"cross-check : {mismatches} mismatches vs published history")
        for note in notes[:5]:
            print("  ", note)


if __name__ == "__main__":
    main()
