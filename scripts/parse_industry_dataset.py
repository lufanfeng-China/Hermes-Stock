#!/usr/bin/env python3
"""Parse Tongdaxin industry files into standardized JSON datasets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.tdx.parsers import (  # noqa: E402
    DEFAULT_INDUSTRY_SOURCE_FILE,
    INDUSTRY_CURRENT_DATASET,
    INDUSTRY_SNAPSHOT_DATASET,
    build_industry_datasets,
    default_timestamp,
    load_text_file,
    today_trading_day,
    with_dataset_name,
    write_json_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-day", default=today_trading_day())
    parser.add_argument("--tdxhy-path", default="/mnt/c/new_tdx64/T0002/hq_cache/tdxhy.cfg")
    parser.add_argument("--tdxzs3-path", default="/mnt/c/new_tdx64/T0002/hq_cache/tdxzs3.cfg")
    parser.add_argument("--tdxzs-path", default="/mnt/c/new_tdx64/T0002/hq_cache/tdxzs.cfg")
    parser.add_argument("--output-dir", default="data/derived/datasets/final")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--data-cutoff-time", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_at = args.generated_at or default_timestamp()
    data_cutoff_time = args.data_cutoff_time or generated_at
    industry_code_path = Path(args.tdxzs3_path)
    if not industry_code_path.exists():
        industry_code_path = Path(args.tdxzs_path)

    current_rows, snapshot_rows = build_industry_datasets(
        stock_mapping_text=load_text_file(args.tdxhy_path, preferred_encoding="utf-8"),
        industry_code_text=load_text_file(industry_code_path, preferred_encoding="gbk"),
        trading_day=args.trading_day,
        generated_at=generated_at,
        data_cutoff_time=data_cutoff_time,
        source_file=DEFAULT_INDUSTRY_SOURCE_FILE if str(args.tdxhy_path).startswith("/mnt/c/new_tdx64/") else str(args.tdxhy_path),
    )

    output_dir = Path(args.output_dir)
    write_json_rows(output_dir / f"{INDUSTRY_CURRENT_DATASET}.json", current_rows)
    write_json_rows(
        output_dir / f"{INDUSTRY_SNAPSHOT_DATASET}.json",
        with_dataset_name(snapshot_rows, INDUSTRY_SNAPSHOT_DATASET),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
