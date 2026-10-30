# 生命周期阶段历史（stage_history）

## 是什么

全市场每只 A 股、每个交易日的生命周期阶段快照，由**通达信前复权日线**计算，严格只用当日及以前的 bar（无未来数据）。

- 数据：`data/derived/datasets/final/stage_history.parquet`
- 清单：`data/derived/datasets/final/stage_history.manifest.json`（行数、日期范围、阈值快照、对拍结果、陈旧源检查）
- 当前版本：12,504,445 行 / 5,408 只 / 2012-04-06 .. 2026-10-29 / 319 MB（zstd）

## 字段

| 字段 | 含义 |
|---|---|
| market / symbol | 市场（sh/sz/bj）与 6 位代码 |
| trading_day | 交易日 `YYYY-MM-DD`（**仅真实成交日**，停牌占位行不入库） |
| region / stage | 区域与阶段（见下） |
| ma5/ma10/ma20/ma60 | 前复权收盘均线（3 位小数） |
| slope20 / slope60 | MA20/MA60 相对 5/10 个 bar 的涨幅（5 位小数） |
| slope20_prev | 5 个 bar 前的 MA20 斜率，用于「刚拐头」判定 |
| bias20 | 收盘对 MA20 乖离率 |
| pos_high_60 / pos_low_60 | 收盘相对 60 日最高/最低的位置 |
| vol_ratio | 当日量 / 前 5 日均量 |
| high_20 / low_20 / high_60 / low_60 | 区间高低点 |

文件**不含前瞻收益**——那是未来信息，只能在评估脚本里临时计算，不允许落进特征文件。

## 阶段定义（v1，阈值未调）

- 下跌区：D1 破位下跌、D2 主跌、D3 下跌中继
- 底部区：B1 底部盘整、B2 探底回升、B3 回踩确认
- 上升区：U1 上升初期、U2 主升、U3 上升中继、U4 加速赶顶
- 顶部区：T1 高位震荡

阈值：`FLAT_SLOPE=0.005`、`BIAS_CLIMAX=0.18`、`VOL_BREAKOUT=1.5`、`MIN_DAYS=60`（见 `app/stage_classify.py`）。

## 两条实现，必须逐 bar 一致

| 路径 | 用途 | 文件 |
|---|---|---|
| 标量 `classify_stage(df)` | 股票分析页当日快照 | `app/stage_classify.py` |
| 序列 `classify_stage_series(df)` | 全市场历史建库 | `app/stage_classify_series.py` |

序列版**必须**沿用标量版的 running-sum 累加顺序。pandas 的 rolling mean 与标量累加在浮点末位不同，而阶段规则里全是 `ma5 > ma10`、`slope60 <= FLAT_SLOPE` 这类等号比较，A 股（尤其北交所）均线相等极常见；换成 pandas 算法后 132,724 个 bar 里有 123 处翻转。

## 闸门（都在脚本内，不靠人记）

1. **陈旧源阻断**：QFQ 最新 bar ≠ RPS 最新交易日 → 直接退出，不写文件
2. **对拍闸门**：随机抽 30 只、近 3 年逐 bar 比对标量与序列实现，任一分歧 → 拒绝写盘
3. **数据质量闸门**：统计脚本若算出非有限的前瞻收益（如 0 价当分母）→ 拒绝写报告
4. **原子落盘**：`.tmp` + `os.replace`

## 停牌占位行（重要）

通达信前复权导出把停牌日写成 0.00 价行。400 只抽样中 13 只有，单只最多 1,158 行。

保留这些行会拉坏 MA20/MA60、60 日高低区间与量比，凭空造出阶段。`prepare_bars()` 在**两条路径**都先剔除，占位日返回 `valid=False` 且不位移后续 bar；全量建库因此剔除 73,508 行。

## 命令

```bash
# 对拍（真实数据，约 3 分钟）
~/.venvs/moontdx-china-stock-data/bin/python scripts/check_stage_series_parity.py --stocks 200 --years 3

# 建库（约 5 分钟，含陈旧源检查与对拍闸门）
~/.venvs/moontdx-china-stock-data/bin/python scripts/build_stage_history.py

# 描述性统计（约 4 分钟，报告写桌面 output）
~/.venvs/moontdx-china-stock-data/bin/python scripts/report_stage_history_stats.py

# 人工抽检（每阶段 5 只，回算并打印证据）
~/.venvs/moontdx-china-stock-data/bin/python scripts/spotcheck_stage_samples.py --per-stage 5
```

## 已审计结论（2026-10-30）

**站得住的部分**
- 对拍：132,724 bar，region/stage/evidence 全 0 差异
- 抽检：55 个样本（每阶段 5 只）回算 0 不一致，D 区样本确为空头排列、负斜率、贴近 60 日低位
- 持续性：除 B2/D1 外，自持率 56.6%–83.7%，是阶段而非噪声标签

**标签名大于规则的四处（待定义，未改）**
1. **B1 底部盘整**：`region=base` 只要求 MA60 上行且收盘在其下方，样本 002605 乖离 MA20 +11.3%、pos60 距高点 −37%，实为「上行趋势回抽」
2. **U2 主升**：up 区默认兜底，样本 601319 收盘低于 MA20、均线纠缠、bias20 −0.9% 仍标主升
3. **T1 高位震荡**：`region=top` 只要求 MA60 走平向下且收盘仍在其上，样本 600528 pos60 仅 23%、距 60 日高点 −10%
4. **B2 探底回升 / D1 破位下跌**：中位持续 1.51 / 2.79 bar（B2 中位 1 bar），本质是「当日事件」，不是可停留的阶段

**阶段与前瞻收益不单调（描述性，非策略）**

全市场 20 日均值：D1 +3.27%、D2 +3.13%、D3 +2.60% 最高；B2 +0.92%、U3 +0.69%、B3 +0.52% 最低。20 日中位数：U4 −3.50%、U3 −1.50%、U2 −1.16%，而 D2 +1.29%。

说明：分类器在下跌发生后标「主跌」，天然吃均值回复；U4 均值正而中位大负，是右尾极厚（连板结构）。该表仅证明标签描述价格结构，**不能**当收益排序或选股依据。

## 已知边界

- 样本为当前在市股票，存在幸存者偏差；QFQ 导出不含已退市标的
- 重叠样本，未扣费税滑点，不能相加
- 持续天数以 bar 计，跨停牌日是连续行但仍算一次转换
- 阶段为当日快照，不是预测
