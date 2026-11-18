#!/usr/bin/env python3
"""Publish bounded recent-entry evidence after the same-day swing snapshot."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.swing_entry_snapshot import build_snapshot, DEFAULT_EXPORT_DIR, DEFAULT_OUTPUT_DIR


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-dir', type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--trading-day', help='YYYY-MM-DD, must have a complete parent swing publication')
    args = parser.parse_args(argv)
    result = build_snapshot(export_dir=args.export_dir, output_dir=args.output_dir,
                            trading_day=args.trading_day)
    print(json.dumps({'as_of_date': result['as_of_date'], 'coverage': result['coverage'],
                      'completeness': result['completeness']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
