#!/usr/bin/env python3
"""Audit Tongdaxin front-adjusted daily exports without altering their source files."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = Path('/mnt/c/new_tdx64/T0002/export')
OUTPUT = PROJECT_ROOT / 'data' / 'derived' / 'cache' / 'tdx_qfq_export_sync.json'
DATE_RE = re.compile(r'^\s*(\d{4}/\d{2}/\d{2})\t')


def latest_bar_date(path: Path) -> str | None:
    """Read the last valid export date from a small tail window, not whole history."""
    try:
        with path.open('rb') as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 16_384))
            tail = handle.read().decode('gb18030', errors='replace')
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        match = DATE_RE.match(line)
        if match:
            return match.group(1).replace('/', '-')
    return None


def main() -> None:
    files = sorted(EXPORT_DIR.glob('*.txt'))
    if not files:
        raise SystemExit(f'No Tongdaxin QFQ export files found: {EXPORT_DIR}')
    latest_dates: list[str] = []
    invalid = 0
    for path in files:
        value = latest_bar_date(path)
        if value:
            latest_dates.append(value)
        else:
            invalid += 1
    payload = {
        'source': 'Tongdaxin desktop 前复权 export',
        'source_dir': str(EXPORT_DIR),
        'synced_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'file_count': len(files),
        'valid_daily_file_count': len(latest_dates),
        'invalid_or_empty_file_count': invalid,
        'latest_trading_day': max(latest_dates) if latest_dates else None,
        'earliest_latest_trading_day': min(latest_dates) if latest_dates else None,
        'price_basis': 'tdx_export_qfq',
        'note': 'Source files remain in Tongdaxin export directory; this task writes only an audit manifest.',
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ok': True, **payload}, ensure_ascii=False))


if __name__ == '__main__':
    main()
