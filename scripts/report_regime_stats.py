"""Statistics for the A/B/C/D regime history: duration, transitions, forward returns."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.stage_regime import STAGE_LABELS, WINDOW  # noqa: E402

FINAL = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
DEFAULT_HISTORY = FINAL / "regime_history.parquet"
OUTPUT_DIR = Path("/mnt/c/Users/Sky.Lu/Desktop/output")
STAGES = ["A", "B", "C", "D"]
HORIZONS = (5, 20)


def build_runs(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values(["symbol", "trading_day"])
    runs = []
    for symbol, group in ordered.groupby("symbol", sort=False):
        stages = group["stage"].to_numpy()
        days = group["trading_day"].to_numpy()
        start = 0
        for index in range(1, len(stages) + 1):
            if index == len(stages) or stages[index] != stages[start]:
                runs.append({"symbol": symbol, "stage": stages[start],
                             "start": days[start], "end": days[index - 1],
                             "trading_days": index - start})
                start = index
    return pd.DataFrame(runs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report A/B/C/D regime statistics")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    frame = pd.read_parquet(args.history, columns=["symbol", "trading_day", "stage", "score"])
    if args.limit:
        keep = sorted(frame["symbol"].unique())[: args.limit]
        frame = frame[frame["symbol"].isin(keep)]
    print(f"rows {len(frame):,} | stocks {frame['symbol'].nunique():,}")

    runs = build_runs(frame)
    duration = runs.groupby("stage")["trading_days"].agg(
        runs="count", mean="mean", median="median", p90=lambda s: s.quantile(0.9), max="max").reindex(STAGES)
    share = (frame["stage"].value_counts(normalize=True) * 100).reindex(STAGES).fillna(0.0)

    pairs = runs.assign(next_stage=runs.sort_values(["symbol", "start"]).groupby("symbol")["stage"].shift(-1))
    pairs = pairs.dropna(subset=["next_stage"])
    transitions = pd.crosstab(pairs["stage"], pairs["next_stage"]).reindex(index=STAGES, columns=STAGES).fillna(0)
    transitions_pct = transitions.div(transitions.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0) * 100

    # forward returns per stage (evaluation only), computed on the QFQ series
    from app.stage_classify import prepare_bars
    from app.tdx.qfq_kline import load_tdx_qfq_daily

    symbols = frame["symbol"].unique()
    if args.limit:
        symbols = symbols[: args.limit]
    bucket = {stage: {horizon: [] for horizon in HORIZONS} for stage in STAGES}
    for symbol in symbols:
        try:
            bars = prepare_bars(load_tdx_qfq_daily(symbol))
        except Exception:  # noqa: BLE001
            continue
        closes = bars["close"]
        days = [str(day)[:10] for day in bars.index]
        index = {day: position for position, day in enumerate(days)}
        subset = frame[frame["symbol"] == symbol]
        for stage, day in zip(subset["stage"].to_numpy(), subset["trading_day"].to_numpy()):
            position = index.get(str(day))
            if position is None:
                continue
            for horizon in HORIZONS:
                if position + horizon < len(closes):
                    base = closes.iloc[position]
                    future = closes.iloc[position + horizon]
                    if base > 0 and future > 0:
                        bucket[str(stage)][horizon].append(float(future / base - 1) * 100)

    rows = []
    for stage in STAGES:
        entry = {"stage": stage, "label": STAGE_LABELS[stage], "bar_share_pct": round(float(share[stage]), 2),
                 "runs": int(duration.loc[stage, "runs"]), "days_mean": round(float(duration.loc[stage, "mean"]), 2),
                 "days_median": float(duration.loc[stage, "median"]),
                 "days_p90": float(duration.loc[stage, "p90"]), "days_max": int(duration.loc[stage, "max"])}
        for horizon in HORIZONS:
            values = np.asarray(bucket[stage][horizon], dtype=float)
            entry[f"fwd_{horizon}_mean_pct"] = round(float(values.mean()), 2) if values.size else None
            entry[f"fwd_{horizon}_median_pct"] = round(float(np.median(values)), 2) if values.size else None
            entry[f"fwd_{horizon}_win_pct"] = round(float((values > 0).mean() * 100), 2) if values.size else None
        rows.append(entry)

    all_values = {horizon: np.concatenate([np.asarray(bucket[s][horizon], dtype=float) for s in STAGES])
                  for horizon in HORIZONS}
    overall = {f"fwd_{h}_mean_pct": round(float(all_values[h].mean()), 2) for h in HORIZONS if all_values[h].size}

    stamp = pd.Timestamp.now().strftime("%Y%m%d-%H%M")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": stamp, "rows": int(len(frame)), "stocks": int(frame["symbol"].nunique()),
               "window_bars": WINDOW, "stages": rows, "transitions_pct": transitions_pct.round(1).to_dict(),
               "overall": overall}
    (OUTPUT_DIR / f"regime-stats-{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# A/B/C/D 阶段统计（{stamp}）", "",
             f"数据：{len(frame):,} 行 / {frame['symbol'].nunique():,} 只 / 判定窗口 {WINDOW} 根", "",
             "| 阶段 | 含义 | 行占比 | 段数 | 平均天数 | 中位 | P90 | 最长 | 5日均值 | 5日中位 | 20日均值 | 20日中位 | 20日胜率 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['stage']} | {row['label']} | {row['bar_share_pct']}% | {row['runs']} | {row['days_mean']} | "
                     f"{row['days_median']:.0f} | {row['days_p90']:.0f} | {row['days_max']} | "
                     f"{row['fwd_5_mean_pct']}% | {row['fwd_5_median_pct']}% | {row['fwd_20_mean_pct']}% | "
                     f"{row['fwd_20_median_pct']}% | {row['fwd_20_win_pct']}% |")
    lines += ["", f"全样本：5 日均值 {overall.get('fwd_5_mean_pct')}%，20 日均值 {overall.get('fwd_20_mean_pct')}%（仅检验区分度，不构成收益预测）", "",
              "## 段转换概率（行=% 从该阶段离开后进入的列阶段）", "",
              "| 从 \\ 到 | " + " | ".join(STAGES) + " |", "|---" * (len(STAGES) + 1) + "|"]
    for stage in STAGES:
        cells = " | ".join(f"{transitions_pct.loc[stage, target]:.1f}%" for target in STAGES)
        lines.append(f"| {stage} | {cells} |")
    report = OUTPUT_DIR / f"regime-stats-{stamp}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"\nreport: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
