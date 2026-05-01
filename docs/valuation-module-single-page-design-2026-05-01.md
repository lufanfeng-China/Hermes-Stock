# 估值模块（单开一页）设计方案

> 参考文档：`估值参考系统_V2.11_单人A股模块化实现版设计文档.docx`
> 适配项目：`/home/lufanfeng/Project-Hermes-Stock`
> 日期：2026-05-01

## 1. 设计目标

为 Project-Hermes-Stock 新增一个独立的个股估值页面，形成与现有：
- 首页（工作台）
- `stock-score.html`（财务评分）
- `rps-pool.html`（RPS / 行业 / K线）

并列的第四个核心页面：
- `valuation.html`（估值模块）

该页面目标不是输出单一 PE 或一个拍脑袋目标价，而是提供：
1. 三视角估值结果
2. 行业模板路由
3. 区间化估值结论
4. 可靠度 / 风险标签 / 失效条件
5. 历史自身估值分位与行业相对分位
6. 规则输出与说明分离

## 2. 参考文档中应继承的核心原则

来自参考文档、且应原样继承到本项目的原则：

1. 不是新模型优先，而是“模块对接方式”优先
- 统一结果结构
- 上下文只读
- 配置一次加载
- 计算层与输出层分离
- 版本兼容

2. 估值过程保持分层
- Step 0：输入与合法性校验
- Step 1：读取数据并生成上下文
- Step 2：三视角并行估值
- Step 3：可靠度与权重修正
- Step 4：自洽性检验与风险分层
- Step 5：输出与历史对比

3. 结果以区间形式输出，而不是单点
- `low / mid / high`
- `output_level`
- `risk_tags`
- `failure_conditions`

4. 计算与展示分离
- 后端返回结构化估值结果
- 前端只负责渲染、交互、切换视图与 drill-down

## 3. 结合当前项目后的总体定位

当前项目已经具备：
- 本地通达信日线与财报
- 申万行业映射
- 财务评分引擎
- RPS / 行业热力图 / K线可视化能力

因此估值页不应从零开始，而应做成：

“财报能力 + 行业模板 + 多估值视角 + 当前价格映射”的独立终端页。

建议页面定位：
- 名称：`Valuation Terminal`
- 中文标题：`个股估值`
- 角色：从“财务评分页”偏质量评分，延伸到“价值区间与定价解释”

## 4. 页面入口与页面命名

### 新页面
- `web/valuation.html`
- `web/valuation.js`

### 顶部导航
建议加到现有 topbar：
- Home
- RPS
- 财务评分
- 估值

### 路由/API
建议新增：
- `GET /valuation.html`
- `GET /api/valuation?market=sh&symbol=600519`
- `GET /api/valuation-history?market=sh&symbol=600519`（二期）
- `GET /api/valuation-compare?market=sh&symbol=600519`（二期）

## 5. 页面结构（单页）

建议单页分为 6 个区块。

### 区块 A：搜索工作台
功能：
- 输入股票代码 / 名称 / market:symbol
- 最近查询
- 快捷股票
- 状态条

沿用现有 `stock-score.html` 的：
- `app-shell`
- `topbar`
- `search-card`
- `search-input-wrap`
- `stock-dropdown`

### 区块 B：估值总览卡
核心显示：
- 当前价
- 基准估值中枢（mid）
- 保守估值（low）
- 乐观估值（high）
- 相对当前价的偏离
- 安全边际
- 输出等级（标准 / 谨慎参考 / 高度谨慎 / 不宜估值）
- 可靠度

建议 4 张卡：
1. 当前价格卡
2. 估值区间卡
3. 估值偏离卡
4. 可靠度 / 风险卡

### 区块 C：三视角估值面板
三视角：
- 盈利视角
- 资产视角
- 收入视角

每个视角显示：
- 视角是否合法
- low / mid / high
- reliability
- method_fitness
- drivers
- notes

### 区块 D：估值方法拆解
展示：
- 行业模板
- 主估值方法
- 辅助估值方法
- 权重修正
- 自洽性检验结果
- dominant_view

### 区块 E：历史分位 / 行业内对照
显示：
- 自身历史估值分位（如 5Y PE percentile）
- 行业内相对分位
- 同行业可比样本摘要
- 可比样本数量 / 质量

### 区块 F：风险标签与失效条件
显示：
- 风险标签（如：高波动、强周期、利润质量存疑、短历史）
- 失效条件
- 使用说明

## 6. 单页交互原则

1. 默认模式
只显示：
- 估值区间
- 当前位置
- 风险标签
- 失效条件
- 主导视角

2. Debug 模式
增加显示：
- data_readiness
- method_fitness
- peer_support
- 权重修正过程
- 可比样本列表
- 字段替代 / 缺失 warning

前端可以用一个简单 toggle：
- `标准`
- `调试`

## 7. 后端总体结构

建议新增目录：
- `app/valuation/`

建议文件：
- `app/valuation/context.py`
- `app/valuation/models.py`
- `app/valuation/config.py`
- `app/valuation/step0_validator.py`
- `app/valuation/data_loader.py`
- `app/valuation/peer_finder.py`
- `app/valuation/views.py`
- `app/valuation/reliability.py`
- `app/valuation/weight_engine.py`
- `app/valuation/self_consistency.py`
- `app/valuation/risk_engine.py`
- `app/valuation/failure_conditions.py`
- `app/valuation/service.py`
- `app/valuation/output.py`

服务入口接入：
- `scripts/serve_stock_dashboard.py`
  - 新增 handler: `handle_valuation(...)`

## 8. 统一数据结构设计

### 8.1 ValuationContext
参考文档建议保留：

```python
@dataclass(frozen=True)
class ValuationContext:
    symbol: str
    market: str
    stock_name: str
    valuation_template_id: str
    short_history: bool
    structural_break_date: str | None
    rate_regime: str
    valuation_date: str
    latest_report_date: str
```

项目适配补充字段：
- `industry_level_1_name`
- `industry_level_2_name`
- `industry_level_3_name`
- `current_price`
- `shares_outstanding`
- `market_cap`

### 8.2 ViewResult
参考文档原样保留：

```python
@dataclass
class ViewResult:
    view_name: str
    low: float | None
    mid: float | None
    high: float | None
    is_valid: bool
    reliability: float | None = None
    method_fitness: float | None = None
    drivers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
```

### 8.3 ValuationResult
建议：

```python
@dataclass
class ValuationResult:
    symbol: str
    market: str
    stock_name: str
    version: str
    output_level: str
    dominant_view: str | None
    final_low: float | None
    final_mid: float | None
    final_high: float | None
    current_price: float | None
    upside_mid_pct: float | None
    margin_of_safety_pct: float | None
    valuation_template_id: str | None
    views: list[ViewResult]
    risk_tags: list[str]
    failure_conditions: list[str]
    methodology_note: str | None
```

## 9. 估值模板路由（最关键）

当前项目文档中已经为行业映射预留了：
- `valuation_template_id`

这是最适合作为估值引擎入口的字段。

### 建议模板
先落 8 类：
- `consumer_quality`
- `cyclical_manufacturing`
- `industrial_metal`
- `utilities_infra`
- `bank`
- `nonbank_finance`
- `healthcare_growth`
- `tech_growth`

### 当前项目可行做法
短期内不必等 parser 全面补齐模板映射，可以先：
1. 若 `valuation_template_id` 已存在，直接使用
2. 若不存在，则根据 `industry_level_1_name / industry_level_2_name` 做 fallback mapping

## 10. 三视角估值方法设计

### 10.1 盈利视角（earnings）
适用最广。

优先方法：
- PE
- E/P
- EV/EBITDA（若可得）
- EV/EBIT（若可得）
- 简化 DCF（成熟行业）

当前项目 V1 建议：
- 以 `PE / E/P / normalized earnings` 为主
- `EV/EBITDA` 先预留结构，等外部数据补齐后启用

### 10.2 资产视角（asset）
适用于金融、重资产、资源、低增长公司。

优先方法：
- PB
- Book Value
- ROE-PB consistency
- Residual Income（金融股）

当前项目 V1 建议：
- 非金融：PB 作为资产锚
- 银行/非银：P/B + ROE 框架

### 10.3 收入视角（revenue）
适用于成长股、早期盈利不稳定、科技/医药。

优先方法：
- PS
- EV/Sales
- EV/Gross Profit

当前项目 V1 建议：
- 先落 `PS / revenue multiple`
- 金融股直接判非法视角

## 11. V1 推荐估值公式（最适合当前项目）

### 11.1 当前价格锚
使用：
- 本地最新日线 close
- 若要扩展再允许实时价做盘中展示层，不进入正式估值结果

### 11.2 三视角 low / mid / high
建议：

#### 盈利视角
- `mid = normalized_eps * target_pe`
- `low = mid * (1 - discount)`
- `high = mid * (1 + premium)`

#### 资产视角
- `mid = bvps * target_pb`
- `low/high` 同理

#### 收入视角
- `mid = revenue_per_share * target_ps`

### 11.3 target multiple 的来源
不要只用静态行业中位数。
建议组合：
1. 自身历史分位
2. 行业内分位
3. 模板默认锚

例如：
- `target_pe = blend(self_hist_pe_anchor, industry_pe_anchor, template_pe_anchor)`

## 12. 权重修正逻辑

参考文档建议保留：
- 合法视角数 < 2 → 单视角参考
- 合法视角数 >= 2 → 等权起步，再做因子修正

### 当前项目适配建议
可直接从现有评分体系复用以下因子：
- `roe_ex`
- `net_margin`
- `revenue_growth`
- `profit_growth`
- `ocf_to_profit`
- `free_cf`
- `debt_ratio`
- `current_ratio`
- `quick_ratio`
- `goodwill_ratio`

用这些给视角加减权：
- 现金流与利润稳定 → 盈利视角加权
- 净资产可信 / 金融属性强 → 资产视角加权
- 高增长 / 利润暂不稳 → 收入视角加权

## 13. 可靠度与输出等级

### 13.1 data_readiness
取决于：
- 是否有最新财报
- 是否有至少 8 个连续自然季度
- 是否有完整行业映射
- 是否有有效当前价格
- 是否有 10Y 国债序列

### 13.2 method_fitness
由模板决定：
- 银行：资产视角高适配，收入视角无效
- 消费龙头：盈利视角高适配
- 高成长：收入视角较高适配

### 13.3 output_level
建议：
- `standard`
- `cautious_reference`
- `highly_cautious`
- `not_estimable`

## 14. 风险标签与失效条件

建议完全沿用参考文档的思路。

风险标签示例：
- `short_history`
- `structural_break`
- `cyclical_peak_risk`
- `cashflow_quality_warning`
- `high_leverage`
- `peer_support_weak`
- `financial_stock_special_case`

失效条件示例：
- 行业监管出现重大不利变化
- 公司发生重大资产重组
- 核心管理层或控股股东发生重大变更
- 最新财报出现盈利逻辑断裂
- 估值基础变量（盈利/净资产/收入）大幅重置

## 15. 单页 API 输出建议

### `GET /api/valuation?market=sh&symbol=600519`

返回：

```json
{
  "ok": true,
  "market": "sh",
  "symbol": "600519",
  "stock_name": "贵州茅台",
  "version": "valuation_v1",
  "valuation_date": "2026-05-01",
  "current_price": 1688.00,
  "valuation_template_id": "consumer_quality",
  "output_level": "standard",
  "dominant_view": "earnings",
  "final_low": 1520.0,
  "final_mid": 1760.0,
  "final_high": 1980.0,
  "upside_mid_pct": 4.27,
  "margin_of_safety_pct": -11.05,
  "views": [
    {
      "view_name": "earnings",
      "low": 1600.0,
      "mid": 1800.0,
      "high": 2000.0,
      "is_valid": true,
      "reliability": 0.82,
      "method_fitness": 0.88,
      "drivers": ["normalized_eps", "target_pe"],
      "notes": ["盈利视角主导"]
    }
  ],
  "risk_tags": ["consumer_valuation_premium"],
  "failure_conditions": ["若未来两个季度利润增速明显失速，则当前PE锚失效"],
  "methodology_note": "盈利/资产/收入三视角融合；行业模板=consumer_quality"
}
```

## 16. 页面 UI 设计建议（单页）

### 视觉语言
必须沿用当前项目成熟风格：
- 深色终端/dashboard 风格
- `app-shell`
- `topbar`
- `search-card`
- `profile-card`
- `metric-card`

不要单独再做一套“传统白底研报风”页面。

### 页面布局
建议：

1. 首屏左侧：搜索工作台
- 查询
- 最近查询
- 快捷股票
- 状态条

2. 首屏右侧：估值总览
- 当前价
- 估值区间
- 安全边际
- 可靠度

3. 第二屏：三视角估值卡
- 盈利
- 资产
- 收入

4. 第三屏：估值方法与风险
- 模板说明
- 权重修正
- 风险标签
- 失效条件

5. 第四屏：历史与相对分位
- 自身历史估值位置
- 行业内相对位置
- 可比样本

## 17. 当前项目最适合的实现顺序

### Phase 1：先把估值页骨架做出来
- 新页面 `valuation.html`
- 新脚本 `valuation.js`
- 新接口 `/api/valuation`
- 先实现搜索 + 结果卡 + 三视角结构

### Phase 2：先落 V1 估值计算
数据只用当前项目已有：
- 本地财报
- 本地日线
- 行业映射
- 已有评分因子

### Phase 3：补市场增强数据
优先补：
- 10Y 国债收益率
- 股息历史
- 更稳定的 PB / PS / 市场横截面估值锚

### Phase 4：补行业专属模板
- 银行
- 非银
- 周期资源
- 高成长科技/医药

## 18. 市场上可直接复用的 skill / 能力统筹结论

当前没有一个“现成即插即用的 A 股估值模块 skill”可以直接替代这项设计。
但最值得复用的 skill 有 4 个：

1. `ashare-monitor-system-design`
- 用于整体页面与引擎分层设计
- 适合定义 Page、API、规则边界

2. `ashare-stock-scoring-framework`
- 用于复用当前已落地的财务质量因子
- 适合作为估值权重修正与质量折价层

3. `writing-plans`
- 用于下一步把本设计拆成实现计划

4. `ocr-and-documents`
- 用于持续吸收你的外部设计文档

因此最佳统筹方案不是“直接套某个 skill”，而是：
- 用外部设计文档定接口边界与结构
- 用 `ashare-stock-scoring-framework` 定质量修正层
- 用 `ashare-monitor-system-design` 定页面与系统边界
- 再单独实现 valuation engine

## 19. 最终建议（拍板版）

我建议你现在就把估值模块定义为：

“独立单页 + 三视角估值 + 行业模板路由 + 区间输出 + 风险与失效条件”

而不是：
- 一个简单 PE/PB 表
- 或把估值混进现有 `stock-score.html`

### 为什么要单开一页
因为估值页的用户问题和评分页不一样：
- 财务评分页回答：这家公司财务质量怎么样
- 估值页回答：这家公司现在值多少钱、价格在哪个区间、为什么这样定价

这两个问题应该分开。

如果你愿意，下一步我可以继续直接给你做两种产出中的一个：

1. 产出“实现级设计”
- 精确到：API 字段、页面区块 id、后端文件路径、模块边界

2. 直接产出“实施计划文档”
- 按你当前项目结构拆成可执行任务
- 例如 `docs/plans/valuation-page-implementation-plan.md`

如果你让我来拍板，我建议下一步做：第 2 个。