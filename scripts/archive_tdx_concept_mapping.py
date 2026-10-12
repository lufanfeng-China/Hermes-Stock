#!/usr/bin/env python3
"""Create an immutable, auditable snapshot of the TDX concept-board mapping.

This is forward-only evidence collection.  It deliberately refuses to create a
snapshot for a past trading day: a current source file cannot prove historical
membership.  The snapshot records capture time, raw-file SHA256, raw GB18030
bytes, and normalized concept-member rows.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.concept_temperature import parse_tdx_concept_mapping

SOURCE=Path('/mnt/c/new_tdx64/T0002/export/概念板块.txt')


def args():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,default=SOURCE)
    p.add_argument('--trading-day',required=True,help='capture trading day YYYY-MM-DD; must equal local capture date')
    p.add_argument('--output-root',type=Path,default=ROOT/'data/archive')
    return p.parse_args()


def main():
    a=args(); today=datetime.now().astimezone().date().isoformat()
    if a.trading_day != today:
        raise SystemExit(f'Refusing historical backfill: requested {a.trading_day}, local capture date is {today}')
    raw=a.source.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
    try: text=raw.decode('gb18030')
    except UnicodeDecodeError as e: raise SystemExit(f'Invalid GB18030 source: {e}')
    rows=parse_tdx_concept_mapping(text)
    if not rows: raise SystemExit('No parseable concept-member rows; snapshot not written')
    directory=a.output_root/f'trading_day={a.trading_day}'/'snapshots'
    raw_path=directory/'snapshot_tdx_concept_board_mapping_gb18030.txt'
    data_path=directory/'snapshot_tdx_concept_board_membership.json'
    if raw_path.exists() or data_path.exists():
        raise SystemExit(f'Refusing overwrite of immutable snapshot directory: {directory}')
    directory.mkdir(parents=True,exist_ok=False)
    captured_at=datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    raw_path.write_bytes(raw)
    payload={'dataset_name':'snapshot_tdx_concept_board_membership','capture_day':a.trading_day,'captured_at':captured_at,'source_path':str(a.source),'source_sha256':sha,'source_mtime':datetime.fromtimestamp(a.source.stat().st_mtime).astimezone().isoformat(timespec='seconds'),'source_encoding':'gb18030','point_in_time_verified':False,'temporal_status':'current_source_captured; source_as_of_day_unverified','row_count':len(rows),'rows':rows}
    data_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'snapshot':str(data_path),'raw':str(raw_path),'rows':len(rows),'sha256':sha,'captured_at':captured_at},ensure_ascii=False))

if __name__=='__main__': main()
