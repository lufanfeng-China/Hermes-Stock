#!/usr/bin/env python3
"""Build financial time-series parquet for 2020-2021."""
from pathlib import Path
import pandas as pd
from mootdx.financial.financial import FinancialReader

TS_DIR = Path("/home/lufanfeng/Project-Hermes-Stock/data/derived/financial_ts/by_quarter")
CW_DIR = Path("/mnt/c/new_tdx64/vipdoc/cw")

def period_from_date(rd):
    s = str(int(rd)).zfill(8)
    m = s[4:6]
    if m == "03": return f"{s[:4]}Q1"
    if m == "06": return f"{s[:4]}Q2"
    if m == "09": return f"{s[:4]}Q3"
    return f"{s[:4]}A"

def dedup_cols(df):
    """Make duplicate column names unique by appending _2, _3 etc."""
    cols = df.columns.tolist()
    seen = {}
    result = []
    for c in cols:
        if c not in seen:
            seen[c] = 0
            result.append(c)
        else:
            seen[c] += 1
            result.append(f"{c}_{seen[c]}")
    df.columns = result
    return df

zips = sorted(CW_DIR.glob("gpcw*.zip"))
for zp in zips:
    y = int(zp.name.replace("gpcw","")[:4])
    if y < 2020 or y > 2021:
        continue
    print(f"Reading {zp.name}...")
    df = FinancialReader.to_data(str(zp))
    if df is None or df.empty or "report_date" not in df.columns:
        print(f"  Skip")
        continue
    df = dedup_cols(df)
    # Keep only rows with 2020-2021 report dates
    df = df[(df["report_date"] >= 20200101) & (df["report_date"] <= 20211231)]
    if len(df) == 0:
        continue
    
    for rd in sorted(df["report_date"].unique()):
        period = period_from_date(rd)
        subset = df[df["report_date"] == rd].copy()
        if "code" in subset.columns:
            subset = subset.drop_duplicates(subset="code", keep="last").set_index("code")
        elif subset.index.name != "code":
            subset.index.name = "code"
        
        out = TS_DIR / f"{period}.parquet"
        if out.exists():
            old = pd.read_parquet(out)
            combined = pd.concat([old, subset])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.to_parquet(out)
            print(f"  {period}: merged -> {len(combined)} stocks")
        else:
            subset.to_parquet(out)
            print(f"  {period}: new -> {len(subset)} stocks")

print("\nFinal files:")
for f in sorted(TS_DIR.glob("*.parquet")):
    df = pd.read_parquet(f)
    print(f"  {f.name}: {len(df)} stocks")
