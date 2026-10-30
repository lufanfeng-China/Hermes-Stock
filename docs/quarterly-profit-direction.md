# 季度扣非利润方向口径

适用：季度监测、核心增长质量、利润相关预警、好股低估季度动量。年度五完整年报健康评分不变。

## 公式与证据

利润同比变化率 = (本期累计扣非利润 − 上年同期累计扣非利润) / abs(上年同期累计扣非利润) × 100%。

此修正仅适用于扣非利润；营收、经营现金流及资本开支原公式不在本次修改范围。比较必须为同季累计，不能跨期或以单季替换累计。最新期缺字段不回退旧期。

- 上期为零：同比百分比为 null；用实际金额比较利润方向，不制造无穷大或零增长率。
- 任期缺失或非有限值：方向 unavailable，状态“数据不足”，不能用零填充。
- 不设置小基数截断阈值；展示两期金额，防止只看百分比。
- 利润金额严格增加才满足利润改善项；持平不算改善。
- 仍须同时满足原有营收正增长、盈利能力稳定或改善条件。减亏或扭亏不自动让整股动量通过。

利润状态包括增盈、盈利下滑、减亏、亏损扩大、扭亏、盈转亏、持平。亏到零属于减亏；零到正属于增盈；正到零属于盈利下滑；零到负属于亏损扩大。

`profit_comparisons.ex_net_profit` 同时保留 current/previous/delta/yoy_pct、两个 period、status/label/direction/formula。该证据必须穿过压缩财务快照，并原样进入 `quarterly_momentum.evidence.profit_change`。行业不适用或 TTM 输入不足时可展示已知金额证据，但不得伪造适用评分或整体改善。

计算版本：`quarterly-v2-profit-direction`、`good-stock-quarterly-momentum-v2-profit-direction`。

## 当前快照更新

使用项目 moontdx venv，先构建本页财务，再构建诊断清单：

```sh
/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python scripts/build_good_stock_financial_snapshot.py
/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python scripts/build_good_stock_undervaluation_current.py
```

数据更新工作台提供上述两项独立任务。修复不得把本页混报告期 latest 快照覆盖到严格同周期行业排名文件；已有历史派生归档不因本次当前口径修复而自动追溯重写。

验收应包括：负/正/零/缺失及非有限值、七状态与边界、真实财报样本、原始仓独立 oracle、年度结果逐股哈希不变、API/浏览器及全量筛选。针对性回归通过不代表全项目套件通过。
