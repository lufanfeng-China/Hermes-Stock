#!/usr/bin/env python3
"""2025+ high-breadth concept: leader versus low-position rebound comparison.

Exploratory current-mapping study. QFQ creates signals; raw T+1 open and raw
holding-period close determine price returns. It deliberately compares exactly
one concept selection context and two stock-selection methods.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.concept_temperature import parse_tdx_concept_mapping
from app.tdx.qfq_kline import load_tdx_qfq_daily

START=pd.Timestamp('2025-01-01'); QFQ=Path('/mnt/c/new_tdx64/T0002/export'); OUT=Path('/mnt/c/Users/Sky.Lu/Desktop/output')
OBS=OUT/'concept_temperature_weekly_observations_2025_20260803.parquet'; FEE=.002


def summarize(x):
    a=np.asarray(x,dtype=float)
    if not len(a): return {'n':0}
    return {'n':int(len(a)),'mean_pct':round(float(a.mean()),2),'median_pct':round(float(np.median(a)),2),'win_pct':round(float((a>0).mean()*100),1)}


def main():
    mapping=parse_tdx_concept_mapping((QFQ/'概念板块.txt').read_text(encoding='gb18030'))
    groups=defaultdict(list)
    for row in mapping: groups[row['concept_code']].append(row['symbol'])
    # One known-at-Friday high-breadth concept.  No post-signal ranks are used.
    obs=pd.read_parquet(OBS); obs['date']=pd.to_datetime(obs['date'])
    chosen={}
    for date,g in obs.groupby('date'):
        c=g[(g.t3>=4)&(g.t10>=4)&(g.t20>=3)&(g.breadth>=94)].copy()
        if c.empty: continue
        c['rank_score']=.6*c.s3+.4*c.s10
        chosen[date]=str(c.sort_values(['rank_score','code'],ascending=[False,True]).iloc[0].code)
    symbols={s for x in groups.values() for s in x}; frames={}
    for s in symbols:
        try:
            d=load_tdx_qfq_daily(s).copy()
            d['r10']=d.close.pct_change(10)*100; d['ma5']=d.close.rolling(5).mean(); d['ma10']=d.close.rolling(10).mean(); d['ma20']=d.close.rolling(20).mean()
            frames[s]=d
        except Exception: pass
    from mootdx.reader import Reader
    reader=Reader.factory(market='std',tdxdir='/home/lufanfeng/tdx_data'); raw_cache={}; trades=[]; diagnostics=[]
    def realize(method,date,concept,symbol):
        if symbol not in raw_cache:
            try:
                raw_cache[symbol]=reader.daily(symbol).sort_index()
                if not isinstance(raw_cache[symbol].index, pd.DatetimeIndex):
                    if 'date' in raw_cache[symbol].columns:
                        raw_cache[symbol]=raw_cache[symbol].set_index('date').sort_index()
                    else:
                        raw_cache[symbol]=pd.DataFrame()
                if not raw_cache[symbol].empty:
                    raw_cache[symbol].index=pd.to_datetime(raw_cache[symbol].index)
            except Exception: raw_cache[symbol]=pd.DataFrame()
        raw=raw_cache[symbol]
        if raw.empty: return
        after=raw[raw.index>date]
        for h in (5,10,20):
            if len(after)<h: continue
            entry=float(after.iloc[0].open); exit=float(after.iloc[h-1].close)
            if entry>0 and exit>0: trades.append({'method':method,'signal_date':date,'concept':concept,'symbol':symbol,'horizon':h,'return_pct':(exit/entry-1-FEE)*100,'entry':after.index[0],'exit':after.index[h-1]})
    for date,concept in sorted(chosen.items()):
        members=[]
        for s in groups[concept]:
            d=frames.get(s)
            if d is None or date not in d.index: continue
            i=d.index.get_loc(date)
            if isinstance(i,slice) or i<5: continue
            r=d.iloc[i]
            if any(pd.isna(r[k]) for k in ('r10','ma5','ma10','ma20')): continue
            members.append((s,d,i,float(r.r10),float(r.close),float(r.ma5),float(r.ma10),float(r.ma20)))
        if not members: continue
        # Matched leader baseline: strongest 10d component that is technically tradable.
        leaders=[x for x in members if x[4]>x[7] and x[5]>=x[6] and x[4]/x[6]-1<.10]
        leaders.sort(key=lambda x:x[3],reverse=True)
        if leaders: realize('leader',date,concept,leaders[0][0])
        # Rebound candidate: non-leader positive r10 below concept median, close near MA20,
        # and a QFQ close re-crossed above MA5 within the preceding five daily bars.
        med=float(np.median([x[3] for x in members])); rebounds=[]
        for x in members:
            s,d,i,r10,close,ma5,ma10,ma20=x
            recent=d.iloc[i-4:i+1]
            crossed=any((recent.close.shift(1)<=recent.ma5.shift(1)) & (recent.close>recent.ma5))
            if 0<r10<=med and close>ma20 and close/ma20-1<=.05 and ma5>=ma10 and crossed:
                rebounds.append(x)
        rebounds.sort(key=lambda x:(x[4]/x[7]-1,-x[3],x[0]))
        diagnostics.append({'date':date,'concept':concept,'members':len(members),'median_r10':med,'leader':bool(leaders),'rebound_candidates':len(rebounds)})
        if rebounds: realize('rebound',date,concept,rebounds[0][0])
    trades=pd.DataFrame(trades); tag='2025_high_breadth_rebound_v1_20260804'
    trades.to_csv(OUT/f'concept_temperature_{tag}_trades.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(diagnostics).to_csv(OUT/f'concept_temperature_{tag}_diagnostics.csv',index=False,encoding='utf-8-sig')
    result={'range':['2025-01-01','2026-07-31'],'concept_weeks':len(chosen),'definition':'highest-ranked concept meeting t3>=4,t10>=4,t20>=3,breadth>=94; compare leader to non-leader MA20-near QFQ MA5 re-cross','results':{}}
    for h in (5,10,20):
        result['results'][str(h)]={m:summarize(trades[(trades.horizon==h)&(trades.method==m)].return_pct) for m in ('leader','rebound')}
    (OUT/f'concept_temperature_{tag}_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__': main()
