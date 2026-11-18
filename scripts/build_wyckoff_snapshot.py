#!/usr/bin/env python3
"""Build immutable daily all-market Wyckoff QFQ observation snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.wyckoff_snapshot import (DEFAULT_EXPORT_DIR, DEFAULT_OUTPUT_DIR,
                                  DEFAULT_SYNC_MANIFEST, build_snapshot)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-dir', type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--sync-manifest', type=Path, default=DEFAULT_SYNC_MANIFEST)
    parser.add_argument('--trading-day', help='YYYY-MM-DD; default validated QFQ manifest day')
    parser.add_argument('--limit', type=int, help='first N symbols; isolated output only, sample_only')
    parser.add_argument('--workers', type=int, default=1, help='reserved, validated 1..4; sequential bounded-memory implementation')
    args = parser.parse_args(argv)
    def report_progress(processed: int, total: int, success: int, failed: int) -> None:
        print(f'WYCKOFF_PROGRESS {processed}/{total} success={success} failed={failed}', flush=True)

    result = build_snapshot(args.export_dir, args.output_dir, trading_day=args.trading_day,
                            sync_manifest=args.sync_manifest, limit=args.limit, workers=args.workers,
                            progress_callback=report_progress)
    print(json.dumps({'as_of_date': result['as_of_date'], 'completeness': result['completeness'],
                      'coverage': result['coverage'], 'output_dir': str(args.output_dir)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
