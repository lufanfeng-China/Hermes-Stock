#!/usr/bin/env python3
"""Parse Tongdaxin concept file into standardized JSON datasets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.tdx.parsers import (  # noqa: E402
    CONCEPT_CURRENT_DATASET,
    CONCEPT_DICTIONARY_DATASET,
    CONCEPT_SNAPSHOT_DATASET,
    DEFAULT_CONCEPT_SOURCE_FILE,
    build_concept_datasets,
    default_timestamp,
    load_text_file,
    today_trading_day,
    with_dataset_name,
    write_json_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-day", default=today_trading_day())
    parser.add_argument("--extern-path", default="/mnt/c/new_tdx64/T0002/signals/extern_sys.txt")
    parser.add_argument("--output-dir", default="data/derived/datasets/final")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--data-cutoff-time", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_at = args.generated_at or default_timestamp()
    data_cutoff_time = args.data_cutoff_time or generated_at

    dictionary_rows, current_rows, snapshot_rows = build_concept_datasets(
        concept_text=load_text_file(args.extern_path, preferred_encoding="gbk"),
        trading_day=args.trading_day,
        generated_at=generated_at,
        data_cutoff_time=data_cutoff_time,
        source_file=DEFAULT_CONCEPT_SOURCE_FILE if str(args.extern_path).startswith("/mnt/c/new_tdx64/") else str(args.extern_path),
    )

    output_dir = Path(args.output_dir)
    write_json_rows(output_dir / f"{CONCEPT_DICTIONARY_DATASET}.json", dictionary_rows)
    write_json_rows(output_dir / f"{CONCEPT_CURRENT_DATASET}.json", current_rows)
    write_json_rows(
        output_dir / f"{CONCEPT_SNAPSHOT_DATASET}.json",
        with_dataset_name(snapshot_rows, CONCEPT_SNAPSHOT_DATASET),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
