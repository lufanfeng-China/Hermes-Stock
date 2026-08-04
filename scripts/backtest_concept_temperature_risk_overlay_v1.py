#!/usr/bin/env python3
"""Pre-registered v1: concept-temperature 4/5 -> <=3 risk overlay on matched leaders.

Research only: current mapping and weekly temperature observations are used.
QFQ determines Friday selection; raw T+1 open executes; raw daily closes measure
per-trade MTM price risk.  No cash competition or corporate-action wealth ledger.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.concept_temperature import parse_tdx_concept_mapping
from app.tdx.qfq_kline import load_tdx_qfq_daily
from app.concept_theme_clusters import build_theme_clusters, primary_concept_for_stock
OUT=Path('/mnt/c/Users/Sky.Lu/Desktop/output'); QFQ=Path('/mnt/c/new_tdx64/T0002/export'); FEE=.002
OBS=OUT/'concept_temperature_weekly_observations_2025_20260803.parquet'


def stats(rows, key):
    x=np.asarray([r[key] for r in rows],dtype=float)
    if not len(x): return {'n':0}
    return {'n':len(x),'mean':round(float(x.mean()),2),'median':round(float(np.median(x)),2),'p25':round(float(np.percentile(x,25)),2),'p75':round(float(np.percentile(x,75)),2)}


def raw_frame(reader, symbol):
    try:
        d=reader.daily(symbol).sort_index()
        if not isinstance(d.index,pd.DatetimeIndex):
            if 'date' not in d: return pd.DataFrame()
            d=d.set_index('date').sort_index()
        d.index=pd.to_datetime(d.index); return d
    except Exception: return pd.DataFrame()


def main():
    mapping=parse_tdx_concept_mapping((QFQ/'概念板块.txt').read_text(encoding='gb18030'))
    groups=defaultdict(list); by_symbol=defaultdict(list)
    for r in mapping: groups[r['concept_code']].append(r['symbol']); by_symbol[r['symbol']].append(r)
    clusters=build_theme_clusters(mapping,.35)['concept_to_cluster']
    obs=pd.read_parquet(OBS); obs['date']=pd.to_datetime(obs.date)
    obs_by_date={d:g.copy() for d,g in obs.groupby('date')}
    # Fixed entry universe: previous high-breadth leader study, no new threshold tuning.
    selected={}
    for d,g in obs_by_date.items():
        x=g[(g.t3>=4)&(g.t10>=4)&(g.t20>=3)&(g.breadth>=94)].copy()
        if not x.empty:
            x['rank_score']=.6*x.s3+.4*x.s10
            selected[d]=str(x.sort_values(['rank_score','code'],ascending=[False,True]).iloc[0].code)
    qframes={}
    for symbol in {x['symbol'] for x in mapping}:
        try:
            d=load_tdx_qfq_daily(symbol).copy(); d['r10']=d.close.pct_change(10)*100; d['ma5']=d.close.rolling(5).mean(); d['ma10']=d.close.rolling(10).mean(); d['ma20']=d.close.rolling(20).mean(); qframes[symbol]=d
        except Exception: pass
    from mootdx.reader import Reader
    reader=Reader.factory(market='std',tdxdir='/home/lufanfeng/tdx_data'); raws={}; rows=[]
    for signal_date, concept in sorted(selected.items()):
        candidates=[]
        for s in groups[concept]:
            d=qframes.get(s)
            if d is None or signal_date not in d.index: continue
            i=d.index.get_loc(signal_date)
            if isinstance(i,slice): continue
            x=d.iloc[i]
            if any(pd.isna(x[k]) for k in ('r10','ma5','ma10','ma20')): continue
            if x.close>x.ma20 and x.ma5>=x.ma10 and x.close/x.ma10-1<.10:
                candidates.append((float(x.r10),s))
        if not candidates: continue
        symbol=max(candidates)[1]
        if symbol not in raws: raws[symbol]=raw_frame(reader,symbol)
        raw=raws[symbol]
        if raw.empty: continue
        after=raw[raw.index>signal_date]
        if len(after)<20: continue
        entry_date=after.index[0]; entry=float(after.iloc[0].open)
        # Entry primary uses every concept label for this stock at its known Friday snapshot.
        g=obs_by_date[signal_date].copy(); g['concept_code']=g.code; g['symbol']=symbol; g['temperature']=g.t10; g['heat_score']=g.s10; g['breadth_pct']=g.breadth; g['concept_rank']=g.s10.rank(ascending=False,method='min')
        labels={x['concept_code'] for x in by_symbol[symbol]}
        primary=primary_concept_for_stock(symbol,g[g.concept_code.isin(labels)].to_dict('records'),clusters)
        if primary is None: continue
        primary_code=primary['concept_code']; end_idx=19; exit_kind='baseline_20d'
        # Pre-registered overlay: only after a 4/5 entry state, at each later Friday close.
        entry_temp=int(primary['temperature'])
        if entry_temp>=4:
            for check_date in sorted(d for d in obs_by_date if d>signal_date):
                if check_date>after.index[end_idx]: break
                hit=obs_by_date[check_date]
                hit=hit[hit.code==primary_code]
                if not hit.empty and int(hit.iloc[0].t10)<=3:
                    next_raw=raw[raw.index>check_date]
                    if not next_raw.empty and next_raw.index[0]<=after.index[end_idx]:
                        end_idx=raw.index.get_loc(next_raw.index[0]) - raw.index.get_loc(entry_date)
                        exit_kind='temp_4or5_to_3'; break
        exit_bar=after.iloc[end_idx]
        baseline_close=float(after.iloc[19].close)
        held=after.iloc[:end_idx+1]
        baseline_path=after.iloc[:20]
        rows.append({'signal_date':signal_date,'symbol':symbol,'selected_concept':concept,'primary_concept':primary_code,'cluster':primary['theme_cluster_id'],'entry_date':entry_date,'entry_temp':entry_temp,'exit_kind':exit_kind,'overlay_exit_date':exit_bar.name,'overlay_days':end_idx+1,'baseline_return_pct':(baseline_close/entry-1-FEE)*100,'overlay_return_pct':(float(exit_bar.open if exit_kind!='baseline_20d' else exit_bar.close)/entry-1-FEE)*100,'baseline_mae_pct':(baseline_path.close.min()/entry-1)*100,'overlay_mae_pct':(held.close.min()/entry-1)*100,'baseline_mfe_pct':(baseline_path.close.max()/entry-1)*100,'overlay_mfe_pct':(held.close.max()/entry-1)*100})
    tag='2025_concept_risk_overlay_v1_20260804'; pd.DataFrame(rows).to_csv(OUT/f'{tag}_trades.csv',index=False,encoding='utf-8-sig')
    result={'definition':'fixed high-breadth leader entries; compare fixed 20 raw-close bars vs exit next raw open after entry primary concept t10 falls 4/5 to <=3','n':len(rows),'overlay_exits':sum(r['exit_kind']!='baseline_20d' for r in rows),'baseline':{k:stats(rows,'baseline_'+k) for k in ('return_pct','mae_pct','mfe_pct')},'overlay':{k:stats(rows,'overlay_'+k) for k in ('return_pct','mae_pct','mfe_pct')},'held_days':stats(rows,'overlay_days')}
    (OUT/f'{tag}_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__': main()
