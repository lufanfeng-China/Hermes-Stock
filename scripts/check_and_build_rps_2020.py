#!/usr/bin/env python3
"""
Check if TDX has data going back to 2019 (need 250d lookback for 2020 RPS).
If yes, build full RPS history back to 2020; if no, report what to do.
"""
import os, sys, struct, subprocess
from pathlib import Path

TDX_DAY_DIR = '/home/lufanfeng/tdx_data/vipdoc/sh/lday'
MIN_DATE = '2019-01-01'
CHECK_FILES = ['sh600000.day', 'sh600519.day', 'sh601318.day',
               'sh600036.day', 'sh601857.day']

def check_earliest_date():
    """Check earliest date available in .day files."""
    earliest = None
    for fname in CHECK_FILES:
        path = os.path.join(TDX_DAY_DIR, fname)
        if not os.path.exists(path):
            continue
        with open(path, 'rb') as f:
            first = f.read(32)
        d = struct.unpack('<I', first[:4])[0]
        date_str = f'{d//10000}-{(d%10000)//100:02d}-{d%100:02d}'
        if earliest is None or date_str < earliest:
            earliest = date_str
    return earliest

def main():
    earliest = check_earliest_date()
    print(f"Earliest TDX data: {earliest}")
    
    if earliest is None:
        print("ERROR: No .day files found!")
        sys.exit(1)
    
    if earliest > '2020-01-01':
        print(f"DATA INSUFFICIENT: earliest is {earliest}, need data before 2019-01-01 (for 250d lookback to 2020)")
        print("ACTION REQUIRED:")
        print("  1. Open 通达信 (TDX) client in Windows")
        print("  2. 工具 → 数据维护 → 日线数据维护")
        print("  3. 勾选'下载历史数据'，起始日期填 2019-01-01")
        print("  4. 下载完成后，重新运行此脚本")
        sys.exit(0)
    
    print("Data is sufficient! Building full RPS history...")
    
    # Run the full history build
    script = Path('/home/lufanfeng/Project-Hermes-Stock/scripts/build_rps_history_full.py')
    venv_python = '/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python'
    
    result = subprocess.run(
        [venv_python, str(script)],
        capture_output=True, text=True, timeout=7200,
        cwd='/home/lufanfeng/Project-Hermes-Stock'
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"Build failed:\n{result.stderr}")
        sys.exit(1)
    
    print("Full RPS history build complete!")

if __name__ == '__main__':
    main()
