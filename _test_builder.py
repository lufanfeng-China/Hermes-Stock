import sys, time
from pathlib import Path
from collections import defaultdict
import pandas as pd
import numpy as np

sys.path.insert(0, '/home/lufanfeng/.venvs/moontdx-china-stock-data/lib/python3.12/site-packages')
from mootdx.financial.financial import FinancialReader

TDX_CW = Path('/mnt/c/new_tdx64/vipdoc/cw')
OUT_DIR = Path('data/derived/financial_ts/by_quarter')
OUT_DIR.mkdir(parents=True, exist_ok=True)

def parse_period(report_date: int) -> str:
    s = str(report_date)
    year, month = int(s[:4]), int(s[4:6])
    if month == 3:  return f'{year}Q1'
    if month == 6:  return f'{year}Q2'
    if month == 9:  return f'{year}Q3'
    if month == 12: return f'{year}A'
    q = (month - 1) // 3
    return f'{year}Q{q}' if 1 <= q <= 4 else f'{year}A'

def format_announce_date(raw) -> int:
    try:
        v = float(raw)
        return 0 if (np.isnan(v) or v == 0) else int(v)
    except:
        return 0

def canonical_code(idx_val) -> str:
    s = str(idx_val).strip().lower()
    for p in ('sh:', 'sz:', 'bj:'):
        s = s.replace(p, '')
    return s

zips = sorted(TDX_CW.glob('gpcw*.zip'), reverse=True)
print(f"发现 {len(zips)} 个zip文件\n")

period_data = defaultdict(list)

for zpath in zips[:5]:
    print(f"处理 {zpath.name}...", end=" ", flush=True)
    t0 = time.time()

    df_raw = FinancialReader.to_data(str(zpath))
    if df_raw.empty:
        print("空包")
        continue

    df_raw = df_raw.reset_index()
    code_col = df_raw.columns[0]
    df_raw[code_col] = df_raw[code_col].astype(str).apply(canonical_code)
    df_raw = df_raw.sort_values('report_date').drop_duplicates(subset=code_col, keep='last')
    df_raw.columns = [c.rsplit('.', 1)[0] if '.' in c else c for c in df_raw.columns]
    df_raw = df_raw.loc[:, ~df_raw.columns.duplicated(keep='first')]
    df_idxed = df_raw.set_index(code_col)

    rd_example = int(df_idxed.iloc[0]['report_date'])
    period = parse_period(rd_example)
    n_stocks = df_idxed.shape[0]
    n_cols = df_idxed.shape[1]
    print(f"period={period}, {n_stocks}股x{n_cols}列, {time.time()-t0:.1f}s")

    for code, row in df_idxed.iterrows():
        rd = int(row.get('report_date', 0))
        ad = format_announce_date(row.get('财报公告日期', 0))
        if rd == 0 or pd.isna(rd):
            continue
        record = row.to_dict()
        record['code'] = code
        record['report_date'] = rd
        record['announce_date'] = ad
        period_data[period].append(record)

print(f"\n写入 {len(period_data)} 个季度文件...")
for period, records in sorted(period_data.items()):
    fp = OUT_DIR / f'{period}.parquet'
    df_out = pd.DataFrame(records).set_index('code')
    df_out.to_parquet(fp, index=True, engine='pyarrow', compression='snappy')
    size_kb = fp.stat().st_size / 1024
    print(f"  {period}.parquet  {len(records)}股  {size_kb:.0f}KB")

print("\n读回验证...")
for fp in sorted(OUT_DIR.glob('*.parquet')):
    df_v = pd.read_parquet(fp)
    sample = df_v[['report_date', 'announce_date']].head(2).to_dict('records')
    print(f"  {fp.name}: shape={df_v.shape}, sample={sample}")
