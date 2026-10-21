#!/usr/bin/env python3
"""One-pass-per-symbol historical first-wave event scan; never builds daily snapshots."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import pandas as pd
from mootdx.reader import Reader
from app.config import TONGDAXIN_DIR
from app.first_wave_research import scan_continuous_events,attach_raw_outcomes
from app.search.index import load_security_rows

ASSET=ROOT/'data/derived/datasets/final/first_wave_qfq_ohlcv.parquet'
OUT=ROOT/'data/derived/research/first_wave_events'
def main():
 p=argparse.ArgumentParser();p.add_argument('--start',default='2021-01-01');p.add_argument('--end',default='2026-12-31');p.add_argument('--limit',type=int,default=0);p.add_argument('--output',type=Path);a=p.parse_args()
 out=a.output or OUT/f'first_wave_events_{a.start}_{a.end}.parquet';out.parent.mkdir(parents=True,exist_ok=True)
 df=pd.read_parquet(ASSET);df['date']=pd.to_datetime(df['date']);df=df[(df.date>=pd.Timestamp(a.start)-pd.Timedelta(days=180))&(df.date<=pd.Timestamp(a.end))]
 names={(r['market'],r['symbol']):r.get('stock_name','') for r in load_security_rows()}
 groups=df.groupby(['market','symbol'],sort=True)
 total=groups.ngroups
 events=[]; failures=[]
 for n,(key,part) in enumerate(groups,1):
  if a.limit and n>a.limit: break
  try:
   part=part[['date','open','high','low','close','volume','amount']]
   for e in scan_continuous_events(part,market=key[0],symbol=key[1],stock_name=names.get(key,'')):
    if a.start<=e['b_date']<=a.end: events.append(e)
  except Exception as exc: failures.append(f'{key[0]}:{key[1]} {exc}')
  if n%100==0: print(json.dumps({'progress':n,'total':min(total,a.limit) if a.limit else total,'events':len(events),'failures':len(failures)},ensure_ascii=False),flush=True)
 keys_processed=min(total,a.limit) if a.limit else total
 reader=Reader.factory(market='std',tdxdir=TONGDAXIN_DIR); raw={}
 for e in events:
  key=(e['market'],e['symbol'])
  if key not in raw:
   try: raw[key]=reader.daily(e['symbol'])
   except Exception: raw[key]=None
 rows=attach_raw_outcomes(events,raw)
 pd.DataFrame(rows).to_parquet(out,index=False)
 summary={'ok':True,'output':str(out),'symbols':keys_processed,'events':len(rows),'failures':len(failures),'tradable':sum(r['execution_status']=='tradable' for r in rows),'by_group':pd.DataFrame(rows).groupby('classification').size().to_dict() if rows else {}}
 out.with_suffix('.summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__': main()
