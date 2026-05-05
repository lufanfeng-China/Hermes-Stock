#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.relative_valuation.snapshot_builder import write_current_industry_snapshots


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="构建行业相对估值 current 快照")
    parser.add_argument(
        "--reuse-existing-complete",
        action="store_true",
        help="复用已包含 temperature_history_since_2022、percentile_samples、member_valuation_rows 的完整行业快照",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="单个行业构建失败时立即退出；默认记录失败并继续构建其他行业",
    )
    args = parser.parse_args(argv)

    def print_progress(event: dict[str, object]) -> None:
        event_name = event.get("event")
        if event_name == "start":
            print(
                f"开始构建行业相对估值快照（含同业估值表 member_valuation_rows），共 {event.get('total_industries', 0)} 个二级行业",
                flush=True,
            )
            return
        if event_name == "industry_start":
            print(
                f"[{event.get('index')}/{event.get('total_industries')}] {event.get('industry_level_2_name')} 开始构建...",
                flush=True,
            )
            return
        if event_name == "industry_done":
            print(
                f"[{event.get('index')}/{event.get('total_industries')}] {event.get('industry_level_2_name')} 完成："
                f"member_valuation_rows={event.get('member_valuation_row_count', 0)}，"
                f"percentile_samples={event.get('percentile_sample_count', 0)}",
                flush=True,
            )
            return
        if event_name == "industry_skipped":
            print(
                f"[{event.get('index')}/{event.get('total_industries')}] {event.get('industry_level_2_name')} 跳过："
                f"复用已有完整快照，member_valuation_rows={event.get('member_valuation_row_count', 0)}",
                flush=True,
            )
            return
        if event_name == "industry_failed":
            print(
                f"[{event.get('index')}/{event.get('total_industries')}] {event.get('industry_level_2_name')} 失败：{event.get('error')}",
                flush=True,
            )
            return
        if event_name == "complete":
            total = event.get("total_industries", 0)
            print(
                f"完成：成功 {event.get('success_count', 0)}/{total}，"
                f"跳过 {event.get('skipped_count', 0)}，"
                f"失败 {event.get('failure_count', 0)}，"
                f"同业估值行 {event.get('total_member_valuation_rows', 0)}",
                flush=True,
            )
            failures = event.get("failures")
            if isinstance(failures, list) and failures:
                print("失败行业明细：", flush=True)
                for failure in failures:
                    if isinstance(failure, dict):
                        print(f"- {failure.get('industry_level_2_name')}: {failure.get('error')}", flush=True)

    path = write_current_industry_snapshots(
        progress_callback=print_progress,
        reuse_existing_complete=args.reuse_existing_complete,
        continue_on_error=not args.fail_fast,
    )
    print(f"Wrote industry valuation snapshot to {path}", flush=True)


if __name__ == "__main__":
    main()
