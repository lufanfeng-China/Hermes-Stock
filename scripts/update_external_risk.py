#!/usr/bin/env python3
"""Manual independent full snapshots, or verified existing archive imports."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.data.external_risk_updates import DATASETS, update_external_risk


def main(argv=None):
    parser = argparse.ArgumentParser(description='公司整体质押/2026公告关联交易独立手动全快照更新（非增量）')
    parser.add_argument('--dataset', choices=DATASETS, required=True)
    parser.add_argument('--import-from', type=Path, help='校验并导入既有归档，不执行源目录脚本，不冒充网络更新')
    parser.add_argument('--root', type=Path, help='数据根目录，默认项目 data/external_risk')
    parser.add_argument('--strategy', choices=('full','monthly'), default='monthly', help='关联交易默认按月完整下载与有界重试，不改变2026年范围')
    args = parser.parse_args(argv)
    try:
        result = update_external_risk(args.dataset, root=args.root, import_from=args.import_from,
                                      progress=lambda line: print(line, flush=True), download_strategy=args.strategy)
    except Exception as exc:
        print('[3/3] 失败：' + str(exc), file=sys.stderr, flush=True)
        return 1
    try:
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    except OSError:
        # Publication succeeded; output is only a notification. Redirect the
        # descriptor too, so buffered stdout cannot fail again at shutdown (120).
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
