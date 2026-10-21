#!/usr/bin/env python3
"""Offline-only first-wave event study. It never feeds API or page responses."""
from __future__ import annotations
import argparse, json, statistics, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.financial.reports import _load_raw_daily_bars
from app.search import index as search_index
from app.first_wave_snapshot import HISTORY

def main() -> None:
 p=argparse.ArgumentParser();p.add_argument('dates',nargs='+',help='already-built PIT snapshot dates');p.add_argument('--output',type=Path,default=ROOT/'data/derived/research/first_wave_event_study.json');a=p.parse_args()
 events=[]
 for day in a.dates:
  payload=json.loads((HISTORY/f'{day}.json').read_text(encoding='utf-8'))
  for row in payload.get('rows',[]):
   bars=_load_raw_daily_bars(search_index,row['symbol']); bdays=[str(x.get('trading_day')) for x in bars]; signal=str(row['b_date'])
   if signal not in bdays: continue
   idx=bdays.index(signal); entry_idx=idx+1
   if entry_idx>=len(bars): continue
   entry=float(bars[entry_idx].get('open') or 0)
   if entry<=0: continue
   result={'signal_date':signal,'entry_date':bdays[entry_idx],'market':row['market'],'symbol':row['symbol'],'classification':row['classification'],'score':row['total_score'],'entry_price_raw':entry}
   for horizon in (5,10,20):
    end=entry_idx+horizon-1
    if end>=len(bars): continue
    closes=[float(x.get('close') or 0) for x in bars[entry_idx:end+1]]
    if not all(closes): continue
    result[f'return_{horizon}d_pct']=round((closes[-1]/entry-1)*100,4); result[f'max_drawdown_{horizon}d_pct']=round((min(closes)/entry-1)*100,4)
   events.append(result)
 summary={}
 for h in (5,10,20):
  vals=[x[f'return_{h}d_pct'] for x in events if f'return_{h}d_pct' in x]
  summary[str(h)]={'samples':len(vals),'mean_return_pct':round(statistics.mean(vals),4) if vals else None,'median_return_pct':round(statistics.median(vals),4) if vals else None}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'method':'T+1 raw open; fixed-horizon raw-close event study; not a portfolio backtest','events':events,'summary':summary},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'output':str(a.output),'events':len(events),'summary':summary},ensure_ascii=False))
if __name__=='__main__':main()
