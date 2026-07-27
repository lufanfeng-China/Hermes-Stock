#!/usr/bin/env python3
"""CSI300 ndif阈值对比扫描"""
import json, numpy as np, pandas as pd
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR='/mnt/c/new_tdx64'; LOT=50000
with open('/tmp/csi300_constituents.json') as f:
    codes=sorted(set(str(c) for c in json.load(f)))
reader=Reader.factory(market='std',tdxdir=TDX_DIR)

def run(ndif_threshold):
    events=[]; all_trades=[]
    for code in codes:
        try:
            df=reader.daily(code)
            if df is None or len(df)<100: continue
        except: continue
        df=df.sort_index()
        mask=(df.index>='2016-01-01')&(df.index<='2026-07-23')
        df=df[mask].copy(); n=len(df)
        if n<100: continue
        c=df['close'].values.astype(np.float64); o=df['open'].values.astype(np.float64)
        dates=df.index
        ema12=pd.Series(c).ewm(span=12,adjust=False).mean().values
        ema26=pd.Series(c).ewm(span=26,adjust=False).mean().values
        dif=ema12-ema26; dea=pd.Series(dif).ewm(span=9,adjust=False).mean().values
        ndif=np.where(c!=0,dif/c*100,0); ndea=np.where(c!=0,dea/c*100,0)
        ma10=np.full(n,np.nan)
        for i in range(9,n): ma10[i]=np.mean(c[i-9:i+1])
        lots=[]; entry_idx=None
        for i in range(60,n):
            cp=c[i]
            if np.isnan(cp) or cp<=0: continue
            if lots:
                tc=sum(p*q for p,q in lots); tq=sum(q for _,q in lots)
                if tc>0 and cp*tq/tc-1>0.20:
                    si=i+1
                    if si<n:
                        sp=o[si]; sv=sp*tq; pnl=sv-tc
                        all_trades.append({'pnl':pnl,'ret':(sv/tc-1)*100})
                        events.append((entry_idx,1)); events.append((si,-1))
                        lots=[]; entry_idx=None
                    continue
            if np.isnan(ndif[i]) or np.isnan(ndea[i]) or np.isnan(ndif[i-1]) or np.isnan(ndea[i-1]): continue
            if not (ndif[i]>ndea[i] and ndif[i-1]<=ndea[i-1] and ndif[i]<ndif_threshold): continue
            if np.isnan(ma10[i]) or np.isnan(ma10[i-1]): continue
            if ma10[i]<=ma10[i-1]: continue
            if lots:
                tc=sum(p*q for p,q in lots); tq=sum(q for _,q in lots)
                if cp*tq/tc-1<-0.20:
                    target_avg=cp/0.9; q=int(max(1,round((target_avg*tq-tc)/(cp-target_avg))))
                    bi=i+1
                    if bi<n: lots.append((o[bi],q))
            else:
                bi=i+1
                if bi<n: lots=[(o[bi],int(LOT/o[bi]))]; entry_idx=bi
        if lots: events.append((entry_idx,1))
    
    events.sort()
    cur=0; mx=0
    for _,d in events: cur+=d; mx=max(mx,cur)
    
    if not all_trades: return {'n':0,'mx':0,'net':0,'roi':0,'mean':0,'wr':0,'total_pnl':0}
    df_t=pd.DataFrame(all_trades)
    tp=df_t['pnl'].sum()
    capital=mx*LOT if mx>0 else 1
    return {'n':len(df_t),'mx':mx,'capital':capital,'total_pnl':tp,'net':tp,'roi':tp/capital*100,'mean':df_t['ret'].mean(),'wr':(df_t['ret']>0).mean()*100}

thresholds=[-10,-8,-5,-3,-1,0,1,2,3,5]
print(f'{\"ndif<\":>7} {\"交易\":>5} {\"胜率\":>5} {\"均值\":>7} {\"总盈(万)\":>9} {\"资金(万)\":>8} {\"ROI\":>7}')
print('-'*55)
best=None
for t in thresholds:
    r=run(t)
    if r['n']==0: continue
    if best is None or r['roi']>best['roi']: best=r; best_t=t
    pnl_w = r['total_pnl']/10000; cap_w = r['capital']/10000
    mark = ' ★' if r['roi']>=200 else ''
    print(f'  {t:>+4}%   {r["n"]:>5} {r["wr"]:>4.0f}% {r["mean"]:>+6.1f}% {pnl_w:>9,.0f} {cap_w:>8,.0f} {r["roi"]:>+6.0f}%{mark}')

if best:
    print(f'\n最优: ndif<{best_t}%  {best[\"n\"]}笔 ROI{best[\"roi\"]:.0f}%')
