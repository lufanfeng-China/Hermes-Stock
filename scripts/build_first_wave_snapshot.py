#!/usr/bin/env python3
"""Materialize current or strictly PIT first-wave scan snapshots."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from tempfile import NamedTemporaryFile
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.first_wave_start import scan_symbol
from app.first_wave_snapshot import CURRENT, HISTORY, SCHEMA_VERSION
from app.stock_filter_history_progress import write_progress

ASSET=ROOT/'data/derived/datasets/final/first_wave_qfq_ohlcv.parquet'
def main() -> None:
 p=argparse.ArgumentParser(); p.add_argument('--trading-day',default=''); p.add_argument('--output',type=Path); a=p.parse_args()
 if not ASSET.is_file(): raise SystemExit(f'missing required QFQ OHLCV asset: {ASSET}')
 df=pd.read_parquet(ASSET); df['date']=pd.to_datetime(df['date'])
 target=pd.Timestamp(a.trading_day) if a.trading_day else df['date'].max()
 if target not in set(df['date']): raise SystemExit(f'{target.date()} is not an available QFQ trading day')
 df=df[df.date<=target]
 historical=bool(a.trading_day); outdir=HISTORY if historical else CURRENT.parent; out=(a.output or (HISTORY/f'{target.date()}.json' if historical else CURRENT)); lock=HISTORY/f'{target.date()}.building'
 if historical: lock.parent.mkdir(parents=True,exist_ok=True); lock.touch(exist_ok=True); write_progress(HISTORY,str(target.date()),stage='扫描第一波平台与突破事件',percent=1)
 rows=[]; groups=list(df.groupby(['market','symbol'],sort=True)); total=len(groups)
 for i,((market,symbol),bars) in enumerate(groups,1):
  name=str(bars.iloc[-1].get('stock_name') or symbol)
  found=scan_symbol(bars,market=market,symbol=symbol,stock_name=name,as_of_date=str(target.date()))
  if found: rows.append(found)
  if historical and (i%25==0 or i==total): write_progress(HISTORY,str(target.date()),stage='扫描第一波平台与突破事件',percent=2+96*i/total,completed=i,total=total)
 payload={'schema_version':SCHEMA_VERSION,'as_of_date':str(target.date()),'data_date':str(df.date.max().date()),'price_basis':'tdx_export_qfq','amount_basis':'tdx_export_daily_amount','rows':rows}
 out.parent.mkdir(parents=True,exist_ok=True)
 with NamedTemporaryFile('w',encoding='utf-8',dir=out.parent,delete=False) as h: json.dump(payload,h,ensure_ascii=False,separators=(',',':'),allow_nan=False); temp=Path(h.name)
 os.replace(temp,out)
 if historical: write_progress(HISTORY,str(target.date()),stage='快照完成',percent=100,completed=total,total=total); lock.unlink(missing_ok=True)
 print(json.dumps({'output':str(out),'as_of_date':str(target.date()),'rows':len(rows)},ensure_ascii=False))
if __name__=='__main__': main()
