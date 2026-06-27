"""PE-TTM v8 最终版本: 条件⑤ → 公告日 MA5>MA10"""
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

# 条件⑤: MA5 > MA10
def check_ma5_gt_ma10(code, period):
    t=pd.Timestamp(p2d(period))
    try:
        daily=reader.daily(symbol=code)
        if daily is None or daily.empty:return False
        daily=daily.sort_index()
        if len(daily)<10:return False
        daily['ma5']=daily['close'].rolling(5).mean()
        daily['ma10']=daily['close'].rolling(10).mean()
        mask=daily.index<=t
        if not mask.any():return False
        d=daily[mask].iloc[-1]
        if pd.isna(d['ma5']) or pd.isna(d['ma10']):return False
        return float(d['ma5'])>float(d['ma10'])
    except:
        return False

passed_stock=set()
for ci,(code,periods) in enumerate(candidates.items()):
    for period in periods:
        if check_ma5_gt_ma10(code, period):
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
                    trades.append({'r':'Pre','ret':round((tv/tc-1)*100,2),'ey':int(lots[0][0][:4]),'lots':len(lots),'hold':0})
                    to_remove.append(code);continue
        cl_trade=row['open_next'];pe_ad=row['pe_ad'];pct=row['pe_pct']
        lp=lots[-1][1]
        drop=(cl_trade/lp-1)*100
        if drop<=ADD and len(lots)<MAX_LOTS:
            lots.append((period,cl_trade))
        reason=None
        if pct>=TH:reason='PE'
        if reason:
            tc=sum(p for _,p in lots);tv=cl_trade*len(lots)
            entry_period=lots[0][0]
            entry_idx=ALL.index(entry_period)
            hold_q=i-entry_idx
            trades.append({'r':reason,'ret':round((tv/tc-1)*100,2),'ey':int(lots[0][0][:4]),'lots':len(lots),'hold':hold_q})
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
        entry_period=lots[0][0]
        entry_idx=ALL.index(entry_period)
        hold_q=EI-entry_idx
        trades.append({'r':'End','ret':round((tv/tc-1)*100,2),'ey':int(lots[0][0][:4]),'lots':len(lots),'hold':hold_q})
    except:pass

df=pd.DataFrame(trades)
n=len(df);wr=(df['ret']>0).mean()*100;mn=df['ret'].mean();md=df['ret'].median()
# 修正: ret是加权收益率,需乘以实际份数
tot=(df['ret']*df['lots']).sum()*CAP/100;inv=df['lots'].sum()*CAP

print("PE-TTM 中长期价值策略 v8 — 最终回测")
print("══════════════════════════════════════")
print(f"回测区间: 2014Q1 ~ 2026Q1")
print(f"条件⑤: 公告日 MA5 > MA10 (替换原 MA20)")
print()
print(f"总交易: {n}笔    胜率: {wr:.1f}%")
print(f"均值: {mn:+.2f}%    中位: {md:+.2f}%")
print(f"总盈亏: {tot:+,.0f}    总投资: {inv:+,.0f}")
print(f"ROI: {tot/inv*100:+.2f}%    份数: {df['lots'].mean():.1f}")
print()

print("年度明细:")
print(f"{'年':>5s} {'笔数':>4s} {'均值':>8s} {'胜率':>6s} {'总盈亏':>12s} {'份数':>5s} {'持有(季)':>8s}")
print("-"*60)
profit_years=0
for y in sorted(df['ey'].unique()):
    s=df[df['ey']==y];wr_s=(s['ret']>0).mean()*100;mn_s=s['ret'].mean()
    tot_s=(s['ret']*s['lots']).sum()*CAP/100;lots_s=s['lots'].mean()
    hold_q=s['hold'].mean() if 'hold' in s.columns else 0
    if tot_s>0:profit_years+=1
    print(f"{y:>5d} {len(s):>4d} {mn_s:>+8.2f}% {wr_s:>5.1f}% {tot_s:>+12,.0f} {lots_s:>5.1f} {hold_q:>7.1f}")
print("-"*60)
print(f"{'合计':>5s} {n:>4d} {mn:>+8.2f}% {wr:>5.1f}% {tot:>+12,.0f} {df['lots'].mean():>5.1f}")
print(f"\n盈利年份: {profit_years}年 (仅计正总盈亏)")

print(f"\n退出分布:")
for r in ['PE','Pre','End']:
    s=df[df['r']==r]
    if len(s)>0:
        wr_s=(s['ret']>0).mean()*100
        hold=s['hold'].mean() if 'hold' in s.columns else 0
        print(f"  {r}: {len(s)}笔 均值{s['ret'].mean():+.2f}% 胜{wr_s:.1f}% 持{hold:.1f}季")
