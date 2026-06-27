"""
Below-zero active GC 回测 + PE-TTM 预过滤器
用法: python backtest_bz_active_gc_pe.py [--pe-filter] [--start 2026-01-01] [--end 2026-06-30]
不加 --pe-filter = 原始策略（对照）
加 --pe-filter = PE ≤ 行业中位数 AND PE ≤ 历史20%分位
"""
import pandas as pd
import numpy as np
from pathlib import Path
from mootdx.reader import Reader
import argparse, sys

BASE = Path('/home/lufanfeng/Project-Hermes-Stock')
sys.path.insert(0, str(BASE))

# ── 参数 ──
ap = argparse.ArgumentParser()
ap.add_argument('--pe-filter', action='store_true', help='启用 PE 预过滤')
ap.add_argument('--start', default='2026-01-01')
ap.add_argument('--end', default='2026-06-30')
ap.add_argument('--capital', type=float, default=100000, help='单笔资金')
args = ap.parse_args()

START = pd.Timestamp(args.start)
END = pd.Timestamp(args.end)

# ── 加载 PE 数据库 ──
pe_db = pd.read_parquet(BASE / 'data/derived/pe_ttm_quarterly.parquet')
pe_lookup = {}
for _, row in pe_db.iterrows():
    key = (row['code'], row['period'])
    pe_lookup[key] = {
        'pe_ttm': row['pe_ttm'],
        'pe_pct': row['pe_pct'],
        'ind_median': row.get('ind_median_pe', None),
        'pe_cheap': row.get('pe_cheap', False),
    }

# ── 数据层 ──
reader = Reader.factory(market='std', tdxdir='/home/lufanfeng/tdx_data')
pe_db_index = pe_db.set_index(['code', 'period'])

# ── 股票池：加载 RPS 筛选出的活跃股票 ──
rps_path = BASE / 'data/derived/datasets/final/dataset_stock_rps_current.json'
if rps_path.exists():
    import json
    with open(rps_path) as f:
        rps_data = json.load(f)
    if isinstance(rps_data, list):
        stock_pool = [str(r.get('symbol','')) for r in rps_data if r.get('symbol')]
    else:
        stock_pool = list(rps_data.keys())
else:
    # 退而求其次：用前 1000 只
    stock_pool = pe_db['code'].unique()[:1000].tolist()

print(f"股票池: {len(stock_pool)} 只")
print(f"PE 过滤: {'开启' if args.pe_filter else '关闭（对照）'}")
print(f"回测区间: {START.date()} ~ {END.date()}")
print()

# ── MACD 计算 ──
def compute_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    ndif = dif / close * 100
    ndea = dea / close * 100
    return dif, dea, ndif, ndea

# ── 回测主循环 ──
results = []
stock_count = 0
signal_count = 0
filtered_count = 0

for code in stock_pool:
    stock_count += 1
    if stock_count % 500 == 0:
        print(f"  进度: {stock_count}/{len(stock_pool)}", file=sys.stderr)
    
    try:
        daily = reader.daily(symbol=code)
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
    except:
        continue
    
    daily = daily[(daily.index >= START) & (daily.index <= END)]
    if len(daily) < 40:
        continue
    
    close = daily['close']
    dif, dea, ndif, ndea = compute_macd(close)
    
    # 检测 golden cross: ndif 从 <= ndea 变为 > ndea
    gc_mask = (ndif > ndea) & (ndif.shift(1) <= ndea.shift(1))
    gc_dates = daily.index[gc_mask]
    
    for date in gc_dates:
        idx = daily.index.get_loc(date)
        if idx < 3:
            continue
        
        ndif_val = ndif.iloc[idx]
        
        # Below-zero filter: ndif in [-5, -2)
        if ndif_val < -5 or ndif_val >= -2:
            continue
        
        # Rate: ndif 3-day change ≥ 1%
        ndif_3d_ago = ndif.iloc[max(0, idx-3)]
        rate = ndif_val - ndif_3d_ago
        if rate < 1.0:
            continue
        
        # Rising 2 days: ndif yesterday > ndif 2 days ago, and ndif today > ndif yesterday
        if idx < 2:
            continue
        if not (ndif.iloc[idx-1] > ndif.iloc[idx-2] and ndif_val > ndif.iloc[idx-1]):
            continue
        
        # ── PE-TTM 预过滤 ──
        if args.pe_filter:
            # Find most recent financial period before this date
            date_ym = int(date.strftime('%Y%m'))
            # Map to quarter: 01-03=Q1, 04-06=Q2 (with report_date 0630), etc.
            # Use the period key matching our parquet naming
            y = date.year
            m = date.month
            if m <= 3:
                periods_to_try = [f'{y-1}A', f'{y-1}Q3', f'{y-1}Q2']
            elif m <= 6:
                periods_to_try = [f'{y}Q1', f'{y-1}A', f'{y-1}Q3']
            elif m <= 9:
                periods_to_try = [f'{y}Q2', f'{y}Q1', f'{y-1}A']
            else:
                periods_to_try = [f'{y}Q3', f'{y}Q2', f'{y}Q1']
            
            pe_ok = False
            for period in periods_to_try:
                info = pe_lookup.get((code, period))
                if info and info['pe_cheap']:
                    pe_ok = True
                    break
            
            if not pe_ok:
                filtered_count += 1
                continue
        
        signal_count += 1
        
        close_at_signal = close.iloc[idx]
        
        # Forward returns
        for horizon in [5, 10, 20]:
            future_idx = min(idx + horizon, len(daily) - 1)
            future_close = close.iloc[future_idx]
            ret = (future_close / close_at_signal - 1) * 100
            pnl = args.capital * ret / 100
            
            results.append({
                'code': code,
                'date': date.strftime('%Y-%m-%d'),
                'ndif': round(ndif_val, 3),
                'signal_close': round(close_at_signal, 2),
                'horizon': f'T+{horizon}',
                'exit_date': daily.index[future_idx].strftime('%Y-%m-%d'),
                'exit_close': round(future_close, 2),
                'ret_pct': round(ret, 2),
                'pnl': round(pnl, 2),
            })

print(f"\n处理: {stock_count} 只股票", file=sys.stderr)
print(f"信号: {signal_count} 笔 (PE过滤掉了 {filtered_count} 笔)", file=sys.stderr)

if not results:
    print("没有产生任何信号")
    sys.exit(0)

df = pd.DataFrame(results)

# ── 汇总 ──
print(f"\n{'='*60}")
print(f"Below-zero Active GC 回测 ({'PE过滤' if args.pe_filter else '无过滤'})")
print(f"{'='*60}")

for horizon in ['T+5', 'T+10', 'T+20']:
    sub = df[df['horizon'] == horizon]
    n = len(sub)
    mean_ret = sub['ret_pct'].mean()
    win_rate = (sub['ret_pct'] > 0).mean() * 100
    total_pnl = sub['pnl'].sum()
    print(f"\n{horizon}:")
    print(f"  交易: {n} 笔")
    print(f"  均值: {mean_ret:+.2f}%")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  总盈亏: {total_pnl:+,.0f}")

# ── 月度分布 ──
df['month'] = df['date'].str[:7]
print(f"\n月度分布:")
monthly = df[df['horizon'] == 'T+20'].groupby('month').agg(
    trades=('ret_pct', 'count'),
    mean_ret=('ret_pct', 'mean'),
    total_pnl=('pnl', 'sum')
)
for m, row in monthly.iterrows():
    print(f"  {m}: {int(row['trades']):>3} 笔, 均值 {row['mean_ret']:+.2f}%, 总 {row['total_pnl']:+,.0f}")

# ── 保存 ──
out = BASE / f"data/derived/backtest_bzgc_{'pe' if args.pe_filter else 'nope'}_{START.strftime('%Y%m')}_{END.strftime('%Y%m')}.csv"
df.to_csv(out, index=False)
print(f"\n详细交易明细: {out}")
