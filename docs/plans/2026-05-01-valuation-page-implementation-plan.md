# Valuation Page Implementation Plan

> For Hermes: use subagent-driven-development or Codex to implement this plan task-by-task with strict TDD.

Goal: 为 Project-Hermes-Stock 新增一个独立的“个股估值”页面，提供三视角估值、区间结果、行业模板路由、风险标签与失效条件，并保持与现有 dark terminal/dashboard 风格一致。

Architecture: 沿用当前项目的 stdlib HTTP server + 原生 HTML/CSS/JS 架构。后端新增 `app/valuation/` 模块与 `/api/valuation` 接口；前端新增 `web/valuation.html` 与 `web/valuation.js`，复用现有 `styles.css`、搜索下拉模式、卡片体系与项目导航。估值计算采用“行业模板路由 + 三视角结果 + 权重修正 + 输出分层”的 V1 实现，先使用本地财报、日线与行业映射，不依赖外部数据库。

Tech Stack: Python stdlib server, Python dataclasses, mootdx-backed local TDX data, existing project JSON/parquet datasets, vanilla HTML/CSS/JS, unittest, node --check.

---

## 0. 现有可复用资产（实现前必须理解）

先读这些文件，理解后再动手：

- `docs/valuation-module-single-page-design-2026-05-01.md`
- `docs/industry-concept-schema.md`
- `web/stock-score.html`
- `web/stock-score.js`
- `scripts/serve_stock_dashboard.py`
- `app/search/index.py`
- `tests/test_stock_score_page.py`
- `tests/test_stock_score_ai_report.py`
- `tests/test_rps_page.py`

当前可直接复用的事实：
- 页面壳层：`app-shell`, `topbar`, `search-card`, `profile-card`, `metric-card`
- 搜索模式：输入框 + dropdown + button
- 后端 API 接入模式：`scripts/serve_stock_dashboard.py` 中新增 `handle_*`
- 本地数据能力：
  - 本地通达信日线
  - 本地财报时序/快照
  - 行业映射（含 `valuation_template_id` 设计位）
- 当前现成字段：
  - `dynamic_pe`
  - `a_share_market_cap`
  - RPS 相关字段
  - 财务质量/成长/现金流等评分因子

---

## 1. 功能范围（V1 必须完成）

V1 页面必须回答 5 个问题：
1. 当前价格相对估值区间处于哪里？
2. 这只股票当前属于哪个估值模板？
3. 盈利 / 资产 / 收入 三个视角各给出什么区间？
4. 最终主导视角是什么？
5. 风险标签和失效条件是什么？

V1 不做：
- 外部一致预期接入
- 完整 DCF 模型参数配置器
- 银行/保险/券商专属深度模型
- 历史估值对比接口
- AI 估值解读

V1 只做：
- 单股估值查询
- 三视角区间
- 输出等级
- 风险标签
- 失效条件
- 方法说明

---

## 2. 页面与接口总览

### 页面
- Create: `web/valuation.html`
- Create: `web/valuation.js`

### 后端模块
- Create: `app/valuation/models.py`
- Create: `app/valuation/context.py`
- Create: `app/valuation/config.py`
- Create: `app/valuation/data_loader.py`
- Create: `app/valuation/views.py`
- Create: `app/valuation/weight_engine.py`
- Create: `app/valuation/risk_engine.py`
- Create: `app/valuation/failure_conditions.py`
- Create: `app/valuation/service.py`
- Create: `app/valuation/__init__.py`

### 后端接入
- Modify: `scripts/serve_stock_dashboard.py`

### 测试
- Create: `tests/test_valuation_page.py`
- Create: `tests/test_valuation_service.py`

---

## 3. 数据结构约定（先固定，不允许边写边改）

### 3.1 ValuationContext

放在：`app/valuation/context.py`

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ValuationContext:
    market: str
    symbol: str
    stock_name: str
    valuation_template_id: str
    industry_level_1_name: str
    industry_level_2_name: str
    valuation_date: str
    latest_report_date: str | None
    current_price: float | None
    market_cap: float | None
    dynamic_pe: float | None
    short_history: bool
    structural_break_date: str | None
    rate_regime: str
```

### 3.2 ViewResult

放在：`app/valuation/models.py`

```python
from dataclasses import dataclass, field

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

### 3.3 ValuationResult

同文件：`app/valuation/models.py`

```python
from dataclasses import dataclass, field

@dataclass
class ValuationResult:
    market: str
    symbol: str
    stock_name: str
    version: str
    valuation_date: str
    output_level: str
    dominant_view: str | None
    final_low: float | None
    final_mid: float | None
    final_high: float | None
    current_price: float | None
    upside_mid_pct: float | None
    margin_of_safety_pct: float | None
    valuation_template_id: str | None
    methodology_note: str | None
    views: list[ViewResult] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)
    failure_conditions: list[str] = field(default_factory=list)
```

### 3.4 JSON API 序列化约定

后端最终统一返回：

```json
{
  "ok": true,
  "market": "sz",
  "symbol": "000333",
  "stock_name": "美的集团",
  "version": "valuation_v1",
  "valuation_date": "2026-05-01",
  "current_price": 81.10,
  "valuation_template_id": "consumer_quality",
  "output_level": "standard",
  "dominant_view": "earnings",
  "final_low": 73.2,
  "final_mid": 84.5,
  "final_high": 95.8,
  "upside_mid_pct": 4.19,
  "margin_of_safety_pct": -9.74,
  "methodology_note": "盈利/资产/收入三视角融合；行业模板=consumer_quality",
  "views": [],
  "risk_tags": [],
  "failure_conditions": []
}
```

---

## 4. 估值模板路由规则（V1 固化）

先实现一个最小模板路由函数：
- 输入：`industry_level_1_name`, `industry_level_2_name`, `valuation_template_id`
- 输出：模板 ID

优先级：
1. 使用行业数据里的 `valuation_template_id`
2. 若为空，则按行业 fallback

V1 支持以下模板：
- `consumer_quality`
- `cyclical_manufacturing`
- `industrial_metal`
- `utilities_infra`
- `bank`
- `nonbank_finance`
- `healthcare_growth`
- `tech_growth`
- `generic_equity`（兜底）

建议放在：`app/valuation/config.py`

并以字典配置：

```python
FALLBACK_TEMPLATE_MAP = {
    "家电": "consumer_quality",
    "食品饮料": "consumer_quality",
    "银行": "bank",
    "非银金融": "nonbank_finance",
    "有色": "industrial_metal",
    "公用事业": "utilities_infra",
    "医药医疗": "healthcare_growth",
    "电子": "tech_growth",
    "计算机": "tech_growth",
    "机械设备": "cyclical_manufacturing",
    "汽车": "cyclical_manufacturing",
}
```

---

## 5. V1 三视角估值逻辑

### 5.1 盈利视角

Objective: 用当前盈利能力给出估值区间。

所需字段：
- `current_price`
- `dynamic_pe`
- `eps`
- 可选：近 3 年净利润 / 扣非净利润 / ROE

V1 推荐实现：
- `eps = current_price / dynamic_pe`（如果 dynamic_pe 有效）
- 给模板一个 `target_pe_base`
- 再结合质量修正因子修正目标 PE

公式：
- `mid = eps * target_pe_base`
- `low = mid * 0.85`
- `high = mid * 1.15`

视角合法条件：
- `eps > 0`
- `dynamic_pe` 为正且有限

### 5.2 资产视角

Objective: 用净资产锚给出估值区间。

所需字段：
- `net_assets`
- `total_shares` 或 `a_share_market_cap + current_price`
- 行业模板

V1 推荐实现：
- `bvps = net_assets / total_shares`
- `mid = bvps * target_pb_base`
- `low/high` 同理

视角合法条件：
- `net_assets > 0`
- `total_shares > 0`

### 5.3 收入视角

Objective: 给成长股一个不依赖当前利润的估值锚。

所需字段：
- `revenue`
- `total_shares`
- 行业模板

V1 推荐实现：
- `revenue_per_share = revenue / total_shares`
- `mid = revenue_per_share * target_ps_base`
- `low/high` 同理

视角合法条件：
- `revenue > 0`
- 金融股直接无效

---

## 6. 数据装载层设计

### 6.1 复用现有数据来源

`app/valuation/data_loader.py` 里优先复用：
- `app.search.index.build_stock_profile(...)` 或对应 profile 逻辑
- `app.search.index.compute_stock_score(...)`
- `scripts/serve_stock_dashboard.py` 当前已有基础行情逻辑的字段口径

V1 必须拿到这些字段：
- `stock_name`
- `industry_level_1_name`
- `industry_level_2_name`
- `valuation_template_id`（若有）
- `current_price`
- `dynamic_pe`
- `a_share_market_cap`
- `total_shares`
- `float_shares`
- `eps`
- 最新财报关键字段：
  - revenue
  - net_profit
  - ex_net_profit
  - ocf
  - equity / net_assets

### 6.2 缺失字段兜底策略

- `valuation_template_id` 缺失 -> fallback map
- `eps` 缺失 -> 尝试 `current_price / dynamic_pe`
- `total_shares` 缺失 -> `a_share_market_cap / current_price`
- `net_assets` 缺失 -> 资产视角失效
- `revenue` 缺失 -> 收入视角失效

禁止：
- 为了让视角“看起来合法”而用明显错误的默认值补 0

---

## 7. 权重修正与输出等级（V1）

### 7.1 初始权重

若合法视角数：
- 0 -> `not_estimable`
- 1 -> 单视角参考
- >=2 -> 合法视角等权起步

### 7.2 质量修正（复用现有评分因子）

从 `compute_stock_score(...)` 结果里提取：
- `roe_ex`
- `revenue_growth`
- `profit_growth`
- `ocf_to_profit`
- `free_cf`
- `debt_ratio`

修正规则示例：
- `ocf_to_profit` 高且稳定 -> earnings +0.10
- `debt_ratio` 高 -> asset -0.10
- 高成长但利润不稳 -> revenue +0.10, earnings -0.10
- 金融股 -> asset 主导

注意：
- 单因子上限 ±0.20
- 单视角累计上限 ±0.30

### 7.3 output_level

规则：
- `standard`
- `cautious_reference`
- `highly_cautious`
- `not_estimable`

推荐逻辑：
- 合法视角 0 -> `not_estimable`
- 合法视角 1 -> `cautious_reference`
- 合法视角 >=2 且 reliability 中高 -> `standard`
- 结构性断裂 / 数据缺失明显 -> `highly_cautious`

---

## 8. 风险标签与失效条件

### 8.1 风险标签（V1）

建议在 `app/valuation/risk_engine.py` 中输出：
- `short_history`
- `structural_break`
- `cashflow_quality_warning`
- `high_leverage`
- `financial_stock_special_case`
- `peer_support_weak`

### 8.2 失效条件（V1）

建议在 `app/valuation/failure_conditions.py` 中返回 3 条以内：
- 若未来两个季度利润增速明显失速，则盈利视角失效
- 若资产负债率显著恶化，则资产视角折价加深
- 若行业监管或商业模式出现重大变化，则模板映射失效

---

## 9. API 接入计划

### Task 1: 建 valuation API 页面测试骨架

Objective: 先锁定新页面与新接口的存在。

Files:
- Create: `tests/test_valuation_page.py`
- Modify: `web/stock-score.html`（后续导航链接）
- Modify: `scripts/serve_stock_dashboard.py`

Step 1: Write failing tests

```python
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"

class ValuationPageTests(unittest.TestCase):
    def test_valuation_page_exists_with_terminal_shell(self):
        html = (WEB_ROOT / "valuation.html").read_text(encoding="utf-8")
        self.assertIn('class="app-shell', html)
        self.assertIn('id="valuation-input"', html)
        self.assertIn('id="valuation-status"', html)
        self.assertIn('id="valuation-view-earnings"', html)
        self.assertIn('id="valuation-view-asset"', html)
        self.assertIn('id="valuation-view-revenue"', html)
```

Step 2: Run test to verify failure

Run:
`python3 -m unittest tests.test_valuation_page.ValuationPageTests.test_valuation_page_exists_with_terminal_shell -v`

Expected:
FAIL — `valuation.html` not found

Step 3: Add minimal page shell
- Create `web/valuation.html`
- 只放最小 terminal shell 与占位 DOM id

Step 4: Re-run
Expected: PASS

Step 5: Commit

---

### Task 2: 新增 valuation 数据结构测试

Objective: 锁定 `ViewResult / ValuationContext / ValuationResult`。

Files:
- Create: `tests/test_valuation_service.py`
- Create: `app/valuation/models.py`
- Create: `app/valuation/context.py`
- Create: `app/valuation/__init__.py`

Step 1: Write failing tests

```python
import unittest
from app.valuation.models import ViewResult, ValuationResult
from app.valuation.context import ValuationContext

class ValuationModelTests(unittest.TestCase):
    def test_view_result_fields_exist(self):
        row = ViewResult(view_name="earnings", low=1.0, mid=2.0, high=3.0, is_valid=True)
        self.assertEqual("earnings", row.view_name)
        self.assertEqual(2.0, row.mid)
```

Step 2: Run failure
`python3 -m unittest tests.test_valuation_service.ValuationModelTests.test_view_result_fields_exist -v`

Step 3: Implement dataclasses

Step 4: Re-run
Expected: PASS

Step 5: Commit

---

### Task 3: 建立模板路由层

Objective: 先实现 `valuation_template_id` 选择逻辑。

Files:
- Modify: `app/valuation/config.py`
- Modify: `tests/test_valuation_service.py`

Step 1: Write failing test

```python
def test_resolve_template_prefers_explicit_template_then_fallback():
    from app.valuation.config import resolve_valuation_template_id
    self.assertEqual(
        "consumer_quality",
        resolve_valuation_template_id("consumer_quality", "家电", "白色家电")
    )
    self.assertEqual(
        "bank",
        resolve_valuation_template_id(None, "银行", "全国性银行")
    )
```

Step 2: Run failure

Step 3: Implement minimal resolver

Step 4: Re-run
Expected: PASS

Step 5: Commit

---

### Task 4: 数据装载层最小实现

Objective: 能为单只股票组装 valuation 所需字段。

Files:
- Create: `app/valuation/data_loader.py`
- Modify: `tests/test_valuation_service.py`

Implementation note:
- 先复用现有 profile/basic/score 逻辑
- 不额外造第二套行情/财报读取

Test should lock:
- 返回 `stock_name`
- 返回行业层级
- 返回 `current_price`
- 返回 `dynamic_pe`
- 返回 `total_shares`
- 返回至少一个财报关键字段

---

### Task 5: 三视角函数最小实现

Objective: 能返回 earnings / asset / revenue 三个 `ViewResult`。

Files:
- Create: `app/valuation/views.py`
- Modify: `tests/test_valuation_service.py`

Functions:
- `compute_earnings_view(data, ctx, config)`
- `compute_asset_view(data, ctx, config)`
- `compute_revenue_view(data, ctx, config)`

V1 requirements:
- 合法字段存在时输出 low/mid/high
- 缺字段时 `is_valid=False`
- 金融股收入视角无效

---

### Task 6: 权重修正引擎

Objective: 对合法视角做最小权重修正。

Files:
- Create: `app/valuation/weight_engine.py`
- Modify: `tests/test_valuation_service.py`

Functions:
- `compute_view_weights(view_results, score_context)`
- `pick_dominant_view(weights)`

V1 rules:
- 合法视角数 0 -> 无结果
- 合法视角数 1 -> 单视角参考
- 多视角 -> 等权起步 + 小幅修正 + 归一化

---

### Task 7: 风险标签与失效条件

Objective: 给估值结果补齐使用边界。

Files:
- Create: `app/valuation/risk_engine.py`
- Create: `app/valuation/failure_conditions.py`
- Modify: `tests/test_valuation_service.py`

Lock in:
- `risk_tags` 为 list
- `failure_conditions` 为 list
- 高负债 / 短历史 / 结构变化能触发标签

---

### Task 8: Valuation service 聚合

Objective: 把所有子模块串起来，返回标准 `ValuationResult`。

Files:
- Create: `app/valuation/service.py`
- Modify: `tests/test_valuation_service.py`

Function:
- `build_valuation_result(market, symbol)`

Required behavior:
- 构建 context
- 计算三视角
- 计算权重与主导视角
- 合成 final low/mid/high
- 输出 level / risk_tags / failure_conditions
- 转成 API dict

---

### Task 9: HTTP handler 接入

Objective: 新增 `/api/valuation`。

Files:
- Modify: `scripts/serve_stock_dashboard.py`
- Modify: `tests/test_valuation_page.py`

Step 1: Add failing test at template/string level
- require `/api/valuation`
- require `handle_valuation`

Step 2: Implement handler

Pseudo:

```python
def handle_valuation(self, query: str) -> None:
    params = parse_qs(query)
    market = params.get("market", [""])[0].strip().lower()
    symbol = params.get("symbol", [""])[0].strip()
    try:
        from app.valuation.service import build_valuation_result
        self.respond_json(HTTPStatus.OK, build_valuation_result(market, symbol))
    except ValueError as exc:
        ...
```

Step 3: Re-run tests

Step 4: Commit

---

### Task 10: 构建 valuation.html 正式页面结构

Objective: 建出单页骨架并保持风格一致。

Files:
- Create: `web/valuation.html`
- Modify: `tests/test_valuation_page.py`

页面必须包含：
- topbar
- 搜索输入 `#valuation-input`
- 搜索按钮 `#valuation-search-btn`
- 状态条 `#valuation-status`
- 总览卡：
  - `#valuation-current-price`
  - `#valuation-final-low`
  - `#valuation-final-mid`
  - `#valuation-final-high`
  - `#valuation-output-level`
  - `#valuation-confidence`
- 三视角区：
  - `#valuation-view-earnings`
  - `#valuation-view-asset`
  - `#valuation-view-revenue`
- 风险/失效条件：
  - `#valuation-risk-tags`
  - `#valuation-failure-conditions`

---

### Task 11: 构建 valuation.js

Objective: 前端可调用 `/api/valuation` 并渲染结果。

Files:
- Create: `web/valuation.js`
- Modify: `tests/test_valuation_page.py`

Required behavior:
- 输入 + button 查询
- 渲染总览卡
- 渲染三视角卡
- 渲染风险标签与失效条件
- 保持最近查询（可二期）

---

### Task 12: 顶部导航接入

Objective: 让页面能从现有模块访问。

Files:
- Modify: `web/index.html`
- Modify: `web/stock-score.html`
- Modify: `web/rps-pool.html`
- Modify: `tests/test_valuation_page.py`

Add link:
- `/valuation.html`
- 文案：`估值`

---

### Task 13: 全量回归与 live 验证

Objective: 保证单页真正可用。

Commands:
- `python3 -m unittest tests.test_valuation_page -v`
- `python3 -m unittest tests.test_valuation_service -v`
- `node --check web/valuation.js`
- `python3 -m unittest tests.test_rps_page tests.test_stock_score_page -v`

Live:
- 用专用 venv 重启：
  `/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python scripts/serve_stock_dashboard.py`
- 打开：
  `http://127.0.0.1:8765/valuation.html`
- 查询：
  - `000333`
  - `600519`
  - `600000`
- 重点验证：
  - 消费股 `consumer_quality`
  - 白酒/家电的 earnings 主导
  - 银行股收入视角失效
  - 风险标签与失效条件能显示

---

## 10. V1 配置建议

可先内嵌在 `app/valuation/config.py`，后面再抽 YAML。

最小模板示例：

```python
TEMPLATE_DEFAULTS = {
    "consumer_quality": {"pe": 22.0, "pb": 4.0, "ps": 3.0},
    "cyclical_manufacturing": {"pe": 15.0, "pb": 2.0, "ps": 1.2},
    "industrial_metal": {"pe": 12.0, "pb": 1.6, "ps": 0.9},
    "utilities_infra": {"pe": 16.0, "pb": 1.8, "ps": 2.2},
    "bank": {"pe": 6.0, "pb": 0.8, "ps": None},
    "nonbank_finance": {"pe": 14.0, "pb": 1.4, "ps": None},
    "healthcare_growth": {"pe": 30.0, "pb": 4.5, "ps": 5.0},
    "tech_growth": {"pe": 35.0, "pb": 5.0, "ps": 6.0},
    "generic_equity": {"pe": 18.0, "pb": 2.0, "ps": 2.0},
}
```

---

## 11. 命名与展示约束

- 页面标题：`Valuation Terminal`
- 中文副标题：`个股估值`
- 输出等级文案建议：
  - `标准`
  - `谨慎参考`
  - `高度谨慎`
  - `不宜估值`

- 方法说明文案应写进：
  - `#valuation-methodology-note`

禁止：
- 在前端自己重新计算估值
- 在页面中混入 AI 解读作为 V1 必要依赖
- 输出“精确目标价”而不带区间与风险提示

---

## 12. 验收标准

必须全部满足：
- [ ] 有独立页面 `valuation.html`
- [ ] 有独立接口 `/api/valuation`
- [ ] 三视角结构完整
- [ ] 至少能查询消费股、制造股、银行股
- [ ] 银行股收入视角自动失效
- [ ] 输出有 low/mid/high，不是单点价
- [ ] 输出有 `output_level`
- [ ] 输出有 `risk_tags`
- [ ] 输出有 `failure_conditions`
- [ ] 页面风格与现有 dark terminal 一致
- [ ] 测试通过
- [ ] live 页面可打开并完成 3 个样本查询

---

## 13. 推荐实施顺序（务实版）

固定顺序：
1. 页面壳与测试
2. dataclass 模型
3. 模板路由
4. 数据装载层
5. 三视角函数
6. 权重修正
7. 风险标签/失效条件
8. service 聚合
9. API 接入
10. 前端渲染
11. 导航接入
12. live 验证

---

## 14. 本计划之后的下一步建议

执行完 V1 后，再做：
- V1.5：估值历史分位与行业对照
- V2：10Y 国债、股息历史、增强 PB/PS/EV 数据
- V3：银行/非银/资源股专属模板

---

## 15. 执行提示

优先用 Codex 执行实现。

建议实现时每个任务都遵守：
- 先补测试
- 看测试失败
- 最小实现
- 回归
- live 验证

如果要开始执行，建议从：
- Task 1 + Task 2 + Task 3
起步。