#!/usr/bin/env python3
"""ID1 价格突破20日均线：当前 CSI300 成分股回溯（2012 起）。
Close signal / next-open entry and close exit signal / next-open exit.
"""
import json
import sys
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, "/home/lufanfeng")
import run_id1_2012_report as core

PROJECT = Path(__file__).resolve().parents[1]
CONSTITUENTS = PROJECT / "data/derived/datasets/final/csi300_constituents_current_20260728.json"
OUT = Path("/mnt/c/Users/Sky.Lu/Desktop/output/价格突破20日均线_CSI300_2012起_含成本_T1退出_20260731_v1")


def main():
    codes = set(json.loads(CONSTITUENTS.read_text(encoding="utf-8")))
    if len(codes) != 300:
        raise RuntimeError(f"Expected 300 current CSI300 constituents, got {len(codes)}")

    paths = []
    for code in sorted(codes):
        market = "sh" if code.startswith("6") else "sz"
        path = Path(core.TDX, "vipdoc", market, "lday", f"{market}{code}.day")
        if path.is_file():
            paths.append(str(path))
    if len(paths) != 300:
        raise RuntimeError(f"Expected 300 current CSI300 .day files, found {len(paths)}")

    with Pool() as pool:
        raw = list(pool.imap_unordered(core.process_path, paths, chunksize=8))
    errors = [x for x in raw if x and x[0] == "ERR"]
    usable = [x for x in raw if x and x[0] != "ERR"]
    if errors:
        raise RuntimeError(f"usable={len(usable)}, errors={len(errors)}")
    trades = [trade for _, stock_trades in usable for trade in stock_trades]
    latest = max(day for day, _ in usable)
    metrics = core.metrics(trades)
    report = {
        "report_version": "v1",
        "strategy": {
            "id": 1,
            "name": "价格突破20日均线",
            "entry_signal": "close 上穿 MA20；MA20 > 5日前 MA20；volume > VMA20；20日平均成交额>=5000万元。",
            "entry": "信号日收盘确认，下一交易日开盘买入。",
            "exit": "close<EMA10，或 close<入场后峰值close-3*ATR14，或连续两日close<MA20，或close<入场价-2*入场日ATR14，或收盘亏损<=-20%；条件触发后下一交易日开盘卖出。",
        },
        "universe": {
            "membership": "2026-07-28 当前 CSI300 300 只成分股的历史价格回溯样本，不是历史时点成分股。",
            "constituent_count": len(codes),
            "usable_daily_files": len(usable),
            "date_range": f"2012-01-01 to {str(latest)}",
            "price_basis": "本地 TDX 原始未复权日线",
        },
        "costs": {"buy_commission": 0.0003, "buy_slippage": 0.001, "sell_commission": 0.0003, "sell_slippage": 0.001, "sell_stamp_duty": 0.0005},
        "portfolio_model": "逐日等权活跃仓位收益袖套；现金收益为0；无资金、持仓数量及同日选股排序约束。",
        "metrics": metrics,
        "errors": errors,
        "limitations": ["当前 CSI300 成分回溯有幸存者偏差。", "原始未复权日线会受除权除息影响。", "不含涨跌停可成交性、停牌、冲击成本、最小佣金和资金容量约束。", "仅已完成交易纳入；期末未平仓交易未计入。"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    m = metrics
    text = f'''ID1 价格突破20日均线：当前 CSI300 成分股历史回溯（2012起）v1

期间：2012-01-01 至 {latest}
股票池：当前 CSI300 300 只成分股；本地可用日线 {len(usable)} 只。
注意：使用当前成分股回溯，存在幸存者偏差。

信号：{report['strategy']['entry_signal']}
入场：{report['strategy']['entry']}
退出：{report['strategy']['exit']}
成本：买卖佣金各0.03%、买卖滑点各0.10%、卖出印花税0.05%。

已平仓交易：{m['trades']}
首/末活跃日：{m['first_active_date']} / {m['last_active_date']}
CAGR：{m['cagr']:.2%}
最大回撤：{m['max_drawdown']:.2%}
夏普：{m['sharpe']:.4f}
Calmar：{m['calmar']:.4f}
胜率：{m['win_rate']:.2%}
盈亏比：{m['payoff']:.4f}
年换手率（双边）：{m['annual_turnover']:.2f}
平均持有期（交易日）：{m['average_holding_trading_days']:.2f}
平均/中位单笔净收益：{m['mean_trade_return']:.2%} / {m['median_trade_return']:.2%}
期末等权袖套净值：{m['portfolio_end_value']:.6f}

局限性：
''' + "\n".join(f"- {x}" for x in report["limitations"]) + "\n"
    OUT.with_suffix(".txt").write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(OUT), "metrics": metrics, "errors": len(errors)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
