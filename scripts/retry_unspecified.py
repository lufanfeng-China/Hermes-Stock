#!/usr/bin/env python3
"""重跑未明确细分龙头标签的股票"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, '/home/lufanfeng/Project-Hermes-Stock')
from app.competitive_edge import _generate_via_api, save_competitive_edge

with open('/tmp/retry_unspecified.json') as f: stocks = json.load(f)
print(f"待重跑: {len(stocks)} 只\n")

for i, (code, name) in enumerate(stocks):
    market = 'sh' if code.startswith(('6', '68')) else 'sz'
    print(f"[{i+1}/{len(stocks)}] {code} {name} ...", end=' ', flush=True)
    try:
        text = _generate_via_api(market, code, name)
        if text:
            save_competitive_edge(market, code, text, name)
            has_tag = '细分龙头' in text
            print(f"OK {'🏆' if has_tag else ''}")
        else: print("FAIL")
    except Exception as e: print(f"ERROR: {e}")
    if i < len(stocks) - 1: time.sleep(0.8)

print(f"\n完成!")
