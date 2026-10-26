# 当前治理风险证据协议（governance-risk-v1）

本模块只计算**单列的当前治理风险分**，不覆盖 annual/quarter/composite 原分、不修改策略资格。不联网、不生成生产样本、不从缺失文件或缺失公告推导“无风险”。结构化证据必须经上游人工/可审计流程核实；代码验证结构、口径、日期和规则，不能验证公告内容真伪。

## 当前数据覆盖与接入边界

本轮实现规则引擎、财报 API 接入、股票分析页两卡及证据弹窗；**未完成全市场目标治理证据采集**。现有公司整体质押统计和2026年混合关联交易明细均不得替代本协议指标，生产缺少已审计记录时必须显示未评估，不能据此给出正常或完整调整分。红色、完整调整分及各种边界的合成测试数据仅存于测试临时环境，不作为真实公司结论。

财报 API 会将关联销售证据年度与该股票已加载的最近完整年报对齐：若证据不属于该年度，仅在本次评估的副本上标记 `stale`，不改写源文件、不回写历史财务评分。季度报表不作为此年度基准。若财报仓库没有可识别完整年报，本检查不自行猜测应有年度，仍由证据校验和原财务分可用性门控。

## 接口与读取路径

```python
build_governance_risk(base_score, evidence=None, as_of=None) -> dict
load_governance_evidence(symbol, root=None) -> dict | None
```

`symbol` 必须是六位 ASCII 数字字符串。`root` 是**项目根目录**，默认由模块路径推导。只读 `root/data/external_risk/governance_evidence/<symbol>.json`。缺失、不可读、坏 JSON、非对象、非有限 JSON 常量、可选 `symbol` 与文件名不符，均返回 `None`，不创建目录/文件。空对象可以读取，但评估仍为未评估。生产默认不提供 fixtures。

`as_of` 为 ISO 日期字符串或 `datetime.date`；省略使用本机当天日期。无效截止日期拒绝评估，未来指标/核查日期/来源拒绝；显式 `stale: true` 拒绝。**不附加任何固定天数过期规则**。这不是历史 PIT 数据抓取器；上游仍应提供适用于截止日的证据快照。

## 固定响应

```text
{
 version: "governance-risk-v1",
 original_score: 原样回传输入，计算不修改,
 adjusted_score: number | null,
 complete: boolean,
 items: [大股东质押项, 关联销售项]
}
```

每项固定字段：

|字段|含义|
|---|---|
|`code`|`major_shareholder_pledge` / `related_sales`|
|`title`|中文标题|
|`ratio_pct`|已核验分子÷分母×100；未知 `null`|
|`level`|`normal/watch/high/critical/unavailable`|
|`label`|`正常/注意/高关注/极高风险/未评估`|
|`color`|normal 蓝 `blue`；watch/high 黄 `yellow`；critical 红 `red`；unavailable 灰 `gray`|
|`deduction`|`0/5/10/20/null`，只取本项最高等级一次，不叠加同项红规则|
|`complete`|比例有效且本项两条红规则均完整核查|
|`reason`|中文说明；已知红色且未解除仍提示，覆盖不完整明确说明升级未完整评估|
|`evidence`|指标与规则中有效来源的去重数组；不是捏造或默认来源|
|`details`|有效比例的分子、分母、计算口径、主体、范围、报告期、币种和单位；比例未知为空对象|
|`rule_results`|固定两条规则的结果数组，见下|
|`highly_pledged`|质押比例≥80 的描述性标记，不升级到 critical|
|`high_dependence`|关联销售≥50 的描述性标记，不升级到 critical|

`rule_results[]` 固定含 `code, evaluated, triggered, reason, evidence`；通常另有 `details`（核查日期、主体/范围、事件条件、解除状态，逾期规则含有效应收证据）。`evaluated` 严格 boolean；`triggered` 为 true/false/null。**没有证据为 evaluated=false，不是假装已排除。** 已确认红事件却宣称解除而没有有效解除来源，仍 `triggered=true`，但 `evaluated=false`，禁止输出 adjusted_score。

输入分必须是有限原生 int/float、0–100（bool、字符串不接受）。0 是合法分。只有原分有效、两项均完整才计算 `max(0, original_score - sum(两项扣分))`；否则 `adjusted_score=null, complete=false`。比例有效但红规则未覆盖时保留比例级别，不能把不完整误标正常结论；已知 critical 即使比例未知仍显示 critical，但不出调整分。

## 输入 evidence schema

顶层是对象，可选 `symbol`，两项键为固定 code。每项：

```text
{
 ratio: RatioEvidence | null,
 rules: {
   <规则code>: RuleEvidence,
   <第二规则code>: RuleEvidence
 }
}
```

### 来源 Source（任何核查包括负向核查都必须提供）

```text
{url: "https://真实来源URL", title: "真实公告/报告标题", date: "YYYY-MM-DD"}
```

URL 仅接受 http/https，标题非空，日期不晚于截止日；规则来源不晚于规则 as_of。来源应来自真实公告、报告或有效核查记录，模块**不生成真实来源记录**。测试中的 `example.invalid` 明确是合成来源，不写入生产。前端必须用 textContent/安全 DOM 构造展示文本，链接再次只允许 http/https，不把 evidence/title/reason 当 HTML 执行。

### RatioEvidence（每项指标）

公共必填：

```text
numerator: 有限非负数（不是 bool/字符串）
denominator: 有限正数
metric: 项目code
numerator_basis, denominator_basis: 见下表
subject: 非空实际主体名
scope: 见下表
period_end: "YYYY-MM-DD"
period_type: "annual"（关联销售必须；质押为时点数据可注明 snapshot）
currency: 双方统一币种，质押用 "shares"
unit: 双方统一计量单位（如 元/万元/股/万股）
numerator_currency, denominator_currency: 必须与 currency 相同
numerator_unit, denominator_unit: 必须与 unit 相同
complete: true
sources: 非空 Source[]
```

|项目|metric|分子口径|分母口径|scope|
|---|---|---|---|---|
|大股东质押|`major_shareholder_pledge`|`pledged_shares`|`held_shares`|`major_shareholder`|
|关联销售|`related_sales`|`related_sales`|`operating_revenue`|`consolidated`|

质押是**明确一名大股东的质押股数/该股东持股数**，不是公司总质押量/总股本，更不能将 overall 原始字段当个人指标。上游应对适用的大股东核查完整性负责，本版输入不自动拼接不同股东、也不自动选择最危险股东。关联销售是完整年报同年合并口径销售收入/营业收入，排除采购、担保、资金往来等混合关联交易。关联销售 period_end 必须为年末 12-31，来源发表日不得早于该期年末。分子不得大于分母。`source_basis` 若显式为 `overall/mixed` 直接拒绝；scope/metric/分子分母口径错误同样拒绝。原始 overall 4220、混合关联字段 85715 **不能直接映射成有效比例**。

可选 `numerator_period_end/denominator_period_end`、`numerator_subject/denominator_subject`、`numerator_scope/denominator_scope` 若提供必须与公共字段一致；没有这些扩展字段时公共元数据是对分子分母共同口径的明确声明，不能据此把错期数据拼接。币种单位不转换，不同币种或元/万元混用拒绝。

### RuleEvidence（四条红规则共用核查头）

```text
evaluated: true
complete: true
event_present: true | false  # 必须显式；false 表示已据来源完整核查无该事件
as_of: "YYYY-MM-DD"
subject: 实际主体（比例给出主体时须一致）
scope: major_shareholder | consolidated  # 按所属项目
sources: 非空 Source[]
```

`event_present=false` 是上游有证据的完整负向核查，不允许把“没搜到/字段缺失/仅有询问”写成 false。`event_present=true` 时，下面条件必须逐项有证据支持，否则不完整、不自动红。询问/调查/媒体不构成正式认定；若只提供这些材料，按规则未完整评估处理，不假装完成排雷。

确认事件通用解除字段：`status: "unresolved" | "resolved"`。resolved 必须另有非空有效 `resolution_sources: Source[]`，解除来源不得早于事件来源。没有有效解除证据，不因 status 字面值或时间流逝自行消警。对于重大收入违规，resolved 的业务含义是**已经纠正且影响已消除**；对于质押，是偿付/处置或控制权风险已经解除；不能只因部分整改就填写 resolved。

#### 质押规则 1：`pledge_default`

```text
document_kind: "announcement"
financing: "pledge"
default_confirmed: true
status: "unresolved"
```

已公告质押融资违约，偿付/处置未解决 -> critical。

#### 质押规则 2：`pledge_forced_disposal`

```text
document_kind: "announcement"
financing: "pledge"
disposal_started: true
control_risk_explicit: true
disposal_shares: 有限正数股数（不是 bool/字符串）
status: "unresolved"
```

质押融资强制处置已启动、公告明确控制权风险、未解除，并有处置股数证据 -> critical。仅高质押、预警、诉讼或传闻不满足。

#### 关联销售规则 1：`related_overdue`

```text
status: "unresolved"
receivables: RatioEvidence的同类结构，但：
  metric = numerator_basis = "related_trade_receivables_overdue_gt_180"
  denominator_basis = "operating_revenue"
  scope = "consolidated"
  days_basis = "overdue"
  days_operator = ">"
  days_threshold = 180   # 严格原生整数
```

关联销售≥50%，并且同年完整年末**逾期大于180天的关联贸易应收**/当年营业收入≥10%，且未解决 -> critical。不是账龄180天/一年以上，不是逾期≥180，不是所有关联应收。receivables 的主体、范围、年末、币种、单位、营业收入分母必须与关联销售比例逐一相同；仍要求完整年报、来源、分子分母币种单位。应收/营收可超过100%（这里不强行截断）。已完整核查但任一比例阈值未达到，不升级且可标记核查完成；逾期口径不明则不完整。

#### 关联销售规则 2：`related_misstatement`

```text
document_kind: "regulatory_decision" | "audit_report"
material: true
related_revenue: true
finding: "false_revenue" | "improper_recognition"
status: "unresolved"
```

正式监管认定或审计报告明确重大关联收入虚假/不当确认，且未纠正/影响未消除 -> critical。不依赖比例已知，不因高依赖本身变红。历史已解除不继续红；单有 inquiry/investigation/media 不红。

## 冻结阈值与验证

- 质押 `<30 normal; <50 watch; 其余 high`；≥80 仅 highly_pledged。
- 关联销售 `<10 normal; <30 watch; 其余 high`；≥50 仅 high_dependence。
- 两项同样 `normal0 / watch5 / high10 / critical20`；单项多个红事件只扣20，两个项目分别扣分。
- 无数据：两项 unavailable/gray/扣分null，四条规则 evaluated=false，调整分null。

测试以 unittest 逐行为 RED→GREEN 开发，所有合成 fixtures 在测试函数或 TemporaryDirectory 中，不写生产目录。日志及接口摘要见 `/tmp/governance_core_result.json`。

```bash
/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python -m unittest discover -s tests -p test_governance_risk.py -v
```
