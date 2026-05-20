# 技术面评估系统 — v3 方案（融合买入模型 + 现有系统能力）

> 版本：v3
> 基于：用户「买入模型 v3.4」+ 本系统现有数据能力
> 原则：只做数据可支撑的，不做空壳

---

## 1. 能从用户方案中采纳的

| 用户方案要点 | v3 采纳 | 说明 |
|-------------|---------|------|
| 趋势分6级（强多头/多头/修复/震荡/空头/强空头） | ✅ 采纳 | 比v2的3级更细腻 |
| 动强分6级（极强/强势/启动/早期启动/中性/弱势） | ✅ 采纳 | 多RPS窗口综合判断 |
| 量价分级 + 背离检测 | ✅ 采纳 | v2已有，增强K线形态条件 |
| 位置分「低位/中位/高位/过热」 | ✅ 采纳 | 拆分位置和过热风险 |
| 买入信号需满足K线形态条件 | ✅ 采纳 | 收盘位置、上影线比例 |
| ATR动态止损 | ✅ 采纳 | 每个买点输出止损价 |
| 仓位等级联动财务评分 | ✅ 采纳 | 财务分高→仓位可加重 |
| 涨跌停检测（按板块） | ✅ 采纳 | 688/300=20%, BJ=30%, 主板=10% |
| 最近跌停排除 | ✅ 采纳 | 3日内跌停不触发买入 |
| 一字涨停降级 | ✅ 采纳 | 一字板不确认为买点 |
| 市场环境维度 | ❌ 不做 | 需指数日线数据，暂无 |
| 流动性分位 | ❌ 不做 | 需全市场成交额截面 |
| 除权检测 | ❌ 不做 | 无复权数据对照 |
| 止盈预警 | ❌ 不做 | 需持仓追踪系统 |
| 回测验证 | ❌ 不做 | 独立项目，后续考虑 |

---

## 2. 六维评估（采纳版）

### 维度一：趋势

| 等级 | 标签 | 条件 |
|------|------|------|
| strong_bullish | 强多头 | MA20>MA50>MA120>MA250 + close>MA20 + MA20_slope_5>0 + MA50_slope_10>0 |
| bullish | 多头 | MA20>MA50>MA120 + close>MA20 + MA20_slope_5>0 |
| recovering | 修复中 | MA20>MA50 + close>MA20 + MA20上行 + 斜率达标(低价股≥1%,中价≥0.5%,高价≥0.3%) |
| neutral | 震荡 | 不满足上述，也不满足空头 |
| bearish | 空头 | MA20<MA50<MA120 + close<MA50 |
| strong_bearish | 强空头 | MA20<MA50<MA120<MA250 + close<MA20 + MA20_slope_5<0 |

### 维度二：动强

| 等级 | 标签 | 条件 |
|------|------|------|
| super_strong | 极强 | RPS20≥90 且 RPS50≥85 且 RPS120≥80 |
| strong | 强势 | RPS50≥70 且 RPS120≥70 |
| startup | 启动 | RPS20≥80 且 RPS50≥70 且 40≤RPS120<70 |
| early_startup | 早期启动 | RPS20≥80 且 RPS50≥70 且 RPS120<40 |
| neutral | 中性 | 不满足上述，RPS120 30-70 |
| weak | 弱势 | RPS120<30 且 RPS50<50 |

### 维度三：量价

需要新增两个K线形态指标：

```
close_position = (close - low) / (high - low)   # 收盘在日线中的位置，0-1
upper_shadow = (high - max(open, close)) / (high - low)  # 上影线比例
```

| 等级 | 标签 | 条件 |
|------|------|------|
| bullish | 放量配合 | 量比>1.2 + 5日涨 + close_position>0.5 |
| normal | 正常 | 量比 0.6-1.2 |
| low_volume | 缩量 | 量比<0.6 |
| divergence | 量价背离 | (量比>1.2+5日跌) 或 (量比<0.4+5日涨超3%) |

### 维度四：位置

| 等级 | 标签 | 条件 |
|------|------|------|
| low | 低位 | 5年分位 ≤ 25% |
| mid | 中位 | 25% < 分位 ≤ 75% |
| high | 高位 | 分位 > 75% |
| overheated | 过热 | 分位 > 90% + 20日涨幅>30% |
| new_stock | 新股 | 上市<250日，无5年分位 |

---

## 3. 买入触发信号（4种）

每种信号都需要满足：K线形态 + 量能 + 涨跌停检查

### 信号A：放量突破买入

```
条件（全部满足）：
  trend ≠ bearish/strong_bearish
  close > MA20
  昨日 close ≤ MA20 × 1.01
  close > 前10日最高收盘价
  volume_ratio ≥ 1.2
  close_position ≥ 0.65（收盘在日线上部）
  upper_shadow_ratio < 0.40（上影线不过长）
  今日涨幅 ≥ 1% 且 非一字涨停
  最近3日无跌停

止损：
  entry_price = 今日收盘
  ATR止损价 = entry_price - 1.5×ATR14
  结构止损价 = min(MA20×0.97, 今日最低价)
  最终止损取 ATR止损（若ATR数据充足）否则结构止损
  risk_pct = (entry_price - stop_loss) / entry_price
  若 risk_pct > 8% → 降级为 buy_watch
```

### 信号B：多头缩量回踩买入

```
条件（全部满足）：
  trend = bullish/strong_bullish
  今日最低 ≤ MA20 × 1.03（触碰均线附近）
  今日收盘 ≥ MA20 × 0.98
  今日收阳（close ≥ open）且 close > 昨日收盘
  volume_ratio < 0.9
  近5日跌幅不超过 8%
  非一字跌停
  最近3日无跌停

止损：
  entry_price = 今日收盘
  ATR止损价 = entry_price - 1.5×ATR14
  结构止损价 = MA20 × 0.97
  最终止损 = min(ATR止损, 结构止损)
```

### 信号C：金叉观察

```
条件（全部满足）：
  今日 MA20 > MA50
  昨日 MA20 ≤ MA50
  trend ≠ bearish/strong_bearish
  非一字涨停

说明：金叉本身是观察信号，不直接确认为买点。
      需要同时满足突破或回踩条件才升级为确认买入。
      仅金叉 → buy_watch
```

### 信号D：强势突破买入

```
条件（全部满足）：
  trend = bullish/strong_bullish
  momentum = super_strong/strong
  今日收盘 = 近20日最高
  volume_ratio > 0.8
  close_position ≥ 0.5
  非一字涨停

止损：
  entry_price = 今日收盘
  ATR止损价 = entry_price - 1.5×ATR14
  结构止损价 = MA20
```

---

## 4. 综合结论决策树

```
Step 0: 数据不足 → insufficient_data

Step 1: 强制回避
  强空头+弱势 / 一字跌停 / 量价背离且跌幅大 → avoid

Step 2: 确认买入 (buy_confirmed)
  有买入触发(ABCD) + 趋势=强多头/多头
  + 动强≠弱势 + 量能不背离 + 位置≠过热
  + risk_pct≤8% + 最近无跌停
  (recovering趋势触发 → 降为 buy_watch)

Step 3: 买点观察 (buy_watch)
  有买点触发但存在瑕疵：
  - 趋势=修复中 + 突破
  - 风险>8%
  - 位置过热
  - 仅金叉无突破确认
  - 一字涨停
  - 接近涨停(aggressive)

Step 4: 等待买点 (wait_buy)
  趋势好 + 动强好 + 量能OK + 不过热 + 无买点触发

Step 5: 左侧观察 (left_observe)
  位置=低位 + 趋势≠强空头 + 量能不背离

Step 6: 等待回踩 (wait_pullback)
  趋势=强多头/多头 + 动强=极强/强势 + 位置=高位

Step 7: 观望持有 (hold_watch)
  其他情况。位置=过热 → hold_watch

Step 8: 数据不足 (insufficient_data)
  交易日<60
```

结论枚举：

| conclusion | 标签 | 颜色 |
|------------|------|------|
| buy_confirmed | 确认买入 | 🟢 |
| buy_watch | 买点观察 | 🟡 |
| wait_buy | 等待买点 | 🟡 |
| wait_pullback | 等待回踩 | 🟡 |
| left_observe | 左侧观察 | 🟡 |
| hold_watch | 观望持有 | 🟡 |
| avoid | 回避 | 🔴 |
| insufficient_data | 数据不足 | ⚪ |

---

## 5. 仓位等级（与财务评分联动）

在筛选器中，技术面结论和财务评分组合决定仓位建议：

| 技术结论 | 财务总分 | 仓位等级 | 含义 |
|----------|---------|----------|------|
| buy_confirmed | ≥80 | strong | 满仓 |
| buy_confirmed | 60-80 | normal | 标准仓 |
| buy_confirmed | <60 | test | 试探仓 |
| buy_watch | ≥60 | test | 试探仓 |
| buy_watch | <60 | skip | 跳过 |
| wait_buy/wait_pullback | ≥60 | observe | 加入观察 |
| left_observe | ≥40 | observe | 加入观察 |
| 其他 | 任意 | skip | — |

---

## 6. 输出示例

```
兆易创新  603986  SH
──────────────────────────────────────
📈 趋势      强多头
    MA20(380)>MA50(365)>MA120(340)>MA250(310)
    MA20近5日上行2.1%

🚀 动强      极强
    RPS20=98 RPS50=95 RPS120=92

📊 量价      正常
    量比0.95 close_position=0.62

📍 位置      高位
    5年分位100%, 处于历史最高位

──────────────────────────────────────
⚡ 买入信号  无触发
    今日未触发买点。强势股处于历史高位，建议等回踩MA20

──────────────────────────────────────
📋 综合结论  🟡 等待回踩
    趋势极强但价格过高，等待缩量回踩均线后考虑。
    若回调至MA20附近(约365元)且缩量，可关注。

💼 仓位建议  observe（财务78分 → 加入观察）
🛑 参考止损  暂无（无买入信号不输出止损）
```

```
某突破股  601xxx  SH
──────────────────────────────────────
📈 趋势      修复中
    MA20>MA50, MA20近5日上行1.8%, 收盘站上MA20
    MA50仍低于MA120

🚀 动强      启动
    RPS20=86 RPS50=75 RPS120=52

📊 量价      放量配合
    量比1.35 close_position=0.78

📍 位置      低位
    5年分位12%

──────────────────────────────────────
⚡ 买入信号  🟢 放量突破
    放量站上MA20并突破前10日高点，收盘位于日内高位
    买入参考价 12.56  止损价 11.93  风险 5.0%

──────────────────────────────────────
📋 综合结论  🟡 买点观察
    短期正在修复，出现放量突破，但中期趋势尚未确认为多头。
    可小仓位试探，等MA50站稳MA120后再加仓。

💼 仓位建议  test（财务65分 → 试探仓）
🛑 参考止损  11.93（ATR动态止损，跌破即出）
```

---

## 7. 实现计划

### 新建

| 文件 | 内容 |
|------|------|
| `scripts/build_technical_eval.py` | 预计算脚本，输出 dataset_technical_eval.json |
| `data/derived/datasets/final/dataset_technical_eval.json` | 预计算结果 |

### 修改

| 文件 | 变更 |
|------|------|
| `app/search/index.py` | `_load_technical_eval()` 加载器 |
| `app/search/index.py` | `build_stock_screener_response` 新增 tech_* 字段 |
| `app/search/index.py` | 新增技术面筛选逻辑（tech_trend/tech_momentum等下拉） |
| `web/stock-screener.html` | 新增「技术面」筛选分组 |

### 不做（本次）

| 项目 | 原因 |
|------|------|
| 独立技术面详情页 | 先接入筛选器验证效果，后续再加 |
| 市场环境维度 | 缺指数日线数据通道 |
| 除权检测 | 无复权数据 |
| 止盈预警 | 需持仓追踪 |
| 回测 | 独立项目 |

---

## 8. 性能

全市场 ~5000 只 × 250 日数据，预计 **90-120 秒**（增加了 ATR 和 K 线形态计算）。
