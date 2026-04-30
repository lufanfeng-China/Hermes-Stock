# 细分指标归因层与影响层一体化模板设计

## 1. 目标

本文件用于统一设计：
- 归因层（Attribution Layer）
- 影响层（Impact Layer）
- 两层之间的字段对接、适配关系与落地顺序

目标不是分别写两套互相独立的模板，而是形成一条稳定的数据链路：

1. 指标变化
2. 归因层
3. 影响层
4. 解释层

其中：
- 指标变化：告诉用户“变了多少”
- 归因层：告诉用户“从财务结构上为什么变了”
- 影响层：告诉用户“这意味着什么，会带来什么后果”
- 解释层：告诉用户“业务上可能发生了什么”

核心原则：
- 影响层不能脱离归因层单独存在
- 影响层必须尽量复用归因层输出，而不是重新做一遍判断
- 解释层默认建立在“变化 + 归因 + 影响”之上
- 所有涉及 AI 的内容必须默认空态，不自动生成，只有在用户手工点击后才触发处理，以节省 token

---

## 2. 为什么要统一设计

如果只单独设计影响层，会出现几个问题：

1. 同一指标的口径不稳定
- 一次说“自由现金流下降因为经营现金流下降”
- 一次说“自由现金流下降因为资本开支增加”
- 一次又只说“现金流承压”

2. 影响层容易飘
- 没有归因，就不知道影响究竟来自哪个驱动项
- 用户看到的会是泛化风险，而不是基于数据结构的判断

3. 解释层没法精确落点
- 如果不知道是利润端、回款端、资本开支端还是资产负债端导致变化
- 后面就无法精准决定去公告正文、MD&A 还是财报附注验证什么

所以，正确顺序应为：
- 先给出归因层模板
- 再定义影响层如何消费归因层字段
- 最后再补解释层文本验证

---

## 3. 统一数据链路

建议统一输出结构为：

```json
{
  "indicator_key": "free_cf",
  "indicator_name": "自由现金流",
  "change": {},
  "attribution": {},
  "impact": {},
  "explanation": {}
}
```

其中：

### 3.1 change
负责最基础的数值变化描述：

```json
{
  "current_value": 18.7,
  "previous_value": 52.3,
  "delta_value": -33.6,
  "delta_pct": -64.2,
  "direction": "down"
}
```

### 3.2 attribution
负责财务结构归因：

```json
{
  "template_type": "formula_decomposition",
  "formula": "free_cf = operating_cash_flow - capex",
  "drivers": [
    {
      "field": "operating_cash_flow",
      "label": "经营现金流",
      "current": 80.1,
      "previous": 102.1,
      "delta": -22.0,
      "role": "negative_driver"
    },
    {
      "field": "capex",
      "label": "资本开支",
      "current": 61.4,
      "previous": 49.1,
      "delta": 12.3,
      "role": "negative_driver"
    }
  ],
  "attribution_summary": "自由现金流下降主要由经营现金流减少和资本开支增加共同导致。",
  "evidence_strength": "high",
  "needs_text_validation": false
}
```

### 3.3 impact
负责后果和传导：

```json
{
  "impact_level": "strong",
  "impact_summary": "可支配现金减少，资本配置空间收缩。",
  "impact_positive": [],
  "impact_risks": [
    "分红与回购空间受压",
    "偿债和扩产的内部现金支持减弱"
  ],
  "transmission_path": [
    "自由现金流下降 -> 可支配现金减少 -> 财务弹性下降"
  ],
  "derived_from": ["operating_cash_flow", "capex"]
}
```

### 3.4 explanation
负责业务解释与文本验证。

重要交互规则：
- explanation 属于 AI 层内容
- 默认必须为空态，不在查询后自动生成
- 只有用户显式点击“生成解释”或等价按钮时，才触发 AI 处理
- 若用户未点击，则前端只展示 change / attribution / impact 三层结果

```json
{
  "status": "idle",
  "needs_text_validation": true,
  "validation_sources": ["公告正文", "MD&A", "财报附注"],
  "hypotheses": [
    "可能与扩产项目投入增加有关",
    "也可能与回款放缓导致经营现金流减弱有关"
  ]
}
```

---

## 4. 归因层模板分类

建议把 18 个细分指标的归因模板先分成 4 类。

### Type A: 公式拆解型（formula_decomposition）
适用于可以明确拆分分子/分母或构成项的指标。

适用指标：
- `roe_ex`
- `net_margin`
- `ocf_to_profit`
- `ocf_to_rev`
- `free_cf`
- `ar_to_asset`
- `inv_to_asset`
- `goodwill_ratio`
- `impair_to_rev`

特点：
- 归因最稳
- 影响层最容易直接生成
- 多数情况下 `evidence_strength = high`

### Type B: 同比对比型（period_compare）
适用于同比类指标。

适用指标：
- `revenue_growth`
- `profit_growth`
- `ex_profit_growth`

特点：
- 需要重点展示本期、上年同期、增量
- 适合与利润质量或收入动能影响联动
- 解释层通常需要文本验证

### Type C: 效率错位型（efficiency_misalignment）
适用于“资产/负债/周转天数/效率”变化相对收入、成本或资产基数出现错位的指标。

适用指标：
- `ar_days`
- `inv_days`
- `asset_turn`
- `current_ratio`
- `quick_ratio`
- `debt_ratio`

特点：
- 不一定有单个公式拆分项
- 更适合输出“谁增长得更快/谁覆盖得更弱”
- 影响层通常是现金流、流动性、偿债压力传导

### Type D: 直接读取型（direct_field_signal）
适用于通达信本身已直接给出字段，但仍可结合相关科目做弱归因。

适用指标：
- `roe_pct`
- 某些直接读取的比率字段

特点：
- 归因强度低于公式拆解型
- 影响层可输出，但要偏保守

---

## 5. 影响层如何对接归因层

影响层不应直接读取原始财务字段，而应优先消费归因层输出。

### 5.1 建议的依赖关系

影响层的生成逻辑优先读这些归因字段：
- `template_type`
- `direction`
- `drivers`
- `attribution_summary`
- `evidence_strength`
- `needs_text_validation`

### 5.2 统一映射规则

#### 规则 1：先看指标方向
- `direction = up` 或 `down`
- 结合指标方向偏好（higher better / lower better）转换成“变好 / 变坏”

例如：
- `free_cf` 上升 => 变好
- `ar_days` 上升 => 变坏

#### 规则 2：再看归因驱动项角色
从 `drivers[*].role` 提取：
- `positive_driver`
- `negative_driver`
- `neutral_driver`

用于决定风险是来自：
- 分子走弱
- 分母扩张
- 资本开支抬升
- 负债扩张
- 回款效率下降

#### 规则 3：根据 template_type 选择影响模板
- `formula_decomposition` -> 强依赖财务传导链
- `period_compare` -> 强调增长持续性、预期修正
- `efficiency_misalignment` -> 强调现金占用、周转、偿债或效率压力
- `direct_field_signal` -> 输出保守的中性影响

#### 规则 4：影响层继承证据等级
建议：
- 归因 `evidence_strength = high` -> 影响层可输出 `strong`
- 归因 `evidence_strength = medium` -> 影响层最多 `medium`
- 归因 `needs_text_validation = true` -> 影响层仍可输出，但应加上“需结合正文验证”标记

---

## 6. 统一字段适配表

### 6.1 归因层 -> 影响层 字段映射

| 归因层字段 | 影响层用途 |
|---|---|
| `indicator_key` | 查找该指标的影响模板 |
| `direction` | 判断当前是正向影响还是风险影响 |
| `template_type` | 选择影响生成策略 |
| `drivers` | 决定影响摘要的焦点 |
| `attribution_summary` | 生成 impact_summary 时做压缩或引用 |
| `evidence_strength` | 控制 impact_level 上限 |
| `needs_text_validation` | 透传到 impact / explanation |

### 6.2 影响层对外字段

建议统一：
- `impact_level`
- `impact_summary`
- `impact_positive`
- `impact_risks`
- `transmission_path`
- `derived_from`
- `needs_text_validation`

其中：
- `derived_from` 用于记录影响层是基于哪些驱动项得出的
- 便于前端 tooltip 或 explain chip 展示“影响依据”

---

## 7. 18 个指标的统一对接思路

### 7.1 盈利能力

#### `roe_ex`
- 归因模板：`formula_decomposition`
- 关键 drivers：`ex_net_profit`, `equity`
- 影响层重点：主业资本回报、估值承载、再投资效率

#### `net_margin`
- 归因模板：`formula_decomposition`
- 关键 drivers：`net_profit`, `revenue`
- 影响层重点：利润缓冲、盈利弹性、业绩波动放大或缓释

#### `roe_pct`
- 归因模板：`direct_field_signal`
- 影响层重点：综合股东回报率变化、市场对盈利效率评价

### 7.2 成长能力

#### `revenue_growth`
- 归因模板：`period_compare`
- 关键 drivers：`revenue_current`, `revenue_last_year_same_period`
- 影响层重点：收入动能、规模效应、后续利润基础

#### `profit_growth`
- 归因模板：`period_compare`
- 关键 drivers：`net_profit_current`, `net_profit_last_year_same_period`
- 影响层重点：业绩弹性、利润释放节奏、预期修正

#### `ex_profit_growth`
- 归因模板：`period_compare`
- 关键 drivers：`ex_net_profit_current`, `ex_net_profit_last_year_same_period`
- 影响层重点：主业增长质量、持续性判断

### 7.3 运营效率

#### `ar_days`
- 归因模板：`efficiency_misalignment`
- 关键 drivers：`accounts_receivable`, `revenue`
- 影响层重点：回款风险、坏账风险、现金流承压

#### `inv_days`
- 归因模板：`efficiency_misalignment`
- 关键 drivers：`inventory`, `operating_cost`
- 影响层重点：库存积压、资金占压、减值压力

#### `asset_turn`
- 归因模板：`efficiency_misalignment`
- 关键 drivers：`revenue`, `total_assets`
- 影响层重点：资产利用效率、资本回报率承压或改善

### 7.4 现金流质量

#### `ocf_to_profit`
- 归因模板：`formula_decomposition`
- 关键 drivers：`operating_cash_flow`, `net_profit`
- 影响层重点：利润含金量、利润兑现质量

#### `ocf_to_rev`
- 归因模板：`formula_decomposition`
- 关键 drivers：`operating_cash_flow`, `revenue`
- 影响层重点：收入转现金能力、经营质量

#### `free_cf`
- 归因模板：`formula_decomposition`
- 关键 drivers：`operating_cash_flow`, `capex`
- 影响层重点：资本配置空间、分红/回购/偿债/扩张能力

### 7.5 偿债能力

#### `debt_ratio`
- 归因模板：`efficiency_misalignment`
- 关键 drivers：`total_liabilities`, `total_assets`
- 影响层重点：杠杆、融资脆弱性、偿债压力

#### `current_ratio`
- 归因模板：`efficiency_misalignment`
- 关键 drivers：`current_assets`, `current_liabilities`
- 影响层重点：短期流动性缓冲

#### `quick_ratio`
- 归因模板：`efficiency_misalignment`
- 关键 drivers：`quick_assets`, `current_liabilities`
- 影响层重点：剔除存货后的短期偿债能力

### 7.6 资产质量

#### `ar_to_asset`
- 归因模板：`formula_decomposition`
- 关键 drivers：`accounts_receivable`, `total_assets`
- 影响层重点：应收占压、回款风险

#### `inv_to_asset`
- 归因模板：`formula_decomposition`
- 关键 drivers：`inventory`, `total_assets`
- 影响层重点：库存占压、减值风险

#### `goodwill_ratio`
- 归因模板：`formula_decomposition`
- 关键 drivers：`goodwill`, `total_assets`
- 影响层重点：并购减值敏感度

#### `impair_to_rev`
- 归因模板：`formula_decomposition`
- 关键 drivers：`impairment_loss`, `revenue`
- 影响层重点：资产质量恶化、利润侵蚀

---

## 8. 推荐的后端实现结构

建议新增两个配置层：

### 8.1 归因模板配置
文件建议：
- `app/search/indicator_attribution_templates.py`

负责：
- 定义每个指标的 `template_type`
- 定义 `formula`
- 定义 `driver_fields`
- 定义如何生成 `attribution_summary`

### 8.2 影响模板配置
文件建议：
- `app/search/indicator_impact_templates.py`

负责：
- 针对每个 `indicator_key` + `direction` 生成影响模板
- 允许根据 `template_type` 和 `drivers` 调整文案细节

### 8.3 统一装配器
文件建议：
- `app/search/indicator_analysis_pipeline.py`

负责：
1. 读取 change 数据
2. 调用 attribution builder
3. 将 attribution 输出传给 impact builder
4. 返回统一结构

---

## 9. MVP 落地顺序

建议不要一口气上 18 个指标，先做 6 个归因 + 影响一体化 MVP：

1. `free_cf`
2. `ocf_to_profit`
3. `ocf_to_rev`
4. `debt_ratio`
5. `revenue_growth`
6. `ex_profit_growth`

理由：
- 用户最容易理解
- 财务传导路径最清晰
- 归因层和影响层最容易一体化输出
- 能快速验证整条链路设计是否稳定

---

## 10. 推荐下一步

### Step 1
把归因层模板和影响层模板都先转成 Python 常量配置，不先接 UI。

### Step 2
做 6 个 MVP 指标的一体化输出函数，返回：
- `change`
- `attribution`
- `impact`

### Step 3
在 stock-score 页面里优先选择 1~2 个指标试点展示，例如：
- `free_cf`
- `ocf_to_profit`

### Step 4
稳定后再扩展到全部 18 个指标。

---

## 11. 与现有文档关系

- 本文件是“归因层 + 影响层”的统一设计文档
- 现有 `/docs/indicator-impact-layer-template.md` 更偏影响层单独定义
- 后续建议以本文件为主，影响层文档作为补充参考
