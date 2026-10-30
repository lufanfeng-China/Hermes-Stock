"""Export one symbol's A/B/C/D regime history to Excel.

Three sheets: 阶段汇总 (segments), 逐日明细 (per-bar score + items), 判定标准
(the eight items and the four stages, read from the live constants).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.regime_history_store import DEFAULT_HISTORY, STAGE_LABELS, load_regime_series  # noqa: E402
from app.stage_regime import (  # noqa: E402
    BREAKOUT_MULT,
    D_MIN_BIAS20,
    D_MIN_BOX_POSITION,
    SCORE_STRONG,
    SELL_DAYS_MIN,
    SELL_WINDOW,
    STALL_VOL_SHRINK,
    VOL_LONG,
    VOL_SHORT,
    WINDOW,
)

OUTPUT_DIR = Path("/mnt/c/Users/Sky.Lu/Desktop/output")
FILLS = {"A": "E8EEF7", "B": "FFF4D6", "C": "E4F3E6", "D": "FBE3E3"}


def criteria_sheet() -> pd.DataFrame:
    rows = [
        ("窗口", f"最近 {WINDOW} 个交易日（约一个季度，覆盖 {VOL_LONG} 日均量线的完整循环）"),
        ("价格均线", "MA20：判断价格在短期资金生命线的上方还是下方"),
        ("均量线", f"5 日均量 / {VOL_LONG} 日均量：短期量能相对中期基准是扩张、休眠还是退潮"),
        ("价格结构", f"{WINDOW} 根最高价 / 最低价 / 中轨：界定价格运行的箱体与位置"),
        ("打分", f"6 项正向各 1 分，2 项扣分各 −1 分；得分 ≥{SCORE_STRONG} 才可能进 C"),
        ("", ""),
        ("条目 1 低点不创新低", "最近 20 日最低价 不低于 此前 40 日最低价（下跌股因最低点就在近期而不算筑底）"),
        ("条目 2 量能线上", f"5 日均量 > {VOL_LONG} 日均量，或当期为上穿（金叉）"),
        ("条目 3 红肥绿瘦", f"窗口内上涨日均量 > 下跌日均量（单边上涨无阴线时视为成立）"),
        ("条目 4 放量突破", f"收盘突破前 20 根最高价，且量能 ≥ {BREAKOUT_MULT} × 20 日均量（窗口内出现过即算）"),
        ("条目 5 缩量回踩守住", "最近一次突破后回落 ≥1%、未跌破突破位 2% 以上、且回踩期均量小于突破日"),
        ("条目 6 价在MA20上", "收盘价高于 MA20"),
        ("扣分 7 放量滞涨", f"收盘贴住 {WINDOW} 日高点但 5 日均量 < 20 日均量 × {STALL_VOL_SHRINK}"),
        ("扣分 8 抛售日密集", f"近 {SELL_WINDOW} 日「下跌且放量」≥ {SELL_DAYS_MIN} 次"),
        ("", ""),
        ("阶段 A", f"{STAGE_LABELS['A']}：其余情形；低点不再创新低→底部构筑，仍在创新低→下跌中继"),
        ("阶段 B", f"{STAGE_LABELS['B']}：放量突破后缩量回踩守住，且突破发生在最近 10 根内"),
        ("阶段 C", f"{STAGE_LABELS['C']}：得分 ≥{SCORE_STRONG}、收盘 > MA20、红肥绿瘦、无扣分项（或早前突破已确认）"),
        ("阶段 D", f"{STAGE_LABELS['D']}：有扣分项 且 箱体位置 ≥{D_MIN_BOX_POSITION:.0%} 或 MA20 乖离 ≥{D_MIN_BIAS20:.0%}"),
        ("优先级", "D > B（刚确认）> C > A"),
        ("数据基准", "前复权日线（通达信 export）；不含未来数据，每根 bar 只用当日及之前"),
    ]
    return pd.DataFrame(rows, columns=["项目", "口径"])


def build_segments(payload: dict) -> pd.DataFrame:
    rows = []
    for index, segment in enumerate(payload["segments"], start=1):
        last = next((row for row in payload["rows"] if row["trading_day"] == segment["end"]), {})
        hits = [key for key, hit in (last.get("items") or {}).items() if hit]
        penalties = [key for key, hit in (last.get("penalties") or {}).items() if hit]
        evidence = last.get("evidence") or {}
        rows.append({
            "序号": index, "开始日": segment["start"], "结束日": segment["end"],
            "交易日数": segment["trading_days"], "阶段": segment["stage"], "含义": segment["stage_label"],
            "段末得分": last.get("score"), "段末正向项": "、".join(hits) or "无",
            "段末扣分项": "、".join(penalties) or "无", "当前段": "是" if index == len(payload["segments"]) else "",
            "箱体下沿": evidence.get("box_low"), "箱体上沿": evidence.get("box_high"),
            "箱体位置": evidence.get("box_position"), "MA20": evidence.get("ma20"),
            "量能线5": evidence.get("vol_ma5"), "量能线60": evidence.get("vol_ma60"),
            "近15日抛售日": evidence.get("sell_days_15"),
        })
    return pd.DataFrame(rows)


def build_rows(payload: dict) -> pd.DataFrame:
    rows = []
    for row in payload["rows"]:
        evidence = row["evidence"]
        record = {"日期": row["trading_day"], "阶段": row["stage"], "含义": row["stage_label"],
                  "得分": row["score"], "判断说明": row["reason"]}
        record.update({key: "√" if hit else "" for key, hit in row["items"].items()})
        record.update({key: "扣分" if hit else "" for key, hit in row["penalties"].items()})
        record.update({"MA20": evidence["ma20"], "量能线5": evidence["vol_ma5"], "量能线60": evidence["vol_ma60"],
                       "箱体下沿": evidence["box_low"], "箱体上沿": evidence["box_high"],
                       "箱体位置": evidence["box_position"], "近15日抛售日": evidence["sell_days_15"]})
        rows.append(record)
    return pd.DataFrame(rows)


def style(workbook, sheet_name: str, stage_column: str | None) -> None:
    sheet = workbook[sheet_name]
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    for column in range(1, sheet.max_column + 1):
        width = max(len(str(sheet.cell(row=row, column=column).value or "")) for row in range(1, min(sheet.max_row, 60) + 1))
        sheet.column_dimensions[get_column_letter(column)].width = min(max(8, width + 2), 34)
    if stage_column:
        header = [cell.value for cell in sheet[1]]
        position = header.index(stage_column) + 1
        for row in range(2, sheet.max_row + 1):
            code = sheet.cell(row=row, column=position).value
            fill = FILLS.get(str(code))
            if fill:
                for column in range(1, sheet.max_column + 1):
                    sheet.cell(row=row, column=column).fill = PatternFill("solid", fgColor=fill)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a symbol's A/B/C/D regime history to Excel")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--bars", type=int, default=60)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    payload = load_regime_series(args.symbol, args.bars, path=args.history)
    segments = build_segments(payload)
    rows = build_rows(payload)
    criteria = criteria_sheet()

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    target = args.output or OUTPUT_DIR / f"{payload['symbol']}-阶段ABCD-{stamp}.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        segments.to_excel(writer, sheet_name="阶段汇总", index=False)
        rows.to_excel(writer, sheet_name="逐日明细", index=False)
        criteria.to_excel(writer, sheet_name="判定标准", index=False)
        style(writer.book, "阶段汇总", "阶段")
        style(writer.book, "逐日明细", "阶段")
        style(writer.book, "判定标准", None)

    print(f"file        : {target}")
    print(f"window      : {payload['window_start']} ~ {payload['as_of']} ({payload['bars']} bars)")
    print(f"segments    : {len(segments)} | current {payload['current']['stage_label']} ({payload['current']['trading_days']} 天)")
    print(f"size        : {os.path.getsize(target) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
