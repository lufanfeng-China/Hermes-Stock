#!/usr/bin/env python3
"""Weekly CT-Rotation v1 research: QFQ signal / raw T+1 execution / raw MTM exit.

Current Tongdaxin concept membership is used throughout, so results have explicit
current-taxonomy survivorship bias and are research-only.
"""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.concept_temperature import parse_tdx_concept_mapping
from app.tdx.qfq_kline import load_tdx_qfq_daily

QFQ_DIR = Path('/mnt/c/new_tdx64/T0002/export')
MAPPING = QFQ_DIR / '概念板块.txt'
RAW_TDX = '/home/lufanfeng/tdx_data'
START = pd.Timestamp('2015-01-01')
END = pd.Timestamp('2026-07-31')
HORIZONS = (5, 10, 20)
FEE_RATE = 0.002


def pctile(values, x):
    return sum(v <= x for v in values) / len(values) if values else 0.0


def calc_temperature(grouped, metrics, window):
    """Exact heat-score factors, evaluated on one decision date from QFQ metrics."""
    all_rets=[]; valid={}
    for code, members in grouped.items():
        rows=[metrics[s][window] for s in members if s in metrics and metrics[s][window] is not None]
        if rows:
            valid[code]=rows; all_rets.extend(r[0] for r in rows)
    market=float(np.median(all_rets)) if all_rets else 0.0
    cutoff=float(np.quantile(all_rets,.75)) if all_rets else 0.0
    drafts=[]
    for code, rows in valid.items():
        if len(rows)<10: continue
        rets=np.array([r[0] for r in rows]); vols=np.array([r[1] for r in rows])
        drafts.append({'code':code,'n':len(rows),'med':float(np.median(rets)),
                       'breadth':float((rets>0).mean()*100),'excess':float(np.median(rets)-market),
                       'strong':float((rets>cutoff).mean()*100),'active':float((vols>1.2).mean()*100)})
    if not drafts: return {}
    fields=('med','breadth','excess','strong','active')
    values={f:[x[f] for x in drafts] for f in fields}
    scores=[]
    for x in drafts:
        score=sum(pctile(values[f],x[f])*w for f,w in zip(fields,(30,25,20,15,10)))
        x['score']=round(score,1); scores.append(score)
    for x in drafts:
        p=pctile(scores,x['score']); temp=4
        if p<=.20 and x['med']<=0 and x['breadth']<35: temp=0
        elif p<=.40: temp=1
        elif p<=.60: temp=2
        elif p<=.80 or x['med']<=0 or x['breadth']<55 or x['excess']<=0: temp=3
        elif p>=.95 and x['med']>0 and x['breadth']>=75 and x['excess']>0 and x['strong']>=30 and x['active']>=20 and x['n']>=15: temp=5
        x['temp']=temp
    return {x['code']:x for x in drafts}


def raw_frame(symbol, cache, reader):
    if symbol in cache: return cache[symbol]
    try:
        raw=reader.daily(symbol=symbol).sort_index()
        raw.index=pd.to_datetime(raw.index)
        cache[symbol]=raw
    except Exception:
        cache[symbol]=pd.DataFrame()
    return cache[symbol]


def trade_return(symbol, signal_date, horizon, cache, reader):
    raw=raw_frame(symbol,cache,reader)
    after=raw.loc[raw.index>signal_date]
    if len(after)<=horizon: return None
    entry=float(after.iloc[0]['open']); exit_price=float(after.iloc[horizon-1]['close'])
    if entry<=0 or exit_price<=0: return None
    return (exit_price/entry-1-FEE_RATE)*100, after.index[0], after.index[horizon-1]


def summarize(values):
    a=np.array(values,dtype=float)
    if not len(a): return {'n':0}
    return {'n':int(len(a)),'mean_pct':round(float(a.mean()),2),'median_pct':round(float(np.median(a)),2),'win_pct':round(float((a>0).mean()*100),1),'p25':round(float(np.quantile(a,.25)),2),'p75':round(float(np.quantile(a,.75)),2)}


def main():
    global START
    parser=argparse.ArgumentParser(description='Weekly CT-Rotation exploratory research')
    parser.add_argument('--start', default=str(START.date()), help='inclusive signal start date, YYYY-MM-DD')
    parser.add_argument('--label', default='20260801', help='new output filename label; never overwrites prior report names')
    args=parser.parse_args()
    START=pd.Timestamp(args.start)
    label=args.label
    from mootdx.reader import Reader
    mapping=parse_tdx_concept_mapping(MAPPING.read_text(encoding='gb18030'))
    grouped=defaultdict(list)
    for row in mapping: grouped[row['concept_code']].append(row['symbol'])
    symbols=sorted({r['symbol'] for r in mapping})
    # QFQ preparation: own-series returns/volume/MAs, retained only for dates >= START.
    frames={}; calendar=set(); skipped=0
    for i,s in enumerate(symbols,1):
        try:
            d=load_tdx_qfq_daily(s)
            d=d.loc[d.index>=START-pd.Timedelta(days=500)].copy()
            if len(d)<80: continue
            d['v5']=d['volume'].rolling(5).mean()/d['volume'].shift(5).rolling(20).mean()
            for w in (3,10,20): d[f'r{w}']=d['close'].pct_change(w)*100
            d['ma5']=d['close'].rolling(5).mean(); d['ma10']=d['close'].rolling(10).mean(); d['ma20']=d['close'].rolling(20).mean()
            frames[s]=d; calendar.update(d.index[d.index>=START])
        except Exception: skipped+=1
    # Friday decisions avoid daily lookahead while permitting an 11-year reproducible run.
    dates=sorted(d for d in calendar if d<=END and d.weekday()==4)
    raw_cache={}; reader=Reader.factory(market='std',tdxdir=RAW_TDX)
    previous={}; observations=[]; trades=[]
    for no,date in enumerate(dates):
        metrics={}
        for s,d in frames.items():
            if date not in d.index: continue
            row=d.loc[date]
            if pd.isna(row['r20']) or pd.isna(row['v5']): continue
            metrics[s]={w:(float(row[f'r{w}']),float(row['v5'])) if not pd.isna(row[f'r{w}']) else None for w in (3,10,20)}
            metrics[s]['stock']=(float(row['r10']),float(row['ma5']),float(row['ma10']),float(row['ma20']),float(row['close']))
        temps={w:calc_temperature(grouped,metrics,w) for w in (3,10,20)}
        for code,c10 in temps[10].items():
            c3=temps[3].get(code); c20=temps[20].get(code)
            if not c3 or not c20: continue
            rec={'date':date,'code':code,'t3':c3['temp'],'t10':c10['temp'],'t20':c20['temp'],'s3':c3['score'],'s10':c10['score'],'breadth':c10['breadth']}
            rec['upgrade4']=previous.get(code,{}).get('t10',0)<=3 and c10['temp']>=4
            rec['score_up']=c10['score']-previous.get(code,{}).get('s10',c10['score'])
            observations.append(rec)
        # CT-Rotation candidate: short trigger + medium confirmation + broad participation.
        candidates=[r for r in observations[-len(temps[10]):] if r['date']==date and r['t3']>=4 and r['t10']>=3 and r['t20']>=2 and r['s10']>=80 and r['breadth']>=60]
        candidates.sort(key=lambda r:(.6*r['s3']+.4*r['s10'],r['score_up']),reverse=True)
        for rank,concept in enumerate(candidates[:2],1):
            members=[]
            for s in grouped[concept['code']]:
                if s not in metrics: continue
                r10,ma5,ma10,ma20,close=metrics[s]['stock']
                if ma5>ma10 and close>ma20 and close/ma10-1<.10: members.append((s,r10))
            members.sort(key=lambda x:x[1],reverse=True)
            cutoff=max(1,int(np.ceil(len(members)*.2)))
            for stock_rank,(stock,_) in enumerate(members[:min(2,cutoff)], 1):
                for horizon in HORIZONS:
                    result=trade_return(stock,date,horizon,raw_cache,reader)
                    if result:
                        ret,entry,exit_date=result
                        trades.append({**concept,'rank':rank,'stock_rank':stock_rank,'stock':stock,'horizon':horizon,'return_pct':ret,'entry':entry,'exit':exit_date})
        previous={c:{'t10':x['temp'],'s10':x['score']} for c,x in temps[10].items()}
        if no%100==0: print('progress',no,'/',len(dates),'trades',len(trades),flush=True)
    out=Path('/mnt/c/Users/Sky.Lu/Desktop/output')
    out.mkdir(parents=True,exist_ok=True)
    stamp=label
    pd.DataFrame(observations).to_parquet(out/f'concept_temperature_weekly_observations_{stamp}.parquet',index=False)
    pd.DataFrame(trades).to_csv(out/f'concept_temperature_ct_rotation_trades_{stamp}.csv',index=False,encoding='utf-8-sig')
    report={'date_range':[str(dates[0].date()),str(dates[-1].date())],'decision_frequency':'weekly Friday close; QFQ signal, raw T+1 open entry, raw close MTM horizon exit','taxonomy':'current 2026 Tongdaxin concept mapping (survivorship-biased)','qfq_symbols':len(frames),'skipped':skipped,'weeks':len(dates),'trades':{}}
    for h in HORIZONS:
        df=pd.DataFrame([x for x in trades if x['horizon']==h])
        report['trades'][str(h)]={'all':summarize(df.return_pct if len(df) else []),'by_entry_year':{str(y):summarize(g.return_pct) for y,g in df.groupby(df.entry.dt.year)} if len(df) else {}}
    Path(out/f'concept_temperature_ct_rotation_report_{stamp}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,default=str))

if __name__=='__main__': main()
