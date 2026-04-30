# 细分指标影响层模板设计

## 1. 目标

在现有“指标变化 → 归因 → 解释”的链路中，正式插入“影响层”，形成统一的 4 层结构：

1. 指标变化
2. 归因
3. 影响
4. 解释

其中：
- 指标变化：回答“变了多少”
- 归因：回答“从财务结构上为什么变了”
- 影响：回答“这意味着什么、会带来什么问题或正面结果”
- 解释：回答“业务层面可能发生了什么”

本文件只定义“影响层模板”，用于后续：
- 后端规则引擎输出
- AI 财报解读增强
- 前端细分指标展开卡片/悬浮说明

---

## 2. 影响层定位

影响层不是“原因”，也不是“结论性经营判断”。

它的职责是：
- 把指标变化转译成用户能理解的后果
- 给出风险传导路径或正面传导路径
- 标注影响强弱与是否需要外部文本验证

示例：
- `free_cf` 下滑不是原因
- “经营现金流下降 + 资本开支上升”是归因
- “分红、回购、扩产和偿债空间受压”是影响
- “可能与扩产项目投入或回款放缓有关”是解释

---

## 3. 建议输出 schema

建议每个指标在影响层输出统一结构：

```json
{
  "indicator_key": "free_cf",
  "indicator_name": "自由现金流",
  "direction": "down",
  "impact_level": "strong",
  "impact_summary": "可自由支配现金减少，资本配置空间收缩。",
  "impact_positive": [
    "若资本开支对应高回报项目，短期承压但中长期可能改善竞争力"
  ],
  "impact_risks": [
    "分红与回购空间受压",
    "偿债和扩产的内部现金支持减弱",
    "若连续多期偏弱，估值可能转向保守"
  ],
  "transmission_path": [
    "现金流下降 -> 可支配现金减少 -> 资本配置约束增强"
  ],
  "needs_text_validation": true,
  "validation_sources": ["公告正文", "MD&A", "财报附注"],
  "evidence_strength": "high"
}
```

字段说明：
- `direction`: `up` / `down` / `flat`
- `impact_level`: `strong` / `medium` / `weak`
- `impact_summary`: 一句话总结
- `impact_positive`: 正向影响列表
- `impact_risks`: 风险影响列表
- `transmission_path`: 传导链路
- `needs_text_validation`: 是否建议结合文本源验证
- `validation_sources`: 需要补充验证的来源
- `evidence_strength`: 当前仅靠结构化数据判断的可信度

---

## 4. 影响层强弱定义

### strong
指标变化与后续财务后果关系非常直接，单靠结构化财务数据即可给出较强判断。

适用例子：
- `free_cf`
- `ocf_to_profit`
- `ocf_to_rev`
- `debt_ratio`
- `goodwill_ratio`
- `impair_to_rev`

### medium
指标变化能较清楚提示潜在后果，但仍需结合行业或正文验证严重程度。

适用例子：
- `revenue_growth`
- `profit_growth`
- `ex_profit_growth`
- `current_ratio`
- `quick_ratio`
- `asset_turn`

### weak
指标变化能提示关注方向，但业务外推性较弱，不能单独下强结论。

适用例子：
- `ar_days`
- `inv_days`
- `ar_to_asset`
- `inv_to_asset`

---

## 5. 按指标定义影响层模板

以下模板中的“变好/变坏”，默认基于当前评分体系方向：
- higher better 为“上升变好”
- lower better 为“下降变好”

### 5.1 盈利能力

#### roe_ex（扣非ROE）
- 变好：
  - `impact_level`: medium
  - 正向影响：主业资本回报改善，利润对股东权益的转化效率提升
  - 风险缓释：估值支撑增强，盈利质量更容易被市场认可
  - 传导链路：扣非回报提升 -> 主业资本效率提升 -> 中长期估值承载力增强
  - `needs_text_validation`: true
- 变坏：
  - `impact_level`: medium
  - 风险影响：主业回报率下行，若持续可能压制估值和资本配置效率
  - 传导链路：扣非回报走弱 -> 权益使用效率下降 -> 估值与再投资效率承压
  - `needs_text_validation`: true

#### net_margin（净利率）
- 变好：
  - `impact_level`: medium
  - 正向影响：收入转利润能力增强，抗收入波动能力提高
  - 传导链路：净利率提升 -> 盈利弹性增强 -> 利润稳定性改善
  - `needs_text_validation`: true
- 变坏：
  - `impact_level`: medium
  - 风险影响：利润空间被压缩，成本、费用或价格压力可能向后续利润传导
  - 传导链路：净利率下降 -> 利润缓冲变薄 -> 业绩波动放大
  - `needs_text_validation`: true

#### roe_pct（净资产收益率）
- 变好：
  - `impact_level`: medium
  - 正向影响：综合股东回报率改善，有利于市场对盈利能力的整体评价
  - `needs_text_validation`: true
- 变坏：
  - `impact_level`: medium
  - 风险影响：资本回报率走弱，若净资产继续扩张而利润跟不上，估值容易承压
  - `needs_text_validation`: true

### 5.2 成长能力

#### revenue_growth（营收增速）
- 变好：
  - `impact_level`: medium
  - 正向影响：需求或业务扩张改善，为利润增长提供基础
  - 传导链路：营收扩张 -> 规模效应释放空间扩大 -> 利润改善潜力上升
  - `needs_text_validation`: true
- 变坏：
  - `impact_level`: medium
  - 风险影响：收入端动能走弱，后续利润增长和费用摊薄能力可能承压
  - 传导链路：营收放缓 -> 规模效应减弱 -> 利润增长承压
  - `needs_text_validation`: true

#### profit_growth（净利润增速）
- 变好：
  - `impact_level`: medium
  - 正向影响：利润释放加快，市场对业绩弹性的预期容易改善
  - `needs_text_validation`: true
- 变坏：
  - `impact_level`: medium
  - 风险影响：利润端承压，若弱于营收增速，说明盈利弹性下降
  - `needs_text_validation`: true

#### ex_profit_growth（扣非净利润增速）
- 变好：
  - `impact_level`: strong
  - 正向影响：主业增长质量提升，利润改善的可持续性更强
  - 传导链路：扣非利润改善 -> 主业盈利增强 -> 市场对持续性更认可
  - `needs_text_validation`: true
- 变坏：
  - `impact_level`: strong
  - 风险影响：主业盈利动能减弱，若与净利润增速背离，需警惕非经常性项目掩盖主业压力
  - 传导链路：扣非利润走弱 -> 主业承压 -> 后续业绩持续性存疑
  - `needs_text_validation`: true

### 5.3 运营效率

#### ar_days（应收周转天数，越低越好）
- 变好（下降）：
  - `impact_level`: medium
  - 正向影响：回款效率提升，经营现金流改善概率上升
  - 传导链路：应收周转加快 -> 现金回笼改善 -> 现金流质量增强
  - `needs_text_validation`: true
- 变坏（上升）：
  - `impact_level`: medium
  - 风险影响：回款周期拉长，坏账风险与现金占用压力上升
  - 传导链路：应收天数上升 -> 现金回笼放慢 -> 经营现金流承压
  - `needs_text_validation`: true

#### inv_days（存货周转天数，越低越好）
- 变好（下降）：
  - `impact_level`: medium
  - 正向影响：库存周转改善，资金占用下降，减值压力缓解
  - `needs_text_validation`: true
- 变坏（上升）：
  - `impact_level`: medium
  - 风险影响：库存积压风险抬升，资金被占用，后续可能传导到减值或毛利压力
  - 传导链路：存货周转放慢 -> 资金占压上升 -> 减值/促销压力增加
  - `needs_text_validation`: true

#### asset_turn（总资产周转率）
- 变好：
  - `impact_level`: medium
  - 正向影响：资产利用效率提高，有利于 ROA/ROE 改善
  - `needs_text_validation`: true
- 变坏：
  - `impact_level`: medium
  - 风险影响：资产扩张效率下降，若收入跟不上资产增速，资本回报率可能继续承压
  - `needs_text_validation`: true

### 5.4 现金流质量

#### ocf_to_profit（净现比）
- 变好：
  - `impact_level`: strong
  - 正向影响：利润含金量提升，盈利兑现为现金的能力增强
  - 传导链路：净现比改善 -> 利润兑现质量提升 -> 财务稳健性增强
  - `needs_text_validation`: false
  - `evidence_strength`: high
- 变坏：
  - `impact_level`: strong
  - 风险影响：利润含金量下降，账面利润与实际现金回笼脱节风险加大
  - 传导链路：净现比下滑 -> 利润兑现能力走弱 -> 后续可持续性和质量受质疑
  - `needs_text_validation`: false
  - `evidence_strength`: high

#### ocf_to_rev（现金流/营收）
- 变好：
  - `impact_level`: strong
  - 正向影响：收入转现金效率提高，经营质量增强
  - `needs_text_validation`: false
  - `evidence_strength`: high
- 变坏：
  - `impact_level`: strong
  - 风险影响：每单位收入产生的现金减少，若持续可能拖累自由现金流和偿债空间
  - `needs_text_validation`: false
  - `evidence_strength`: high

#### free_cf（自由现金流）
- 变好：
  - `impact_level`: strong
  - 正向影响：可支配现金增加，分红、回购、偿债和扩产空间改善
  - 传导链路：FCF 改善 -> 资本配置自由度提升 -> 股东回报与扩张弹性增强
  - `needs_text_validation`: false
  - `evidence_strength`: high
- 变坏：
  - `impact_level`: strong
  - 风险影响：可支配现金减少，分红/回购/降杠杆/扩产空间受压
  - 传导链路：FCF 下滑 -> 可支配现金收缩 -> 财务弹性下降
  - `needs_text_validation`: false（若只判断后果）/ true（若解释业务原因）
  - `evidence_strength`: high

### 5.5 偿债能力

#### debt_ratio（资产负债率，越低越好）
- 变好（下降）：
  - `impact_level`: strong
  - 正向影响：杠杆压力缓解，融资脆弱性下降
  - `needs_text_validation`: false
  - `evidence_strength`: high
- 变坏（上升）：
  - `impact_level`: strong
  - 风险影响：杠杆敏感度提高，融资成本和偿债压力可能上升
  - 传导链路：负债率上升 -> 财务弹性下降 -> 融资与偿债约束增强
  - `needs_text_validation`: false
  - `evidence_strength`: high

#### current_ratio（流动比率）
- 变好：
  - `impact_level`: medium
  - 正向影响：短期流动性缓冲增强
  - `needs_text_validation`: false
- 变坏：
  - `impact_level`: medium
  - 风险影响：短期偿债安全垫变薄，若叠加现金流偏弱，流动性风险加大
  - `needs_text_validation`: false

#### quick_ratio（速动比率）
- 变好：
  - `impact_level`: medium
  - 正向影响：剔除存货后的即时偿债能力改善
  - `needs_text_validation`: false
- 变坏：
  - `impact_level`: medium
  - 风险影响：短期高流动资产对负债覆盖能力减弱，流动性更容易受冲击
  - `needs_text_validation`: false

### 5.6 资产质量

#### ar_to_asset（应收占资产比，越低越好）
- 变好（下降）：
  - `impact_level`: medium
  - 正向影响：资产中应收占比下降，资产质量和现金回收确定性改善
  - `needs_text_validation`: true
- 变坏（上升）：
  - `impact_level`: medium
  - 风险影响：应收占压上升，回款与坏账压力可能加大
  - 传导链路：应收占比上升 -> 资产变现效率下降 -> 现金流承压
  - `needs_text_validation`: true

#### inv_to_asset（存货占资产比，越低越好）
- 变好（下降）：
  - `impact_level`: medium
  - 正向影响：库存占压下降，资产周转与现金效率可能改善
  - `needs_text_validation`: true
- 变坏（上升）：
  - `impact_level`: medium
  - 风险影响：库存占压提升，未来减值和促销去库存压力增加
  - `needs_text_validation`: true

#### goodwill_ratio（商誉占比，越低越好）
- 变好（下降）：
  - `impact_level`: strong
  - 正向影响：并购资产对报表的脆弱性下降，减值敏感度降低
  - `needs_text_validation`: false
  - `evidence_strength`: high
- 变坏（上升）：
  - `impact_level`: strong
  - 风险影响：未来减值风险敏感度上升，利润表波动风险变大
  - 传导链路：商誉占比上升 -> 减值敏感度提高 -> 后续利润稳定性下降
  - `needs_text_validation`: false（后果判断）/ true（并购背景解释）
  - `evidence_strength`: high

#### impair_to_rev（减值损失率，越低越好）
- 变好（下降）：
  - `impact_level`: strong
  - 正向影响：减值压力缓解，利润表拖累减少
  - `needs_text_validation`: false
  - `evidence_strength`: high
- 变坏（上升）：
  - `impact_level`: strong
  - 风险影响：资产质量恶化信号增强，利润表后续承压可能上升
  - 传导链路：减值损失率上升 -> 利润侵蚀加剧 -> 资产质量担忧增强
  - `needs_text_validation`: false（后果判断）/ true（具体减值资产解释）
  - `evidence_strength`: high

---

## 6. 可直接落地的规则分层

### 第一层：硬影响（结构化强结论）
直接基于财务结构就能输出：
- `free_cf`
- `ocf_to_profit`
- `ocf_to_rev`
- `debt_ratio`
- `goodwill_ratio`
- `impair_to_rev`

### 第二层：软影响（结构化中等结论）
可输出较稳的影响，但建议保守措辞：
- `roe_ex`
- `roe_pct`
- `net_margin`
- `revenue_growth`
- `profit_growth`
- `ex_profit_growth`
- `asset_turn`
- `current_ratio`
- `quick_ratio`

### 第三层：提示性影响（弱提示）
适合提示关注方向，不宜单独下重结论：
- `ar_days`
- `inv_days`
- `ar_to_asset`
- `inv_to_asset`

---

## 7. 前端展示建议

### 展示顺序
建议在细分指标展开区按顺序展示：
1. 变化
2. 归因
3. 影响
4. 解释

### 展示形式
影响层建议固定为：
- `影响摘要`：一句话
- `正向影响`：1~2 条
- `风险影响`：1~3 条
- `传导路径`：1 条短链路
- `证据等级`：强/中/弱
- `是否需正文验证`：是/否

### 颜色建议
- 强正向：青绿
- 强风险：橙红
- 中性提示：灰蓝
- 证据等级：
  - 高：实心
  - 中：半实心
  - 低：空心

---

## 8. 后端落地建议

建议新增一层规则模块，例如：
- `app/search/impact_templates.py`
或
- `app/search/indicator_impact.py`

建议提供：
- 指标模板字典
- `build_indicator_impact(indicator_key, current_value, previous_value, raw_context)`
- 输出统一 schema

后续可以先不接 AI，先由规则生成影响层；AI 只在“解释层”补充自然语言。

---

## 9. 第一阶段最小可行版本（MVP）

建议第一阶段先落 6 个最有价值指标：
- `free_cf`
- `ocf_to_profit`
- `ocf_to_rev`
- `debt_ratio`
- `revenue_growth`
- `ex_profit_growth`

原因：
- 用户最容易理解
- 与风险/经营质量/资金弹性最相关
- 结构化判断较稳
- 适合尽快接到现有 stock-score 页面中

---

## 10. 下一步实现建议

### Step 1
先把本文件里的 18 个指标模板，整理成 Python 常量配置。

### Step 2
先实现 6 个 MVP 指标的影响层规则输出。

### Step 3
把影响层挂到：
- 细分指标展开区
- AI 财报解读的结构化输入上下文

### Step 4
后续再补“解释层”的文本源校验。
