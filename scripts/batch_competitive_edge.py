#!/usr/bin/env python3
"""批量生成沪深300竞争优势分析，支持断点续跑"""
import json, sys, time, os
from pathlib import Path

sys.path.insert(0, '/home/lufanfeng/Project-Hermes-Stock')
from app.competitive_edge import _generate_via_api, save_competitive_edge

# Load CSI 300 list
with open('/tmp/csi300_approx.json') as f:
    stocks = json.load(f)

# Check existing cache
cache_dir = Path('/home/lufanfeng/Project-Hermes-Stock/data/derived/cache/competitive_edge')
existing = set()
for f in cache_dir.glob('*.json'):
    parts = f.stem.split('_', 1)
    if len(parts) == 2:
        existing.add(parts[1])  # code

# Filter: only stocks not yet analyzed
todo = [(code, name) for code, name in stocks if code not in existing]
done_already = len(stocks) - len(todo)

print(f"沪深300: {len(stocks)} 只")
print(f"已分析: {done_already} 只")
print(f"待分析: {len(todo)} 只")
print(f"预计时间: {len(todo) * 10 / 60:.0f} 分钟")
print()

total = len(todo)
for i, (code, name) in enumerate(todo):
    # Determine market
    market = 'sh' if code.startswith(('6', '68')) else 'sz'
    
    print(f"[{i+1}/{total}] {code} {name} ...", end=' ', flush=True)
    try:
        text = _generate_via_api(market, code, name)
        if text:
            save_competitive_edge(market, code, text, name)
            # Check for 细分龙头 tag
            has_tag = '细分龙头' in text
            print(f"OK {'🏆细分龙头' if has_tag else ''}")
        else:
            print("FAIL (empty response)")
    except Exception as e:
        print(f"ERROR: {e}")
    
    # Rate limiting: 1 second between calls
    if i < total - 1:
        time.sleep(1.5)

print(f"\n完成! {total} 只股票已分析")
print(f"缓存目录: {cache_dir}")
