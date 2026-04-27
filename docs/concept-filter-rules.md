# 概念过滤规则 v1

## 目标
为通达信本地概念标签建立一套“可解释、可审计、可归档”的第一版过滤规则，用于：
- 前端默认只展示更干净的核心概念列表
- 将噪声标签从“概念”中剥离出来，转入辅助标签/事件标签/技术标签
- 保留原始数据，不直接物理删除，避免后续回溯困难
- 为后续实现 `core concepts / auxiliary tags / event tags / technical tags` 分层展示做准备

## 结论先行
第一版不建议对原始概念做“直接删除式清洗”，而建议采用：
1. 保留原始 `dataset_stock_concept_current`
2. 新增过滤分类结果字段
3. 前端默认只展示 `keep_core`
4. 其他标签归入辅助桶，必要时可折叠显示

也就是说：
- 原始层：完整保留
- 展示层：过滤后展示
- 研究层：允许回看全部标签

## 当前原始数据问题（基于本地实测）
数据源：
- `data/derived/datasets/final/dataset_concept_dictionary.json`
- `data/derived/datasets/final/dataset_stock_concept_current.json`

本地实测规模：
- 股票概念 current 总行数：166627
- 唯一概念名总数：52775

### 观察到的主要噪声类型
1. 时间戳前缀标签
- 例如：`200706 银行`
- 例如：`20260326 评级系数:4.00 综合评级:增持`

2. 财报/评级类标签
- 例如：`2025三季报:营业收入1.06亿元`
- 例如：`业绩预亏`
- 例如：`综合评级:买入`

3. 解禁/增减持/机构持股类标签
- 例如：`270101解禁3018.06万股`
- 例如：`平安保险持股`
- 例如：`高盛持股`
- 例如：`不可减持(新规)`

4. 技术指标/形态类标签
- 例如：`CCI下穿-100`
- 例如：`KDJ超卖`
- 例如：`MACD低位金叉`
- 例如：`上穿BOLL中轨`
- 例如：`平台整理`

5. 成分/风格/制度归属类标签
- 例如：`罗素大盘`
- 例如：`罗素中盘`
- 例如：`转板A股`
- 例如：`创业板注册制`
- 例如：`融资融券业务`

6. 历史证券简称链条
- 例如：`深发展A<-S深发展A<-深发展A`
- 例如：`*ST一重<-中国一重`

7. 主营业务长描述/经营范围文本
- 通常表现为：
  - 文本极长
  - 含大量分号 `；` / `;`
  - 更像经营范围而不是概念

8. 空值/无意义标签
- 例如：`无`
- 例如：`个人`

## v1 过滤原则

### 原则 1：只过滤“非概念语义”，不破坏真正的主题概念
应该尽量保留：
- 产业链/技术方向：`CPO概念`、`存储芯片`、`低空经济`
- 应用主题：`DeepSeek概念`、`跨境支付CIPS`
- 政策/改革主题：`国企改革`、`一带一路`
- 典型题材概念：`机器人概念`、`人工智能`

### 原则 2：先做“隐藏/分桶”，再考虑“彻底剔除”
第一版推荐动作：
- `keep_core`：保留并在默认 UI 展示
- `hide_from_default_ui`：不在默认概念区展示，但仍保留在原始层/辅助层
- `manual_review`：规则容易误伤的类型，先不自动处理

### 原则 3：高风险词不要直接粗暴正则删除
例如：
- `重组`
- `突破`
- `放量`

这些词在某些标签中是噪声，但在另一些标签中可能是有效主题的一部分。
因此 v1 不建议把这类词做成全局硬删除规则。

## v1 建议分桶

### A. keep_core
定义：真正用于前端默认展示、概念联动分析、热点研究的核心概念。

示例：
- `DeepSeek概念`
- `机器人概念`
- `人工智能`
- `储能`
- `芯片`
- `低空经济`
- `跨境支付CIPS`
- `苹果概念`
- `国企改革`

### B. auxiliary_timestamped
定义：带日期前缀、偏快照/时点说明性质的标签。

示例：
- `200706 银行`
- `20260326 评级系数:4.00 综合评级:增持`

默认动作：
- 不在默认概念区展示
- 保留原始值
- 后续如需可拆出 `event_date` 与 `normalized_name`

### C. auxiliary_financial
定义：财报、评级、业绩预告、收入利润等非概念型标签。

示例：
- `2025三季报:营业收入1.06亿元`
- `业绩预亏`
- `财报亏损`

默认动作：
- 不在默认概念区展示
- 后续单独归入“财务/公告标签”层

### D. auxiliary_shareholder
定义：解禁、增减持、机构持股、监管限制等标签。

示例：
- `解禁3018.06万股`
- `平安保险持股`
- `高盛持股`
- `不可减持(新规)`

默认动作：
- 不在默认概念区展示
- 后续归入“股东结构/交易约束标签”层

### E. auxiliary_technical
定义：技术形态、指标信号、超买超卖、均线/指标事件。

示例：
- `CCI下穿-100`
- `KDJ超卖`
- `MACD低位金叉`
- `平台整理`

默认动作：
- 不在默认概念区展示
- 后续归入“技术标签”层

### F. auxiliary_membership
定义：指数/成分/风格/制度属性标签。

示例：
- `罗素大盘`
- `罗素中盘`
- `转板A股`
- `创业板注册制`
- `融资融券业务`

默认动作：
- 不在默认概念区展示
- 后续归入“风格/成分标签”层

### G. auxiliary_alias
定义：历史简称链条、ST 演化链、旧证券名串。

示例：
- `深发展A<-S深发展A<-深发展A`
- `*ST一重<-中国一重`

默认动作：
- 不在默认概念区展示
- 后续归入“证券历史信息”层

### H. auxiliary_description
定义：主营业务长描述、经营范围、介绍型长文本。

示例特征：
- 含大量 `；` / `;`
- 文本很长
- 更像业务说明而不是概念

默认动作：
- 不在默认概念区展示
- 后续归入“公司业务画像”层

## v1 规则优先级
建议按以下顺序匹配，命中即停止：

1. `drop_empty`
2. `drop_historical_alias`
3. `drop_business_description`
4. `drop_date_prefix`
5. `drop_financial_report`
6. `drop_holding_unlock`
7. `drop_technical`
8. `drop_membership_style`
9. 其余默认 `keep_core`

说明：
- `drop_*` 是规则编号/内部名称，不代表物理删除
- 在实现层应映射到：
  - `filter_decision = keep_core | hide_from_default_ui | manual_review`
  - `filter_bucket = auxiliary_*`

## v1 建议规则表达（安全版）

### 1. 空值/无意义标签
- 精确匹配：`无`
- 精确匹配：`个人`

### 2. 历史简称链条
- 包含：`<-`

### 3. 主营业务长描述
- 包含：`；` 或 `;`
- 或长度超过一定阈值（例如 `>= 40`）并进入人工复核名单

### 4. 时间戳前缀
- 正则：`^(19|20|21|22|23|24|25|26)\d{4}\s*`

### 5. 财报/评级类
建议关键词：
- `评级`
- `目标价`
- `综合评级`
- `营业收入`
- `净利润`
- `扣非`
- `每股收益`
- `一季报`
- `中报`
- `三季报`
- `年报`
- `半年报`
- `业绩预亏`
- `业绩预增`
- `业绩公告预警`
- `财报亏损`

### 6. 解禁/增减持/机构持股类
建议关键词：
- `解禁`
- `增持`
- `减持`
- `持股`
- `万股`
- `亿股`
- `保险持股`
- `知名投行持股`
- `高盛持股`

### 7. 技术信号类
建议关键词：
- `上穿`
- `下穿`
- `BOLL`
- `MACD`
- `KDJ`
- `RSI`
- `CCI`
- `多头排列`
- `平台整理`
- `金叉`
- `死叉`
- `超卖`
- `超买`
- `底背离`

### 8. 成分/风格/制度属性类
建议关键词：
- `罗素`
- `转板A股`
- `注册制`
- `融资融券`
- `沪股通`
- `深股通`

## v1 过滤效果预估（基于本地当前数据）
按上述“安全版”规则估算：

### 行级（stock-concept rows）
- `keep_core`: 120155
- `drop_date_prefix`: 14172
- `drop_financial_report`: 12600
- `drop_technical`: 5666
- `drop_holding_unlock`: 4346
- `drop_empty`: 3991
- `drop_membership_style`: 2678
- `drop_business_description`: 1576
- `drop_historical_alias`: 1443

### 唯一概念名级别
- `keep_core`: 28979
- `drop_date_prefix`: 11609
- `drop_financial_report`: 8885
- `drop_business_description`: 1570
- `drop_historical_alias`: 1443
- `drop_holding_unlock`: 250
- `drop_technical`: 30
- `drop_membership_style`: 7
- `drop_empty`: 2

### 粗略保留率
- 行级保留率约：72.1%
- 唯一概念名保留率约：54.9%

解释：
- 原始概念字典里噪声种类非常多，所以唯一概念名保留率较低是正常的
- 但从“实际股票概念关系”看，仍有约 72% 的行级标签可以保留为核心概念候选

## v1 推荐输出字段
如果后续落代码，建议在标准化结果中增加：
- `concept_name_raw`
- `concept_name_display`
- `concept_filter_version`
- `concept_filter_rule_id`
- `concept_filter_bucket`
- `concept_filter_decision`
- `concept_filter_reason`
- `display_priority`

建议取值：
- `concept_filter_decision`
  - `keep_core`
  - `hide_from_default_ui`
  - `manual_review`

- `concept_filter_bucket`
  - `core`
  - `timestamped`
  - `financial`
  - `shareholder`
  - `technical`
  - `membership`
  - `alias`
  - `description`

## 前端展示口径建议

### 默认股票详情页
只展示：
- `keep_core`

### 可折叠“更多标签”
可按需展示：
- `auxiliary_shareholder`
- `auxiliary_financial`
- `auxiliary_technical`
- `auxiliary_membership`

### 默认不展示
- `auxiliary_alias`
- `auxiliary_description`
- 明显空值/无意义标签

## v1 暂不自动处理的高风险项
以下类型容易误伤，先不做强规则删除，建议保留为 `manual_review`：
- 含 `重组` 的标签
- 含 `突破` 的标签
- 含 `放量` 的标签
- 含 `基因重组`、`重组蛋白` 等生物医药真实术语的标签

原因：
- 这些词在事件标签里可能是噪声
- 但在医药、生物技术、资产主题里也可能是有效概念表达

## 第一版落地建议
建议下一步不是直接改原 parser，而是新增一层：
1. 保持 `app/tdx/parsers.py` 原始解析逻辑不动
2. 新增 `concept_filter_rules.v1.json`
3. 新增过滤函数：`classify_concept_name_v1()`
4. 在 current / dictionary / snapshot 输出中补充过滤字段
5. 前端股票详情页默认只取 `keep_core`

## 本规则的正式结论
1. 通达信原始“概念”标签并不纯粹，混有财报、评级、技术、解禁、历史简称、经营范围等多类非概念信息。
2. 第一版处理应采用“分桶隐藏”而不是“物理删除”。
3. 股票详情默认概念展示应只展示 `keep_core`。
4. `重组 / 突破 / 放量` 等高风险关键词暂不做全局硬过滤，应留待人工复核或更细规则。
5. 后续若落代码，必须把过滤版本号和规则命中原因写入标准化结果，保证可审计。
