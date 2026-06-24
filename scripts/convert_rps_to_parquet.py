#!/usr/bin/env python3
"""Convert dataset_stock_rps_history.json to Parquet (one-time)."""
import sys, os, time, json

JSON_PATH = '/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/dataset_stock_rps_history.json'
PARQUET_PATH = JSON_PATH.replace('.json', '.parquet')

print("[1/3] Loading JSON with streaming parser...", flush=True)
t0 = time.time()

# Use Python's built-in json to avoid pd.read_json's ujson memory spike
with open(JSON_PATH, 'r') as f:
    data = json.load(f)  # list of dicts

t1 = time.time()
print(f"  Loaded {len(data):,} records in {t1-t0:.1f}s", flush=True)

# Now import pandas (after json is in memory, to isolate memory measurement)
print("[2/3] Building DataFrame...", flush=True)
import pandas as pd
df = pd.DataFrame(data)
del data  # free the list immediately

print(f"  Shape: {df.shape}", flush=True)
print(f"  Columns: {list(df.columns)}", flush=True)
print(f"  Memory: {df.memory_usage(deep=True).sum() / 1024**2:.1f} MB", flush=True)

print("[3/3] Writing Parquet (snappy compressed)...", flush=True)
df.to_parquet(PARQUET_PATH, compression='snappy', index=False)
del df

sz_mb = os.path.getsize(PARQUET_PATH) / 1024**2
sz_json = os.path.getsize(JSON_PATH) / 1024**2
ratio = sz_json / sz_mb
print(f"  Parquet: {sz_mb:.1f} MB  (from {sz_json:.1f} MB JSON, {ratio:.1f}x smaller)", flush=True)
print("Done.", flush=True)
