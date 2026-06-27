"""PE-TTM 中长期价值策略 — 最终版本 (公告日补仓)"""
import pandas as pd; from pathlib import Path; from mootdx.reader import Reader

BASE=Path('/home/lufanfeng/Project-Hermes-Stock')
reader=Reader.factory(market='std',tdxdir='/home/lufanfeng/tdx_data')
pe_db=pd.read_parquet(BASE/'data/derived/pe_ttm_quarterly.parquet')

def pk(p):
    if p.endswith('A'):return(int(p[:4]),4)
    return(int(p[:4]),int(p[5:]))
ALL=sorted(pe_db['period'].unique(),key=pk)
pe_ix=pe_db.set_index(['code','period'])
CAP=50000;MAX_TOTAL=200;MAX_LOTS=4;ADD=-20;EP=30;TH=60;IM=0.6
SI=ALL.index('2014Q1');EI=ALL.index('2026Q1')

def p2d(p):
    y=int(p[:4])
    if p.endswith('A'):return f'{y}-12-31'
    if 'Q1' in p:return f'{y}-03-31'
    if 'Q2' in p:return f'{y}-06-30'
    return f'{y}-09-30'

cw_dir=BASE/'data/derived/financial_ts/by_quarter'
preannounce={}
for fp in cw_dir.glob('*.parquet'):
    if fp.stem=='latest':continue
    cdf=pd.read_parquet(fp)
    for code in cdf.index:
        ad=cdf.loc[code,'业绩预告公告日期 ']
        if pd.isna(ad) or ad==0:continue
        lo=cdf.loc[code,'业绩预告-本期净利润同比增幅下限%']
        if pd.isna(lo):continue
        preannounce[(code,fp.stem)]=(int(ad),float(lo))

candidates={}
for i in range(SI,EI+1):
    period=ALL[i]
    for code in pe_ix.loc[pd.IndexSlice[:,period],:].index.get_level_values(0).unique():
        row=pe_ix.loc[(code,period)]
        pe_ad,pct,imd,eps=row['pe_ad'],row['pe_pct'],row['ind_median_pe'],row['eps']
        if pct>EP or pe_ad>imd*IM:continue
        if i>=1:
            try:
                if pe_ad>=pe_ix.loc[(code,ALL[i-1])]['pe_ad']:continue
            except:pass
        py=f'{int(period[:4])-1}{period[4:]}'
        try:pyr=pe_ix.loc[(code,py)]
        except:pass
        else:
            if pyr['eps']>0 and eps<pyr['eps']*0.85:continue
        if code not in candidates:candidates[code]=[]
        candidates[code].append(period)

passed_stock=set()
daily_data={}
for ci,(code,periods) in enumerate(candidates.items()):
    try:
        daily=reader.daily(symbol=code)
        if daily is None or daily.empty:continue
        daily=daily.sort_index()
        if len(daily)<20:continue
        daily['ma20']=daily['close'].rolling(20).mean()
        daily_data[code]=daily
    except:continue
    for period in periods:
        t=pd.Timestamp(p2d(period));m=daily.index<=t
        if not m.any():continue
        d=daily[m].iloc[-1]
        if pd.isna(d['ma20']):continue
        if float(d['close'])>float(d['ma20']):
            passed_stock.add((code,period))

idx=reader.daily(symbol='000905');idx=idx.sort_index()
idx['ma150']=idx['close'].rolling(150).mean()
def idx_ok(period):
    t=pd.Timestamp(p2d(period));m=idx.index<=t
    if not m.any():return True
    r=idx[m].iloc[-1]
    if pd.isna(r['ma150']):return True
    return float(r['close'])>float(r['ma150'])

def get_close(code,date_int):
    y=date_int//10000;m=(date_int%10000)//100;d=date_int%100
    try:
        daily=reader.daily(symbol=code)
        if daily is None or daily.empty:return None
        daily=daily.sort_index()
        mask=daily.index<=pd.Timestamp(f'{y}-{m:02d}-{d:02d}')
        if not mask.any():return None
        return float(daily.loc[mask].iloc[-1]['close'])
    except:return None

trades=[];positions={}
for i in range(SI,EI+1):
    period=ALL[i]
    to_remove=[]
    for code in list(positions.keys()):
        lots,_,_=positions[code]
        try:row=pe_ix.loc[(code,period)]
        except:continue
        if (code,period) in preannounce:
            ad,lo_pct=preannounce[(code,period)]
            if lo_pct<=-30:
                cl=get_close(code,ad)
                if cl:
                    tc=sum(p for _,p in lots);tv=cl*len(lots)
                    trades.append({'r':'Pre','ret':round((tv/tc-1)*100,2),'ey':int(lots[0][0][:4]),'lots':len(lots)})
                    to_remove.append(code);continue
        cl_trade=row['open_next'];pe_ad=row['pe_ad'];pct=row['pe_pct']
        # 补仓: 公告日开盘价较上次买入跌20%加1份
        lp=lots[-1][1]
        drop=(cl_trade/lp-1)*100
        if drop<=ADD and len(lots)<MAX_LOTS:
            lots.append((period,cl_trade))
        reason=None
        if pct>=TH:reason='PE'
        if reason:
            tc=sum(p for _,p in lots);tv=cl_trade*len(lots)
            trades.append({'r':reason,'ret':round((tv/tc-1)*100,2),'ey':int(lots[0][0][:4]),'lots':len(lots)})
            to_remove.append(code)
    for code in to_remove:del positions[code]
    total_lots=sum(len(l) for l in positions.values())
    if idx_ok(period):
        for code in pe_ix.loc[pd.IndexSlice[:,period],:].index.get_level_values(0).unique():
            if code in positions:continue
            if (code,period) not in passed_stock:continue
            if total_lots>=MAX_TOTAL:break
            row=pe_ix.loc[(code,period)]
            positions[code]=([(period,row['open_next'])],row['eps'],row['pe_pct'])
            total_lots+=1
for code in positions:
    lots,_,_=positions[code]
    try:
        row=pe_ix.loc[(code,ALL[-1])]
        cl=row['open_next'];tc=sum(p for _,p in lots);tv=cl*len(lots)
        trades.append({'r':'End','ret':round((tv/tc-1)*100,2),'ey':int(lots[0][0][:4]),'lots':len(lots)})
    except:pass

df=pd.DataFrame(trades)
n=len(df);wr=(df['ret']>0).mean()*100;mn=df['ret'].mean()
tot=df['ret'].sum()*CAP/100;inv=df['lots'].sum()*CAP
label='公告日补仓'
print(f'\n{label}: {n}笔 胜率{wr:.1f}% 均值{mn:+.2f}% 总{tot:+,.0f} ROI{tot/inv*100:+.2f}% 份{df["lots"].mean():.1f}')
for y in sorted(df['ey'].unique()):
    s=df[df['ey']==y];wr_s=(s['ret']>0).mean()*100
    print(f'  {y}:{len(s):>3}笔 均{s["ret"].mean():+.2f}% 胜{wr_s:.1f}% {s["lots"].mean():.1f}份')
