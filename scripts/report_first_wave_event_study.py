#!/usr/bin/env python3
"""Summarise first-wave cohort outcomes by frozen chronological research split."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd

def measure(df):
 out={'events':int(len(df)),'tradable':int((df.execution_status=='tradable').sum()),'untradable':int((df.execution_status!='tradable').sum()),'by_execution':df.execution_status.value_counts().to_dict()}
 out['untradable_rate_pct']=round(out['untradable']/out['events']*100,4) if out['events'] else None
 for h in (5,10,20):
  values=pd.to_numeric(df[f'return_{h}d_pct'],errors='coerce').dropna();dd=pd.to_numeric(df[f'max_drawdown_{h}d_pct'],errors='coerce').dropna()
  out[f'{h}d']={'complete_samples':int(len(values)),'mean_return_pct':round(float(values.mean()),4) if len(values) else None,'median_return_pct':round(float(values.median()),4) if len(values) else None,'win_rate_pct':round(float((values>0).mean()*100),2) if len(values) else None,'mean_max_drawdown_pct':round(float(dd.mean()),4) if len(dd) else None,'median_max_drawdown_pct':round(float(dd.median()),4) if len(dd) else None}
 return out
def main():
 p=argparse.ArgumentParser();p.add_argument('events',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();df=pd.read_parquet(a.events);df['b_date']=pd.to_datetime(df.b_date)
 splits={'exploration_2021_2024':('2021-01-01','2024-12-31'),'calibration_2025':('2025-01-01','2025-12-31'),'oos_2026_ytd':('2026-01-01','2026-12-31')};result={'definition':'QFQ signal at B close; raw T+1 open event study only; no portfolio, exit, sizing or MTM.','source':str(a.events),'splits':{}}
 for name,(start,end) in splits.items():
  part=df[(df.b_date>=start)&(df.b_date<=end)];result['splits'][name]={'all':measure(part),'by_classification':{g:measure(x) for g,x in part.groupby('classification')}}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'output':str(a.output),'splits':list(result['splits'])},ensure_ascii=False))
if __name__=='__main__':main()
