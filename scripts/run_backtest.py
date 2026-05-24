#!/usr/bin/env python3
"""
Signal-driven stock screening backtest engine.

Daily screening → next-day open buy → check 5 exit rules daily → track trades.
"""
import json
import sys
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── Config holder ────────────────────────────────────────────────────────────

class BacktestConfig:
    def __init__(self, args):
        self.strategy = getattr(args, 'strategy', None)
        self.filters_json = getattr(args, 'filters', None)
        self.start_date = args.start
        self.end_date = args.end
        self.stop_loss = getattr(args, 'stop_loss', None)
        self.take_profit = getattr(args, 'take_profit', None)
        self.ma_period = getattr(args, 'ma_period', None)
        self.trailing_pct = getattr(args, 'trailing_pct', None)
        self.max_hold_days = getattr(args, 'max_hold_days', 20)
        self.max_holdings = getattr(args, 'max_holdings', 10)
        self.tdxdir = getattr(args, 'tdxdir', r'/mnt/c/new_tdx64')
        self.output = getattr(args, 'output', None)


# ── Data loading ─────────────────────────────────────────────────────────────

def load_trading_days():
    """Load all trading days from RPS history dataset."""
    path = PROJECT_ROOT / "data" / "derived" / "datasets" / "final" / "dataset_stock_rps_history.json"
    if not path.exists():
        raise FileNotFoundError(f"RPS history not found: {path}")
    with open(path) as f:
        data = json.load(f)
    return sorted({str(r["trading_day"]) for r in data if r.get("trading_day")})


def get_next_trading_day(day, trading_days):
    for d in trading_days:
        if d > day:
            return d
    return None


# ── K-line helpers ───────────────────────────────────────────────────────────

def get_or_load_kline(reader, symbol, cache):
    key = symbol
    if key not in cache:
        daily = reader.daily(symbol=symbol)
        if daily is None or daily.empty:
            cache[key] = {}
        else:
            daily = daily.sort_index()
            bars = daily.to_dict("records")
            cache[key] = {str(b.get("date", ""))[:10]: b for b in bars}
    return cache[key]


def find_bar(klines, date_str):
    return klines.get(date_str)


def is_limit_up(symbol, day, cache, reader):
    """Check if stock hit limit-up on signal day (next-day buy may fail)."""
    klines = get_or_load_kline(reader, symbol, cache)
    bar = find_bar(klines, day)
    if not bar:
        return False
    pre_close = bar.get("pre_close", 0)
    if pre_close <= 0:
        return False
    limit_up = round(pre_close * 1.1, 2)
    close = bar.get("close", 0)
    high = bar.get("high", 0)
    return close >= limit_up * 0.995 or high >= limit_up * 0.995


def get_open_price(symbol, date_str, cache, reader):
    klines = get_or_load_kline(reader, symbol, cache)
    bar = find_bar(klines, date_str)
    if bar and bar.get("open", 0) > 0:
        return bar["open"]
    return None


# ── Exit rule checks ─────────────────────────────────────────────────────────

def check_ma_stop(pos, day, klines, ma_period=10):
    """Close < MA(N) → trigger."""
    bars = get_recent_bars(klines, day, ma_period)
    if len(bars) < ma_period:
        return False
    ma = sum(b["close"] for b in bars[-ma_period:]) / ma_period
    today = find_bar(klines, day)
    return today and today["close"] < ma


def check_trailing_stop(pos, day, klines, trailing_pct=0.10):
    """Close below (peak × (1 - trailing_pct)) → trigger."""
    peak = pos.get("peak_since_entry", pos["buy_price"])
    today = find_bar(klines, day)
    if not today:
        return False
    if today["high"] > peak:
        peak = today["high"]
        pos["peak_since_entry"] = peak
    return today["close"] < peak * (1 - trailing_pct)


def get_recent_bars(klines, day, count):
    sorted_dates = sorted(klines.keys())
    result = []
    for d in sorted_dates:
        if d <= day:
            result.append(klines[d])
    return result[-count:] if len(result) >= count else result


def check_exits(day, positions, trades, cache, reader, config):
    """Check all positions against exit rules (priority: 1-stop 2-profit 3-MA 4-trailing 5-expire)."""
    to_remove = []
    for pos in positions:
        klines = get_or_load_kline(reader, pos["symbol"], cache)
        bar = find_bar(klines, day)
        if not bar:
            continue

        high = bar.get("high", 0)
        low = bar.get("low", 0)
        close = bar.get("close", 0)
        hold_days = (datetime.strptime(day, "%Y-%m-%d") -
                     datetime.strptime(pos["buy_date"], "%Y-%m-%d")).days

        exit_price = None
        exit_reason = None

        # 1. Fixed stop loss (intraday low triggers)
        if config.stop_loss is not None and low > 0 and low <= pos["stop_loss_price"]:
            exit_price = pos["stop_loss_price"]
            exit_reason = "stop_loss"

        # 2. Fixed take profit (intraday high triggers)
        elif config.take_profit is not None and high > 0 and high >= pos["take_profit_price"]:
            exit_price = pos["take_profit_price"]
            exit_reason = "take_profit"

        # 3. MA stop (close triggers)
        elif config.ma_period is not None and check_ma_stop(pos, day, klines, config.ma_period):
            exit_price = close
            exit_reason = "ma_stop"

        # 4. Trailing stop (close triggers)
        elif config.trailing_pct is not None and check_trailing_stop(pos, day, klines, config.trailing_pct):
            exit_price = close
            exit_reason = "trailing_stop"

        # 5. Expiry
        elif hold_days >= config.max_hold_days:
            exit_price = close
            exit_reason = "expired"

        if exit_price:
            ret = round((exit_price - pos["buy_price"]) / pos["buy_price"], 4)
            trades.append({
                "symbol": pos["symbol"],
                "name": pos["name"],
                "market": pos.get("market", ""),
                "signal_date": pos["signal_date"],
                "buy_date": pos["buy_date"],
                "buy_price": pos["buy_price"],
                "sell_date": day,
                "sell_price": exit_price,
                "return": ret,
                "hold_days": hold_days,
                "exit_reason": exit_reason,
                "stop_loss_price": pos.get("stop_loss_price"),
                "take_profit_price": pos.get("take_profit_price"),
            })
            to_remove.append(pos)

    for pos in to_remove:
        positions.remove(pos)


def force_close_all(positions, trades, last_day, cache, reader):
    for pos in list(positions):
        klines = get_or_load_kline(reader, pos["symbol"], cache)
        bar = find_bar(klines, last_day)
        close = bar.get("close", 0) if bar else pos["buy_price"]
        hold_days = (datetime.strptime(last_day, "%Y-%m-%d") -
                     datetime.strptime(pos["buy_date"], "%Y-%m-%d")).days
        ret = round((close - pos["buy_price"]) / pos["buy_price"], 4)
        trades.append({
            "symbol": pos["symbol"],
            "name": pos["name"],
            "market": pos.get("market", ""),
            "signal_date": pos["signal_date"],
            "buy_date": pos["buy_date"],
            "buy_price": pos["buy_price"],
            "sell_date": last_day,
            "sell_price": close,
            "return": ret,
            "hold_days": hold_days,
            "exit_reason": "force_close",
            "stop_loss_price": pos.get("stop_loss_price"),
            "take_profit_price": pos.get("take_profit_price"),
        })
    positions.clear()


# ── Screening ────────────────────────────────────────────────────────────────

def get_candidates(day, config):
    """Run screener for the given day, return candidate stock list."""
    from app.search.index import build_stock_screener_response

    params = {}
    if config.strategy:
        params["strategy"] = config.strategy
    elif config.filters_json:
        params.update(json.loads(config.filters_json))
    else:
        return []

    params["as_of_date"] = day
    params["page_size"] = str(config.max_holdings * 3)

    result = build_stock_screener_response(params)
    return result.get("rows", [])


# ── Summary stats ────────────────────────────────────────────────────────────

def compute_summary(trades):
    if not trades:
        return {"total_trades": 0}

    returns = [t["return"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    sorted_returns = sorted(returns)
    mid = len(sorted_returns) // 2
    median = sorted_returns[mid] if len(sorted_returns) % 2 else (
        sorted_returns[mid - 1] + sorted_returns[mid]) / 2

    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    hold_days = [t.get("hold_days", 0) for t in trades]

    reasons = {}
    for t in trades:
        r = t.get("exit_reason", "unknown")
        reasons[r] = reasons.get(r, 0) + 1

    # Return distribution buckets
    buckets = {"<-10%": 0, "-10~-5%": 0, "-5~0%": 0, "0~5%": 0,
               "5~10%": 0, "10~20%": 0, "20~30%": 0, ">30%": 0}
    for r in returns:
        pct = r * 100
        if pct < -10:
            buckets["<-10%"] += 1
        elif pct < -5:
            buckets["-10~-5%"] += 1
        elif pct < 0:
            buckets["-5~0%"] += 1
        elif pct < 5:
            buckets["0~5%"] += 1
        elif pct < 10:
            buckets["5~10%"] += 1
        elif pct < 20:
            buckets["10~20%"] += 1
        elif pct < 30:
            buckets["20~30%"] += 1
        else:
            buckets[">30%"] += 1

    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(returns), 4),
        "avg_return": round(sum(returns) / len(returns), 4),
        "median_return": round(median, 4),
        "max_return": round(max(returns), 4),
        "min_return": round(min(returns), 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "profit_factor": round(
            abs(avg_win * len(wins) / (avg_loss * len(losses))) if losses else 999, 2),
        "avg_hold_days": round(sum(hold_days) / len(hold_days), 1),
        "exit_reasons": reasons,
        "return_distribution": buckets,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Signal-driven stock screening backtest")
    parser.add_argument("--strategy", help="Preset strategy name")
    parser.add_argument("--filters", help="Custom filter JSON string")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--stop-loss", type=float, default=-0.08, help="Stop loss ratio")
    parser.add_argument("--take-profit", type=float, default=0.20, help="Take profit ratio")
    parser.add_argument("--ma-period", type=int, default=None, help="MA stop period (None=disabled)")
    parser.add_argument("--trailing-pct", type=float, default=None, help="Trailing stop % (None=disabled)")
    parser.add_argument("--max-hold-days", type=int, default=20, help="Max holding days")
    parser.add_argument("--max-holdings", type=int, default=10, help="Max concurrent positions")
    parser.add_argument("--tdxdir", default=r"/mnt/c/new_tdx64")
    parser.add_argument("--output", help="Output JSON path")
    args = parser.parse_args()

    if not args.strategy and not args.filters:
        print("Error: must provide --strategy or --filters")
        sys.exit(1)

    config = BacktestConfig(args)

    # Load trading days
    trading_days = load_trading_days()
    signal_days = [d for d in trading_days if args.start <= d <= args.end]

    if not signal_days:
        print(f"No trading days in range {args.start} ~ {args.end}")
        sys.exit(1)

    print(f"Backtest: {args.start} ~ {args.end}")
    print(f"Signal days: {len(signal_days)}")
    print(f"Config: stop_loss={args.stop_loss}, take_profit={args.take_profit}, "
          f"ma={args.ma_period}, trailing={args.trailing_pct}, "
          f"max_hold={args.max_hold_days}d, max_pos={args.max_holdings}")

    # Mootdx reader
    from mootdx.reader import Reader
    reader = Reader.factory(market="std", tdxdir=config.tdxdir)

    positions = []
    trades = []
    kline_cache = {}
    in_position_symbols = set()

    for i, day in enumerate(signal_days):
        # Step 1: Check exits
        check_exits(day, positions, trades, kline_cache, reader, config)
        in_position_symbols = {p["symbol"] for p in positions}

        # Step 2: Skip if at capacity
        if len(positions) >= config.max_holdings:
            continue

        # Step 3: Run screening
        try:
            candidates = get_candidates(day, config)
        except Exception as e:
            print(f"  [{i+1}/{len(signal_days)}] {day} — screening error: {e}")
            continue

        if not candidates:
            continue

        # Step 4: Find next trading day for buy
        next_day = get_next_trading_day(day, trading_days)
        if not next_day:
            continue

        # Step 5: Filter + open positions
        opened = 0
        for c in candidates:
            symbol = str(c.get("symbol", ""))
            if not symbol or symbol in in_position_symbols:
                continue

            # Skip limit-up stocks
            try:
                if is_limit_up(symbol, day, kline_cache, reader):
                    continue
            except Exception:
                pass

            # Get next-day open price
            try:
                buy_price = get_open_price(symbol, next_day, kline_cache, reader)
            except Exception:
                continue
            if not buy_price:
                continue

            pos = {
                "symbol": symbol,
                "name": str(c.get("stock_name", symbol)),
                "market": str(c.get("market", "")),
                "signal_date": day,
                "buy_date": next_day,
                "buy_price": buy_price,
                "stop_loss_price": round(buy_price * (1 + config.stop_loss), 2) if config.stop_loss is not None else None,
                "take_profit_price": round(buy_price * (1 + config.take_profit), 2) if config.take_profit is not None else None,
                "peak_since_entry": buy_price,
            }
            positions.append(pos)
            in_position_symbols.add(symbol)
            opened += 1

            if len(positions) >= config.max_holdings:
                break

        if opened:
            print(f"  [{i+1}/{len(signal_days)}] {day} → signal={len(candidates)}, "
                  f"opened={opened}, holding={len(positions)}")

    # Force close remaining positions
    force_close_all(positions, trades, signal_days[-1], kline_cache, reader)

    # Summary
    summary = compute_summary(trades)

    result = {
        "config": {
            "strategy": config.strategy,
            "filters": config.filters_json,
            "start_date": config.start_date,
            "end_date": config.end_date,
            "stop_loss_pct": config.stop_loss,
            "take_profit_pct": config.take_profit,
            "ma_period": config.ma_period,
            "trailing_pct": config.trailing_pct,
            "max_hold_days": config.max_hold_days,
            "max_holdings": config.max_holdings,
        },
        "trades": trades,
        "summary": summary,
    }

    # Output
    output_path = config.output or (
        PROJECT_ROOT / "data" / "derived" / "backtest" /
        f"bt_{config.strategy or 'custom'}_{config.start_date}_{config.end_date}.json"
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(trades)} trades.")
    if trades:
        print(f"  Win rate: {summary['win_rate']:.1%}")
        print(f"  Avg return: {summary['avg_return']:.1%}")
        print(f"  Profit factor: {summary['profit_factor']}")
        print(f"  Max drawdown (per trade): {summary['min_return']:.1%}")
        print(f"  Exit reasons: {summary['exit_reasons']}")
    else:
        print("  (no trades to summarize)")
    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()
