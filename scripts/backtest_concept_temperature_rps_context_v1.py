#!/usr/bin/env python3
"""2025+ exploratory RPS-cross baseline vs prior-Friday concept-temperature context.

Not the authoritative RPS-first strategy: this deliberately isolates whether a
simple RPS-total cross becomes better when its stock belongs to the single
highest-ranked, newly-heating concept known at the preceding Friday close.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
import sys
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.concept_temperature import parse_tdx_concept_mapping

START='2025-01-01'; END='2026-06-18'; RPS_MIN=360; FEE=0.002
RPS=ROOT/'data/derived/datasets/final/dataset_stock_rps_history.parquet'
OBS=Path('/mnt/c/Users/Sky.Lu/Desktop/output/concept_temperature_weekly_observations_2025_20260803.parquet')
MAP=Path('/mnt/c/new_tdx64/T0002/export/概念板块.txt')
OUT=Path('/mnt/c/Users/Sky.Lu/Desktop/output')


def stat(s):
    s=np.asarray(s,dtype=float)
    if not len(s): return {'n':0}
    return {'n':int(len(s)),'mean_pct':round(float(s.mean()),2),'median_pct':round(float(np.median(s)),2),'win_pct':round(float((s>0).mean()*100),1)}


def main():
    # Freeze concept relation deliberately; group current mapping.
    by_symbol=defaultdict(set)
    for r in parse_tdx_concept_mapping(MAP.read_text(encoding='gb18030')):
        by_symbol[r['symbol']].add(r['concept_code'])
    obs=pd.read_parquet(OBS); obs['date']=pd.to_datetime(obs['date'])
    # Compute a known-at-Friday, one-week-forward context. Require a genuine 10d upgrade.
    contexts={}
    for date,g in obs.groupby('date'):
        x=g[(g.t3>=4)&(g.t10>=4)&(g.t20>=3)&(g.upgrade4)&(g.breadth>=60)].copy()
        if not x.empty:
            x['rank_score']=.6*x.s3+.4*x.s10
            contexts[date]=str(x.sort_values(['rank_score','code'],ascending=[False,True]).iloc[0].code)
    d=pd.read_parquet(RPS,columns=['trading_day','market','symbol','rps_20','rps_50','rps_120','rps_250'])
    d['rps_total']=d.rps_20+d.rps_50+d.rps_120+d.rps_250
    d=d[(d.trading_day>=START)&(d.trading_day<=END)].copy()
    d['date']=pd.to_datetime(d.trading_day)
    d.sort_values(['date','market','symbol'],inplace=True)
    # Daily crossing and actual 60-trading-day dedup.  Previous Friday context only.
    prev={}; last_signal={}; day_to_i={x:i for i,x in enumerate(sorted(d.trading_day.unique()))}; signals=[]
    for date,g in d.groupby('date',sort=True):
        prior_friday=date-pd.Timedelta(days=(date.weekday()-4)%7 or 7)
        context=contexts.get(prior_friday)
        today={}
        for r in g.itertuples(index=False):
            key=(r.market,str(r.symbol).zfill(6)); total=float(r.rps_total); today[key]=total
            crossed=total>=RPS_MIN and prev.get(key,float('-inf'))<RPS_MIN
            if not crossed: continue
            if key in last_signal and day_to_i[str(date.date())]-last_signal[key]<60: continue
            last_signal[key]=day_to_i[str(date.date())]
            symbols_concepts=by_symbol.get(key[1],set())
            signals.append({'signal_date':date,'market':key[0],'symbol':key[1],'rps_total':total,'context_concept':context or '',
                            'in_context':bool(context and context in symbols_concepts)})
        prev=today
    # Raw execution/price realization for matched fixed horizons.
    from mootdx.reader import Reader
    reader=Reader.factory(market='std',tdxdir='/home/lufanfeng/tdx_data'); cache={}; rows=[]
    for s in signals:
        key=s['symbol']
        if key not in cache:
            try: cache[key]=reader.daily(key).sort_index()
            except Exception: cache[key]=pd.DataFrame()
        raw=cache[key]; after=raw[raw.index>s['signal_date']]
        for h in (5,10,20):
            if len(after)<h: continue
            entry=float(after.iloc[0].open); close=float(after.iloc[h-1].close)
            if entry>0 and close>0: rows.append({**s,'horizon':h,'entry':after.index[0],'exit':after.index[h-1],'return_pct':(close/entry-1-FEE)*100})
    trades=pd.DataFrame(rows); tag='2025_20260618_rps_context'
    trades.to_csv(OUT/f'concept_temperature_rps_context_trades_{tag}.csv',index=False,encoding='utf-8-sig')
    summary={'range':[START,END],'definition':'RPS-total cross >=360 with 60-trading-day dedup; not authoritative RPS-first; previous-Friday single newly-heating top-concept context','signals':len(signals),'contexts':len(contexts),'results':{}}
    for h in (5,10,20):
        x=trades[trades.horizon==h]
        summary['results'][str(h)]={'baseline':stat(x.return_pct),'in_context':stat(x[x.in_context].return_pct),'outside_context':stat(x[~x.in_context].return_pct)}
    (OUT/f'concept_temperature_rps_context_summary_{tag}.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__': main()
