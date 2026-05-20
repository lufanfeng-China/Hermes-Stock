# 技术面评估系统 — 完整开发文档 v2

> 最后更新：2026-05-18
> 状态：待确认后开发

---

## 1. 系统定位

在现有 **财务评分**（公司好不好）的基础上，增加 **技术面评估**（时机对不对）。
两者互补，可在筛选器中组合使用。

---

## 2. 数据来源

完全复用现有通达信本地数据，不引入新数据源：

| 数据 | 来源 | 说明 |
|------|------|------|
| 日线 OHLCV | 通达信 `vipdoc/*/lday/*.day` | 250 个交易日 |
| RPS20/50/120/250 | `dataset_stock_rps_history.json` | 已有全市场截面排名 |
| 5年价格分位 | `dataset_price_percentile_5y.json` | 上一轮刚建的 |
| 均线 MA20/50/120/250 | 日线 close 计算 | 实时算，不存储 |

---

## 3. 四维评估

### 维度一：趋势 📈

**计算：** 取最近一个交易日收盘，计算 MA20、MA50、MA120、MA250。

| 判定 | 条件 | 含义 |
|------|------|------|
| 🟢 多头排列 | MA20 > MA50 且 MA50 > MA120 且 MA120 > MA250 | 趋势健康向上 |
| 🟡 震荡 | 不满足多头也不满足空头 | 方向不明 |
| 🔴 空头排列 | MA20 < MA50 且 MA50 < MA120 且 MA120 < MA250 | 趋势向下 |

**边缘情况：** 若交易日不足 250 天（新股），降级为 🟡 震荡。

### 维度二：动强 🚀

**计算：** 读取已有 `rps_120` 值。若无 RPS 数据则回退看 60 日价格涨跌幅。

| 判定 | 条件 | 含义 |
|------|------|------|
| 🟢 强势 | RPS120 ≥ 70 | 强于全市场 70% 的股票 |
| 🟡 中性 | RPS120 30-70 | 随大流 |
| 🔴 弱势 | RPS120 < 30 | 弱于全市场 70% 的股票 |

**回退逻辑：** 若 RPS120 不可用，用 `(今日收盘 / 60日前收盘 - 1) * 100` 替代：
- 涨幅 > 同市场均值 → 🟢 强势
- 涨幅 < 同市场均值-10% → 🔴 弱势
- 其他 → 🟡 中性

### 维度三：量能 📊

**计算：**
- `量比` = 今日成交量 / 近20日均量
- `5日价格变化` = (今日收盘 / 5日前收盘 - 1) 的正负

| 判定 | 条件 | 含义 |
|------|------|------|
| 🟢 放量配合 | 量比 > 1.2 且 5日涨 | 资金流入，价量齐升 |
| 🟡 正常 | 量比 0.6-1.2 | 交易平稳 |
| 🔴 量价背离 | (量比 > 1.2 且 5日跌) 或 (量比 < 0.4 且 5日涨超 3%) | 放量跌/缩量拉 |

### 维度四：位置 📍

**计算：** 读取已有 `price_percentile_5y` 值。

| 判定 | 条件 | 含义 |
|------|------|------|
| 🟢 低位 | 分位 ≤ 25% | 处于5年历史低位 |
| 🟡 中位 | 分位 25-75% | 中间位置 |
| 🔴 高位 | 分位 > 75% | 处于5年历史高位 |

**回退逻辑：** 若 5年分位不可用，用 `(今日收盘 / 250日最高 - 1)` 替代：
- 距高点 < -30% → 🟢
- 距高点 > -10% → 🔴
- 中间 → 🟡

---

## 4. 买入触发信号

4 维评估回答「值不值得看」，买入信号回答「今天能不能买」。
**触发信号每日计算，只在满足当天条件时点亮**。

### 信号A：突破买入 🟢

```
条件（全部满足）：
  趋势 ≠ 🔴（非空头）
  今日收盘 > MA20
  昨日收盘 ≤ MA20 × 1.01（昨日在MA20附近或下方）
  量比 > 1.2（放量突破）

结论：今日放量突破20日均线，短线转强
```

### 信号B：回踩买入 🟢

```
条件（全部满足）：
  趋势 = 🟢（多头排列）
  今日收盘距 MA20 在 -3% ~ 0% 之间（回踩到均线附近）
  量比 < 0.9（缩量回踩）

结论：多头趋势中缩量回踩均线，经典买点
```

### 信号C：金叉买入 🟢

```
条件（全部满足）：
  今日 MA20 > MA50（短期均线上穿长期）
  昨日 MA20 ≤ MA50（昨日还在下方或持平）
  趋势 = 🟢 或 🟡（非空头）

结论：20日均线上穿50日均线，趋势可能反转走强
```

### 信号D：强势突破 🟢

```
条件（全部满足）：
  趋势 = 🟢（多头排列）
  动强 = 🟢（强势）
  今日收盘 = 近20日最高（创新高）
  量比 > 0.8（非缩量创新高）

结论：强势股继续突破，动量确认
```

---

## 5. 综合结论

决策树 — 按优先级从上到下匹配：

```
1. 有买入触发(ABCD任一) 且 趋势≠🔴
   → 🟢 买入信号
      描述：「今日触发X信号」

2. 4维全🟢 但无买入触发
   → 🟡 等待买点
      描述：「各方面都健康，等待突破/回踩等买入信号」

3. 趋势=🟢 且 动强≠🔴 且 量能≠🔴 且 位置=🟢
   → 🟡 左侧观察
      描述：「趋势健康且处于低位，可加自选等触发信号」

4. 趋势=🔴 或 动强=🔴
   → 🔴 建议回避
      描述：「趋势或动量走弱，暂不建议参与」

5. 其他
   → 🟡 观望持有
      描述：「信号不明确，已持有不动、未持有等待」
```

---

## 6. 输出格式

### 6.1 单只股票输出

```
{stock_name}  {market}:{symbol}
──────────────────────────────────────
📈 趋势   {🟢/🟡/🔴} {多头排列/震荡/空头排列}
   {一句话证据，如「MA20>MA50>MA120>MA250」}

🚀 动强   {🟢/🟡/🔴} {强势/中性/弱势}
   {一句话证据，如「RPS120=85，全市场前15%」}

📊 量能   {🟢/🟡/🔴} {放量配合/正常/量价背离}
   {一句话证据，如「近5日量比1.35，价量齐升」}

📍 位置   {🟢/🟡/🔴} {低位/中位/高位}
   {一句话证据，如「5年分位0.5%，历史底部」}

──────────────────────────────────────
{如有买入触发}
⚡ 买入信号  🟢 {突破买入/回踩买入/金叉买入/强势突破}
   {触发原因描述}

──────────────────────────────────────
综合  {🟢买入信号/🟡等待买点/🟡左侧观察/🟡观望持有/🔴建议回避}
{一段话解释为什么是这个结论，以及下一步建议}
```

### 6.2 预计算 JSON

单文件：`data/derived/datasets/final/dataset_technical_eval.json`

```json
{
  "data_date": "2026-05-15",
  "stocks": {
    "603986": {
      "symbol": "603986",
      "stock_name": "兆易创新",
      "trend": "bullish",
      "trend_label": "多头排列",
      "trend_detail": "MA20(380.2)>MA50(365.1)>MA120(340.8)>MA250(310.5)",
      "momentum": "strong",
      "momentum_label": "强势",
      "momentum_detail": "RPS120=98",
      "volume_signal": "normal",
      "volume_label": "正常",
      "volume_detail": "量比0.95",
      "position": "high",
      "position_label": "高位",
      "position_detail": "5年分位100%",
      "buy_trigger": null,
      "buy_trigger_label": null,
      "buy_trigger_detail": null,
      "conclusion": "hold_watch",
      "conclusion_label": "观望持有",
      "conclusion_color": "yellow",
      "conclusion_reason": "趋势动量好，但价格处于5年最高位，追高风险大"
    }
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `trend` | string | `bullish` / `neutral` / `bearish` |
| `momentum` | string | `strong` / `neutral` / `weak` |
| `volume_signal` | string | `bullish` / `normal` / `divergence` |
| `position` | string | `low` / `mid` / `high` |
| `buy_trigger` | string\|null | `breakout` / `pullback` / `golden_cross` / `strong_break` / null |
| `conclusion` | string | `buy` / `wait_buy` / `left_observe` / `hold_watch` / `avoid` |
| `conclusion_color` | string | `green` / `yellow` / `red` |

### 6.3 筛选器输出

在现有筛选器每行中加入以下字段（作为 `build_stock_screener_response` 行字段）：

```json
{
  "tech_trend": "bullish",
  "tech_trend_label": "多头排列",
  "tech_momentum": "strong",
  "tech_momentum_label": "强势",
  "tech_volume_signal": "normal",
  "tech_volume_label": "正常",
  "tech_position": "low",
  "tech_position_label": "低位",
  "tech_conclusion": "wait_buy",
  "tech_conclusion_label": "等待买点",
  "tech_conclusion_color": "yellow",
  "tech_buy_trigger": null,
  "tech_buy_trigger_label": null
}
```

### 6.4 筛选器下拉条件

在 `stock-screener.html` 中「技术面」分组：

```html
<fieldset class="filter-group">
  <legend>技术面（信号灯）</legend>
  <label><select name="tech_trend">
    <option value="">趋势：不限</option>
    <option value="bullish">🟢 多头排列</option>
    <option value="!bearish">🟢🟡 非空头</option>
  </select></label>
  <label><select name="tech_momentum">
    <option value="">动量：不限</option>
    <option value="strong">🟢 强势</option>
    <option value="!weak">🟢🟡 非弱势</option>
  </select></label>
  <label><select name="tech_volume">
    <option value="">量能：不限</option>
    <option value="bullish">🟢 放量配合</option>
    <option value="!divergence">🟢🟡 非背离</option>
  </select></label>
  <label><select name="tech_position">
    <option value="">位置：不限</option>
    <option value="low">🟢 低位</option>
    <option value="!high">🟢🟡 非高位</option>
  </select></label>
  <label><select name="tech_conclusion">
    <option value="">综合：不限</option>
    <option value="buy">🟢 买入信号</option>
    <option value="!avoid">🟢🟡 非回避</option>
  </select></label>
  <label><select name="tech_buy_trigger">
    <option value="">买入触发：不限</option>
    <option value="breakout">突破买入</option>
    <option value="pullback">回踩买入</option>
    <option value="golden_cross">金叉买入</option>
    <option value="strong_break">强势突破</option>
    <option value="any">有任意买入信号</option>
  </select></label>
</fieldset>
```

筛选逻辑：`tech_trend=!bearish` 表示趋势不是空头（即🟢或🟡），后端匹配 `trend != "bearish"`。

---

## 7. 实现文件清单

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `scripts/build_technical_eval.py` | 新建 | 预计算脚本，遍历全市场，输出 JSON |
| 2 | `data/derived/datasets/final/dataset_technical_eval.json` | 生成 | 预计算结果 |
| 3 | `app/search/index.py` | 修改 | 新增加载器 + 筛选器行字段 + 筛选逻辑 |
| 4 | `app/search/index.py` | 修改 | `build_stock_screener_response` 新增 `tech_*` 字段到每行 |
| 5 | `web/stock-screener.html` | 修改 | 新增「技术面」筛选分组 |
| 6 | `web/stock-screener.js` | 无需改 | FormData 自动收集新字段 |

---

## 8. 性能预估

| 步骤 | 耗时 |
|------|------|
| 读取 5000 只 × 250 日线 | ~60s（mootdx Reader） |
| 计算各维度 + 决策 | ~15s |
| 写入 JSON | ~3s |
| **合计** | **~80s** |

建议每日盘后 cron 执行一次。

---

## 9. 后续可扩展

- `web/technical-score.html`：独立的单只股票技术面详情页（含雷达图）
- 技术面历史：存每日快照，可回溯「当时的技术信号是什么」
- 与财务评分交叉：列出「财务A + 技术🟢」的股票
- 买入信号历史胜率统计
