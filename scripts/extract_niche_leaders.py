#!/usr/bin/env python3
"""从竞争优势缓存中提取细分龙头标签"""
import json, re
from pathlib import Path

cache_dir = Path('/home/lufanfeng/Project-Hermes-Stock/data/derived/cache/competitive_edge')
output_dir = Path('/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final')

results = []

for fp in sorted(cache_dir.glob('*.json')):
    try:
        data = json.loads(fp.read_text(encoding='utf-8'))
    except:
        continue
    
    text = data.get('text', '')
    market = data.get('market', '')
    symbol = data.get('symbol', '')
    name = data.get('stock_name', '')
    
    if not symbol:
        continue
    
    # Extract 细分龙头 tag
    is_leader = False
    niche = ''
    
    # Pattern: [标签: 细分龙头, 领域: XXX]
    m = re.search(r'\[标签:\s*细分龙头[,，]\s*领域:\s*([^\]]+)\]', text)
    if m:
        is_leader = True
        niche = m.group(1).strip()
    
    # Also check older format or implicit mention
    if not is_leader and ('细分龙头' in text or '行业龙头' in text or '绝对龙头' in text):
        # Try to find the niche context
        is_leader = True
        niche = '未明确'
    
    results.append({
        'market': market,
        'symbol': symbol.zfill(6),
        'stock_name': name,
        'is_niche_leader': is_leader,
        'niche_category': niche,
    })

# Save
leaders = [r for r in results if r['is_niche_leader']]
non_leaders = [r for r in results if not r['is_niche_leader']]

print(f"总共分析: {len(results)} 只")
print(f"细分龙头: {len(leaders)} 只")
print(f"非龙头: {len(non_leaders)} 只")

if leaders:
    print(f"\n细分龙头列表:")
    for r in sorted(leaders, key=lambda x: x['niche_category']):
        print(f"  {r['symbol']} {r['stock_name']}: {r['niche_category']}")

# Save to parquet and json
import pandas as pd
df = pd.DataFrame(results)
parquet_path = output_dir / 'dataset_niche_leaders.parquet'
json_path = output_dir / 'dataset_niche_leaders.json'
df.to_parquet(parquet_path, index=False)
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n已保存:")
print(f"  {parquet_path}")
print(f"  {json_path}")
