#!/usr/bin/env python3
"""全市场 2026年 MACD极值策略回测"""
import json, time, numpy as np, pandas as pd
from pathlib import Path
from mootdx.reader import Reader

TDX_DIR='/mnt/c/new_tdx64'; LOT=50000; START='2026-01-01'
ds=Path('/home/lufanfeng/Project-Hermes-Stock/data/derived/datasets/final/dataset_stock_industry_current.json')
with open(ds) as f: data=json.load(f)
seen=set(); codes=[]
for item in data:
    c=str(item['symbol']); m=item.get('market','')
    if c in seen: continue; seen.add(c)
    if m=='bj' or c.startswith('92'): continue
    codes.append(c)

from mootdx.quotes import Quotes
client=Quotes.factory(market='std'); names={}
for mkt in [0,1]:
    df=client.stocks(market=mkt)
    for _,row in df.iterrows(): names[str(row['code'])]=str(row['name']).strip().replace('\x00','')

reader=Reader.factory(market='std',tdxdir=TDX_DIR)
all_holds=[]; closed_pnl=0; all_ret=[]; open_pos=[]; trades_detail=[]
t0=time.time()

for ci,code in enumerate(codes):
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
                    sp=o[si]; sv=sp*tq; pnl=sv-tc; ret=(sv/tc-1)*100
                    all_holds.append(si-entry_idx if entry_idx else 0)
                    all_ret.append(ret); closed_pnl+=pnl
                    trades_detail.append({'code':code,'name':names.get(code,code),'buy':str(dates[entry_idx].date()) if entry_idx else '?','sell':str(dates[si].date()),'lots':len(lots),'pnl':pnl,'ret':ret,'hold':si-entry_idx})
                    lots=[]; entry_idx=None
                continue
        if dates[i]<pd.Timestamp(START): continue
        if np.isnan(ndif[i]) or np.isnan(ndea[i]) or np.isnan(ndif[i-1]) or np.isnan(ndea[i-1]): continue
        if not (ndif[i]>ndea[i] and ndif[i-1]<=ndea[i-1] and ndif[i]<-5.0): continue
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
    if lots:
        tc=sum(p*q for p,q in lots); tq=sum(q for _,q in lots)
        open_pos.append({'code':code,'name':names.get(code,code),'lots':len(lots),'cost':tc,'avg':tc/tq,'cur':c[-1],'pct':(c[-1]*tq/tc-1)*100,'pnl':c[-1]*tq-tc,'entry':str(dates[entry_idx].date()) if entry_idx else '?'})
    if (ci+1)%1000==0: print(f'  {ci+1}/{len(codes)} | {len(trades_detail)}笔 | {time.time()-t0:.0f}秒')

a=np.array(all_holds); r=np.array(all_ret); op=sum(p['pnl'] for p in open_pos)
ti=len(trades_detail)*LOT+sum(p['cost'] for p in open_pos)
print(f'\n=== 全市场 2026年 ({time.time()-t0:.0f}秒) ===')
print(f'已平仓: {len(trades_detail)}笔 胜率{(r>0).mean()*100:.0f}% 均值{r.mean():+.1f}% 盈亏{closed_pnl:+,.0f}')
print(f'持仓: {len(open_pos)}只 浮亏{op:+,.0f}')
print(f'合计: {closed_pnl+op:+,.0f} 投入{ti:,.0f} ROI:{(closed_pnl+op)/ti*100:+.1f}% 持{a.mean():.0f}d')

open_pos.sort(key=lambda p: p['pct'])
print(f'\n持仓(亏损最大10只):')
for p in open_pos[:10]:
    print(f'  {p["code"]} {p["name"]:<8} {p["lots"]}份 {p["entry"]} 均价{p["avg"]:.1f} 现{p["cur"]:.1f} {p["pct"]:+.1f}% {p["pnl"]:+,.0f}')
print(f'\n持仓(盈利最大10只):')
for p in open_pos[-10:]:
    print(f'  {p["code"]} {p["name"]:<8} {p["lots"]}份 {p["entry"]} 均价{p["avg"]:.1f} 现{p["cur"]:.1f} {p["pct"]:+.1f}% {p["pnl"]:+,.0f}')
trades_detail.sort(key=lambda t: t['sell'])
print(f'\n已平仓({len(trades_detail)}笔):')
for t in trades_detail:
    print(f'  {t["code"]} {t["name"]:<8} {t["buy"]}→{t["sell"]} {t["lots"]}份 {t["pnl"]:+,.0f} {t["ret"]:+.1f}% {t["hold"]}d')
