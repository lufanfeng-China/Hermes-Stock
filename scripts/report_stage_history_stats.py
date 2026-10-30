#!/usr/bin/env python3
"""Descriptive statistics for the lifecycle-stage history.

Answers three questions about the classifier, using only the stage history plus
front-adjusted closes:

1. How long does each stage last (bars), and does it behave like a *stage*
   (slow-moving) rather than a noisy label?
2. What does each stage transition into next (row-normalised matrix)?
3. Do stages separate forward 5/20-bar returns at all?  This is a discriminative
   check, **not** a strategy: no costs, no execution rules, no position sizing.

Deliberately separated from the build: forward returns are future information and
must never live in the feature parquet.

Usage:
    ~/.venvs/moontdx-china-stock-data/bin/python scripts/report_stage_history_stats.py
    ... --limit 500 --no-forward
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.stage_classify import _STAGE_LABELS  # noqa: E402
from app.tdx.qfq_kline import load_tdx_qfq_daily  # noqa: E402

FINAL = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
DEFAULT_HISTORY = FINAL / "stage_history.parquet"
DEFAULT_REPORT_DIR = Path("/mnt/c/Users/Sky.Lu/Desktop/output")
# R1/R2 added 2026-10-30 with the 13-state revision; keep this list in sync with
# app.stage_classify._STAGE_LABELS or the report silently drops stages.
STAGE_ORDER = ["D1", "D2", "D3", "B1", "B2", "B3", "R1", "R2", "U1", "U2", "U3", "U4", "T1"]
FORWARD_WINDOWS = (5, 20)


def stage_durations(history: pd.DataFrame) -> pd.DataFrame:
    """Run lengths of identical consecutive stage labels, per stock."""
    frame = history.sort_values(["market", "symbol", "trading_day"])
    same = frame.groupby(["market", "symbol"])["stage"].transform("shift") == frame["stage"]
    new_run = (~same).astype(int)
    frame = frame.assign(run_id=new_run.groupby([frame["market"], frame["symbol"]]).cumsum())
    runs = frame.groupby(["market", "symbol", "stage", "run_id"]).size().reset_index(name="bars")
    summary = runs.groupby("stage")["bars"].agg(
        runs="count", mean_bars="mean", median_bars="median",
        p25=lambda values: values.quantile(0.25), p75=lambda values: values.quantile(0.75),
        max_bars="max",
    ).reindex(STAGE_ORDER)
    summary["mean_bars"] = summary["mean_bars"].round(2)
    summary["median_bars"] = summary["median_bars"].round(1)
    summary["p25"] = summary["p25"].round(1)
    summary["p75"] = summary["p75"].round(1)
    return summary


def transition_matrix(history: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Counts and row-normalised transitions between consecutive bars of a stock."""
    frame = history.sort_values(["market", "symbol", "trading_day"])
    nxt = frame.groupby(["market", "symbol"])["stage"].shift(-1)
    pairs = pd.DataFrame({"from": frame["stage"], "to": nxt}).dropna()
    counts = pd.crosstab(pairs["from"], pairs["to"]).reindex(index=STAGE_ORDER, columns=STAGE_ORDER).fillna(0)
    shares = counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0)
    return counts.astype(int), shares


def forward_returns(history: pd.DataFrame, limit: int = 0) -> pd.DataFrame:
    """Join QFQ closes and compute forward 5/20-bar returns per stage row."""
    rows: list[pd.DataFrame] = []
    groups = list(history.groupby(["market", "symbol"], sort=False))
    if limit:
        groups = groups[:limit]

    for (market, symbol), group in groups:
        try:
            bars = load_tdx_qfq_daily(symbol)
        except Exception:  # noqa: BLE001 - missing export
            continue
        closes = bars["close"].astype(float)
        # suspended placeholder rows carry 0.00 prices; using them as a denominator
        # produces inf returns and poisons the mean
        closes = closes.where(closes > 0)
        result = pd.DataFrame({"close": closes.to_numpy()},
                              index=bars.index.strftime("%Y-%m-%d"))
        for window in FORWARD_WINDOWS:
            result[f"fwd_{window}"] = closes.shift(-window).div(closes).sub(1.0).to_numpy()
        merged = group.set_index("trading_day")[["stage"]].join(result, how="inner")
        if not merged.empty:
            rows.append(merged.reset_index(drop=True))

    if not rows:
        return pd.DataFrame(columns=["stage"] + [f"fwd_{w}" for w in FORWARD_WINDOWS])

    return pd.concat(rows, ignore_index=True)


def summarise_forward(combined: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for stage in STAGE_ORDER:
        subset = combined[combined["stage"] == stage]
        record = {"stage": stage, "bars": int(len(subset))}
        for window in FORWARD_WINDOWS:
            values = subset[f"fwd_{window}"].replace([np.inf, -np.inf], np.nan).dropna()
            record[f"fwd_{window}_mean_pct"] = round(float(values.mean()) * 100, 3) if len(values) else np.nan
            record[f"fwd_{window}_median_pct"] = round(float(values.median()) * 100, 3) if len(values) else np.nan
            record[f"fwd_{window}_win_rate_pct"] = round(float((values > 0).mean()) * 100, 2) if len(values) else np.nan
        rows.append(record)
    overall: dict[str, object] = {"stage": "ALL", "bars": int(len(combined))}
    for window in FORWARD_WINDOWS:
        values = combined[f"fwd_{window}"].dropna()
        overall[f"fwd_{window}_mean_pct"] = round(float(values.mean()) * 100, 3) if len(values) else np.nan
        overall[f"fwd_{window}_median_pct"] = round(float(values.median()) * 100, 3) if len(values) else np.nan
        overall[f"fwd_{window}_win_rate_pct"] = round(float((values > 0).mean()) * 100, 2) if len(values) else np.nan
    return pd.DataFrame(rows + [overall])


def render_markdown(manifest: dict, durations: pd.DataFrame, shares: pd.DataFrame,
                    forward: pd.DataFrame | None, built_at: str) -> str:
    lines: list[str] = []
    lines.append("# 生命周期阶段历史 — 描述性统计")
    lines.append("")
    lines.append(f"生成时间：{built_at}")
    if manifest:
        lines.append(f"数据：{manifest.get('parquet')}｜{manifest.get('rows'):,} 行｜"
                     f"{manifest.get('date_range', {}).get('first')} .. {manifest.get('date_range', {}).get('last')}")
        lines.append(f"口径：{manifest.get('price_basis')}（通达信前复权导出）｜无未来数据（forward returns 不落库）")
    lines.append("")
    lines.append("## 1. 各阶段持续天数（同一股票连续同类标签算一段）")
    lines.append("")
    lines.append("| 阶段 | 名称 | 段数 | 均值(bar) | 中位数(bar) | P25 | P75 | 最长 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for stage, row in durations.iterrows():
        lines.append(f"| {stage} | {_STAGE_LABELS.get(stage, '')} | {int(row['runs'])} | {row['mean_bars']} | "
                     f"{row['median_bars']} | {row['p25']} | {row['p75']} | {int(row['max_bars'])} |")
    lines.append("")
    lines.append("## 2. 阶段转换矩阵（行归一化，%）= 下一交易日进入该阶段的比例")
    lines.append("")
    header = "| 从 \\ 到 | " + " | ".join(STAGE_ORDER) + " |"
    lines.append(header)
    lines.append("|---|" + "---:|" * len(STAGE_ORDER))
    for stage in STAGE_ORDER:
        row = shares.loc[stage]
        cells = " | ".join("—" if pd.isna(value) else f"{value * 100:.1f}" for value in row)
        lines.append(f"| {stage} {_STAGE_LABELS.get(stage, '')} | {cells} |")
    lines.append("")
    if forward is not None:
        lines.append("## 3. 阶段后 5 / 20 日收益（仅检验区分度，不是策略）")
        lines.append("")
        lines.append("| 阶段 | 样本(bar) | 5日均值% | 5日中位% | 5日胜率% | 20日均值% | 20日中位% | 20日胜率% |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for _, row in forward.iterrows():
            label = "全样本" if row["stage"] == "ALL" else f"{row['stage']} {_STAGE_LABELS.get(row['stage'], '')}"
            lines.append(f"| {label} | {int(row['bars']):,} | {row['fwd_5_mean_pct']} | {row['fwd_5_median_pct']} | "
                         f"{row['fwd_5_win_rate_pct']} | {row['fwd_20_mean_pct']} | {row['fwd_20_median_pct']} | "
                         f"{row['fwd_20_win_rate_pct']} |")
        lines.append("")
        lines.append("说明：收益为前复权收盘价对收盘价，未扣费税滑点；同一样本内各阶段重叠，不能直接相加；"
                     "该表只用于判断阶段是否具备区分度，不作为可交易结论。")
    lines.append("")
    lines.append("## 4. 已知边界")
    lines.append("")
    lines.append("- 阶段为当日快照的分类结果，不含未来信息；跨停牌日的连续行仍算一次转换，持续天数以 bar 计而非自然日。")
    lines.append("- 阈值仍为经验值（FLAT_SLOPE / BIAS_CLIMAX / VOL_BREAKOUT），本报告不做调参。")
    lines.append("- 前复权源若落后于 RPS 最新交易日，建库阶段会直接阻断，不会产出旧数据。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage history descriptive stats")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--limit", type=int, default=0, help="forward-return pass: first N stocks")
    parser.add_argument("--no-forward", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    if not args.history.exists():
        print(f"history not found: {args.history}")
        return 1

    history = pd.read_parquet(args.history)
    manifest_path = args.history.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    print(f"history: {len(history):,} rows | {history['symbol'].nunique()} stocks | "
          f"{history['trading_day'].min()} .. {history['trading_day'].max()}")

    durations = stage_durations(history)
    counts, shares = transition_matrix(history)
    print("\n=== stage durations (bars) ===")
    print(durations.to_string())

    print("\n=== transition matrix (row %) ===")
    print((shares * 100).round(1).fillna(0).to_string())

    forward_summary = None
    if not args.no_forward:
        combined = forward_returns(history, limit=args.limit)
        if len(combined):
            forward_summary = summarise_forward(combined)
            numeric = forward_summary.select_dtypes(include=[np.number])
            bad_mask = ~np.isfinite(numeric.to_numpy()).all(axis=0)
            if bad_mask.any():
                bad = numeric.columns[bad_mask].tolist()
                print("\nDATA QUALITY BLOCKED: non-finite forward-return statistics in "
                      f"{bad}. Refusing to write a report — check for zero/absent closes.")
                return 2
            print("\n=== forward returns by stage (evaluation only) ===")
            print(forward_summary.to_string(index=False))

    built_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    markdown_path = args.report_dir / f"stage-history-stats-{stamp}.md"
    markdown_path.write_text(render_markdown(manifest, durations, shares, forward_summary, built_at), encoding="utf-8")

    payload = {
        "generated_at": built_at,
        "history": str(args.history),
        "rows": int(len(history)),
        "stocks": int(history["symbol"].nunique()),
        "date_range": [history["trading_day"].min(), history["trading_day"].max()],
        "durations": durations.reset_index().to_dict("records"),
        "transitions_counts": counts.reset_index().to_dict("records"),
        "forward_returns": None if forward_summary is None else forward_summary.to_dict("records"),
        "caveats": [
            "descriptive only — no costs, no execution rules, overlapping samples",
            "durations counted in bars, not calendar days; suspensions collapse into one run",
            "thresholds unchanged from the frozen v1 classifier",
        ],
    }
    json_path = args.report_dir / f"stage-history-stats-{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"\nreport: {markdown_path}")
    print(f"data  : {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
