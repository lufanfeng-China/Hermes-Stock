#!/usr/bin/env python3
"""批量生成剩余批次2竞争优势分析"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, '/home/lufanfeng/Project-Hermes-Stock')
from app.competitive_edge import _generate_via_api, save_competitive_edge

with open('/tmp/remaining_batch_2.json') as f: stocks = json.load(f)

cache_dir = Path('/home/lufanfeng/Project-Hermes-Stock/data/derived/cache/competitive_edge')
existing = set()
for fp in cache_dir.glob('*.json'): 
    parts = fp.stem.split('_', 1)
    if len(parts) == 2: existing.add(parts[1])

todo = [(c, n) for c, n in stocks if c not in existing]
print(f"批次2: {len(stocks)}只 | 已缓存: {len(stocks)-len(todo)} | 待分析: {len(todo)}")
print(f"预计: {len(todo)*10/60:.0f} 分钟\n")

for i, (code, name) in enumerate(todo):
    market = 'sh' if code.startswith(('6', '68')) else 'sz'
    print(f"[{i+1}/{len(todo)}] {code} {name} ...", end=' ', flush=True)
    try:
        text = _generate_via_api(market, code, name)
        if text:
            save_competitive_edge(market, code, text, name)
            print(f"OK {'🏆' if '细分龙头' in text else ''}")
        else: print("FAIL")
    except Exception as e: print(f"ERROR: {e}")
    if i < len(todo) - 1: time.sleep(1.5)

print(f"\n完成! {len(todo)} 只已分析")
