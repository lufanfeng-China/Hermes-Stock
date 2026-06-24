"""K-line and historical data loading via mootdx subprocess."""
import json
import subprocess

TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/home/lufanfeng/tdx_data"
DEFAULT_SYMBOL = "601600"
DEFAULT_HISTORY_LIMIT = 120

def infer_market(symbol: str) -> tuple[str, int]:
    if symbol.startswith(("60", "68", "90")):
        return "sh", 1
    if symbol.startswith(("00", "30", "20")):
        return "sz", 0
    raise ValueError(f"unsupported symbol prefix for {symbol}")


def load_stock_history(symbol: str, history_limit: int = DEFAULT_HISTORY_LIMIT) -> dict[str, object]:
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    market, suffix = infer_market(symbol)
    script = r"""
import json
import sys

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
suffix = int(sys.argv[3])
tdxdir = sys.argv[4]
history_limit = int(sys.argv[5])

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily = reader.daily(symbol=symbol)
minute = reader.minute(symbol=symbol, suffix=suffix)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found")
if minute is None or minute.empty:
    raise RuntimeError("minute data not found")

minute = minute.copy()
minute["trading_day"] = minute.index.strftime("%Y-%m-%d")
window_specs = {
    "open_15m_volume": ("09:31:00", "09:45:00"),
    "window_1430_1445_volume": ("14:30:00", "14:45:00"),
}
by_day = {}
for trading_day, day_frame in minute.groupby("trading_day", sort=True):
    metrics = {}
    timestamps = day_frame.index.strftime("%H:%M:%S")
    for indicator_name, (start_ts, end_ts) in window_specs.items():
        selected = day_frame.loc[(timestamps >= start_ts) & (timestamps <= end_ts)]
        metrics[indicator_name] = {
            "volume": int(selected["volume"].fillna(0).sum()),
            "bar_count": int(selected.shape[0]),
        }
    by_day[trading_day] = metrics

rows = []
for index, row in daily.sort_index().iterrows():
    trading_day = index.strftime("%Y-%m-%d")
    metrics = by_day.get(trading_day)
    if not metrics:
        continue
    rows.append(
        {
            "trading_day": trading_day,
            "close": round(float(row["close"]), 4),
            "open_15m_volume": metrics["open_15m_volume"]["volume"],
            "open_15m_bar_count": metrics["open_15m_volume"]["bar_count"],
            "window_1430_1445_volume": metrics["window_1430_1445_volume"]["volume"],
            "window_1430_1445_bar_count": metrics["window_1430_1445_volume"]["bar_count"],
        }
    )

if not rows:
    raise RuntimeError("no overlapping daily/minute history found")

rows = rows[-history_limit:]
latest = rows[-1]
payload = {
    "ok": True,
    "symbol": symbol,
    "market": market,
    "history_limit": history_limit,
    "latest_trading_day": latest["trading_day"],
    "latest_metrics": {
        "open_15m_volume": latest["open_15m_volume"],
        "open_15m_bar_count": latest["open_15m_bar_count"],
        "window_1430_1445_volume": latest["window_1430_1445_volume"],
        "window_1430_1445_bar_count": latest["window_1430_1445_bar_count"],
        "close": latest["close"],
    },
    "history": rows,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [
            TONGDAXIN_PYTHON,
            "-c",
            script,
            symbol,
            market,
            str(suffix),
            TONGDAXIN_DIR,
            str(history_limit),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "unknown subprocess error").strip()
        raise RuntimeError(stderr)
    return json.loads(result.stdout)



def load_stock_kline(symbol: str, *, limit: int = 250) -> dict[str, object]:
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    market, suffix = infer_market(symbol)
    script = r"""
import json
import sys

from mootdx.reader import Reader

symbol = sys.argv[1]
market = sys.argv[2]
suffix = int(sys.argv[3])
tdxdir = sys.argv[4]
limit = int(sys.argv[5])

reader = Reader.factory(market="std", tdxdir=tdxdir)
daily = reader.daily(symbol=symbol)

if daily is None or daily.empty:
    raise RuntimeError("daily data not found")

rows = []
for index, row in daily.sort_index().tail(limit).iterrows():
    rows.append({
        "trading_day": index.strftime("%Y-%m-%d"),
        "open": round(float(row["open"]), 2),
        "high": round(float(row["high"]), 2),
        "low": round(float(row["low"]), 2),
        "close": round(float(row["close"]), 2),
        "volume": int(row["volume"]) if not (row["volume"] != row["volume"]) else 0,
    })

print(json.dumps({"ok": True, "symbol": symbol, "market": market, "bars": rows}, ensure_ascii=False))
""".strip()
    result = subprocess.run(
        [TONGDAXIN_PYTHON, "-c", script, symbol, market, str(suffix), TONGDAXIN_DIR, str(limit)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mootdx subprocess error")
    return json.loads(result.stdout)

