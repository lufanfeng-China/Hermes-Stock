#!/usr/bin/env python3
"""Score-bucket cohort analysis for tradable FIRST_WAVE_ELIGIBLE events only."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

SPLITS={"exploration_2021_2024":("2021-01-01","2024-12-31"),"calibration_2025":("2025-01-01","2025-12-31"),"oos_2026_ytd":("2026-01-01","2026-12-31")}
BUCKETS=[0,60,70,80,101]
LABELS=["<60","60–69.5","70–79.5","≥80"]
def metrics(x:pd.DataFrame,h:int)->dict:
 v=pd.to_numeric(x[f"return_{h}d_pct"],errors="coerce").dropna(); dd=pd.to_numeric(x[f"max_drawdown_{h}d_pct"],errors="coerce").dropna()
 return {"complete_samples":int(len(v)),"mean_return_pct":round(float(v.mean()),4) if len(v) else None,"median_return_pct":round(float(v.median()),4) if len(v) else None,"win_rate_pct":round(float((v>0).mean()*100),2) if len(v) else None,"mean_max_drawdown_pct":round(float(dd.mean()),4) if len(dd) else None}
def summarize(x:pd.DataFrame)->dict:
 x=x.copy();x["score_bucket"]=pd.cut(x.total_score,BUCKETS,right=False,labels=LABELS)
 out={}
 for bucket, part in x.groupby("score_bucket",observed=False):
  out[str(bucket)]={"events":int(len(part)),"score_min":float(part.total_score.min()) if len(part) else None,"score_max":float(part.total_score.max()) if len(part) else None,**{f"{h}d":metrics(part,h) for h in (5,10,20)}}
 out["score_return_spearman"]={str(h):round(float(x[["total_score",f"return_{h}d_pct"]].dropna().corr(method="spearman").iloc[0,1]),4) for h in (5,10,20)}
 return out
def main():
 p=argparse.ArgumentParser();p.add_argument("events",type=Path);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 d=pd.read_parquet(a.events);d.b_date=pd.to_datetime(d.b_date)
 d=d[(d.classification=="FIRST_WAVE_ELIGIBLE")&(d.execution_status=="tradable")]
 result={"definition":"FIRST_WAVE_ELIGIBLE only; T+1 raw-open entry; tradable events only; fixed 5/10/20-day returns; score buckets are descriptive, not approved trading thresholds.","buckets":LABELS,"splits":{}}
 for name,(lo,hi) in SPLITS.items(): result["splits"][name]=summarize(d[(d.b_date>=lo)&(d.b_date<=hi)])
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps({"output":str(a.output)},ensure_ascii=False))
if __name__=="__main__":main()
