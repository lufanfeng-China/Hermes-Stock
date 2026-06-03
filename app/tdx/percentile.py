"""Stock price percentile computation."""
import json
import subprocess

TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"

def compute_stock_price_percentile(
    market: str, symbol: str, *, years: int = 5
) -> dict[str, object]:
    """
    Compute where the latest close sits in the stock's own N-year price history.

    Uses all available local .day records from TDX up to `years`, then computes
    empirical percentile = % of historical closes <= latest close.
    Returns bands: 极低(<20%) / 低(20-40%) / 中(40-60%) / 高(60-80%) / 极高(>80%).
    """
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")
    if market not in {"sh", "sz", "bj"}:
        raise ValueError(f"unsupported market: {market}")

    import subprocess as _subprocess

    script = r"""
import json, sys, statistics, pandas as pd

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
tdxdir = sys.argv[3]
years  = int(sys.argv[4])

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily  = reader.daily(symbol=symbol)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found for " + symbol)

daily.index = daily.index.astype("datetime64[ns]")
daily = daily.sort_index()

# Keep only the last N years
cutoff = daily.index[-1] - pd.DateOffset(years=years)
recent = daily[daily.index >= cutoff].copy()

if len(recent) < 30:
    raise RuntimeError(f"only {len(recent)} trading days in {years}-year window for {symbol}")

prices = recent["close"].dropna().tolist()
latest  = prices[-1]

# Empirical percentile
below  = sum(1 for p in prices if p <= latest)
pct    = below / len(prices) * 100

if   pct < 20: band = "极低"
elif pct < 40: band = "低"
elif pct < 60: band = "中"
elif pct < 80: band = "高"
else:          band = "极高"

# Also compute min/max/mean/std
mean_price = statistics.mean(prices)
std_price  = statistics.stdev(prices) if len(prices) > 1 else 0

print(json.dumps({
    "ok": True,
    "symbol": symbol,
    "market": market,
    "years": years,
    "bar_count": len(prices),
    "window_start": str(recent.index[0].date()),
    "window_end":   str(recent.index[-1].date()),
    "latest_close": round(float(latest), 2),
    "price_percentile": round(pct, 2),
    "price_band": band,
    "price_min":  round(float(min(prices)), 2),
    "price_max":  round(float(max(prices)), 2),
    "price_mean": round(float(mean_price), 2),
    "price_std":  round(float(std_price), 2),
}, ensure_ascii=False))
""".strip()

    result = _subprocess.run(
        ["/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python", "-c", script,
         symbol, market, "/mnt/c/new_tdx64", str(years)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mootdx error")
    return json.loads(result.stdout)

