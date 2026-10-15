# A股多维股票筛选页 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 新建一个独立、可审计且分页稳定的“股票筛选”页面，支持 RPS、基础行情、财务健康、年度派生财报指标、趋势、MACD/均线金叉、指定日期涨跌幅、N 日换手率八类条件的 AND 筛选，并按每页 50 只展示结果。

**Architecture:** 不恢复已删除的旧 `stock-screener` 代码。新页面使用 `web/stock-filter.html` + `web/stock-filter.js`，后端以一个专属 `/api/stock-filter` API 和独立的筛选服务负责全量过滤、排序和分页。所有改变样本数的筛选都必须在服务端、分页之前执行；浏览器仅提交条件、呈现审计口径和分页结果。

**Tech Stack:** Python 3.12、现有 `ThreadingHTTPServer`/`app/handler.py`、本地通达信前复权日线、现有技术评估数据集 `dataset_technical_eval.json`、RPS 历史/快照、财务健康和财报数据层、原生 HTML/CSS/JavaScript。

---

## 1. 页面方案

### 1.1 页面定位与入口

- 页面路由：`/stock-filter.html`
- 导航名称：`股票筛选`
- 首页仍保持 `/ -> /stock-analysis.html`；筛选页是独立工具页，不取代股票分析。
- `web/nav.js` 中在“股票分析”之后增加筛选入口；所有使用 `global-nav` 的页面自动同步。
- 不复活旧的 RPS、旧筛选、极值金叉页面/路由/策略构建器。

### 1.2 信息布局

```
┌──────────────────────── 股票筛选 ────────────────────────┐
│ 全部重置 | 执行筛选 | 条件摘要 | 数据日期 / 数据完整性      │
├─────────────────────────────────────────────────────────┤
│ ① RPS                     ② 基础行情                     │
│ ③ 财务健康（年度 / 当季）  ④ 年度派生财报指标             │
│ ⑤ 趋势与技术              ⑥ MACD / 均线金叉              │
│ ⑦ 区间涨跌幅              ⑧ N 日换手率                   │
├─────────────────────────────────────────────────────────┤
│ 命中 X / 全市场 Y | 排序 | 50/页 | 已用条件标签            │
├─────────────────────────────────────────────────────────┤
│ 结果表（50行）                                                  │
│ 名称/代码 | 现价 | RPS总分 | 年度/当季财务健康 | 趋势 |       │
│ 金叉 | 区间涨跌 | N日换手 | 行业 | 详情                       │
├─────────────────────────────────────────────────────────┤
│ 上一页  1 … N  下一页                                        │
└─────────────────────────────────────────────────────────┘
```

- 桌面端：条件区使用可折叠 `fieldset` 网格，每组标题显示已启用条件数。
- 小屏：每组纵向展开；结果表横向滚动，分页控件固定在表格上下。
- 只有用户实际填写的条件才会提交；空字段不构成条件。
- 不提供“默认策略”或旧策略按钮，避免再次把策略选择和通用条件筛选混在一起。
- 点击结果行中的名称/代码，跳转 `/stock-analysis.html?market=...&symbol=...&name=...`。

### 1.3 条件组与字段合同

所有数值区间均采用闭区间 `min <= value <= max`；只填一端表示单边约束。无数据默认不命中已启用的该项筛选，且在结果元信息中显示“因字段缺失排除 N 只”。

| 组 | 用户可见条件 | API 参数 / 字段 | 口径 |
|---|---|---|---|
| RPS | RPS20 / 50 / 120 / 250 下限与上限；RPS 总分下限与上限 | `rps_20`, `rps_50`, `rps_120`, `rps_250`, `rps_total` | 使用最新可用交易日的本地截面 RPS；总分 = 四期 RPS 之和，范围 0–400。|
| 基础行情 | 现价、总市值、自由流通市值、PE-TTM、PB、PS-TTM、近 1/5/20 日涨跌幅、所属市场 | `price`, `market_cap`, `free_float_market_cap`, `pe_ttm`, `pb`, `ps_ttm`, `dividend_yield`, `return_1d`, `return_5d`, `return_20d`, `market` | 现价及收益来自本地最新日线；估值、股息率必须返回数据日期及不可比/缺失原因。|
| 财务健康 | 五年年度总分、当季总分；年度六维；当季六维；可选“红旗数不超过” | `annual_total`, `quarterly_total`, `annual_*`, `quarterly_*`, `annual_red_flags`, `quarterly_alerts` | 年度严格采用连续完整年报；当季为独立 TTM/最新披露监测，不能混入年度评分。|
| 年度派生财报指标 | 营收 CAGR、利润 CAGR、扣非 ROE、毛利率、净利率、经营现金流、自由现金流、资产负债率、商誉/资产、应收/营收、库存/营收等 | 明确的 `annual_*` 数值字段 | 仅按最近五个完整年报计算；每个字段在结果列/抽屉显示报告期、公式和数据缺失原因。|
| 趋势 | 长趋势、短趋势、动量、综合结论；可多选 OR | `trend`, `short_trend`, `momentum`, `conclusion` | 直接复用 `dataset_technical_eval.json` 的预计算标签；不同筛选组间为 AND。|
| MACD / 均线金叉 | MACD 零轴上/下金叉；MA 5/10、10/20、5/20、20/60、5/60 金叉，多选 OR | `macd_cross`, `golden_cross` | 复用技术评估数据；单日金叉严格为前一日快线 <= 慢线、当日快线 > 慢线。|
| 区间涨跌幅 | 开始日期、结束日期、最小/最大涨跌幅 | `return_start_date`, `return_end_date`, `return_min`, `return_max` | 收益 = `(结束日收盘 / 开始日收盘 - 1) * 100%`；日期不是交易日时分别回退至该日期或之前最近交易日；界面显示实际使用的两日。|
| N 日换手率 | N（默认 5，可填 1–120）、N 日累计换手率最小/最大，N 日平均换手率最小/最大 | `turnover_days`, `turnover_sum`, `turnover_avg` | 换手率使用成交量 / 当期流通股本；累计 = N 个交易日之和，平均 = 累计 / 有效交易日数。无可用流通股本时标注不可算，不静默填 0。|

**六维字段固定映射**

- 年度：核心增长质量、盈利能力、现金含金量、营运资本、再投资效率、财务风险。
- 当季：增长、盈利、现金、营运资本、再投资效率、风险；在 UI 中按上述六个通用标签映射并明确“当季监测口径”。
- 后端返回维度 `code`、分数、满分、状态、报告期、覆盖度；前端不自行猜测字段或把 `null` 显示为 0。

### 1.4 结果表与审计体验

默认排序：RPS 总分降序；可切换为年度总分、当季总分、近 20 日涨跌幅、市值、N 日累计换手率。每个排序需后端白名单校验。

固定主列：

1. 股票（名称、市场:代码）
2. 行业
3. 现价
4. RPS（总分；悬浮展示 20/50/120/250）
5. 年度健康（总分、样本年数、红旗数）
6. 当季监测（总分、覆盖度、警示数）
7. 趋势（长/短）
8. 金叉（MACD / MA）
9. 指定区间涨跌幅
10. N 日累计/平均换手率
11. 详情

- 点击“详情”展开行内审计抽屉：展示本次命中的所有筛选字段、值、数据日期、完整性和关键财务报告期。
- 后端返回 `applied_filters`、`data_as_of`、`excluded_missing`、`total_universe`、`total_matched`；前端顶部原样展示，避免筛选结果不可解释。
- 严格固定 `page_size=50`，API 拒绝任意大于 50 的值；分页使用 `page`（从 1 开始）、`total`、`total_pages`。筛选条件或排序变化必须重置到第 1 页。

---

## 2. 数据与性能方案

### 2.1 采用“日快照 + 查询过滤”而非每次逐股票计算

约 5,000+ 只 A 股不能在每个 HTTP 请求中逐只读取日线、财报和 CW 文件。新增一个可版本化的筛选快照：

`data/derived/datasets/final/dataset_stock_filter_snapshot_YYYY-MM-DD.json`

并维护 `dataset_stock_filter_snapshot_current.json`。每行按 `market:symbol` 存储：

- 身份、名称、行业；
- 最新 RPS 与数据日期；
- 基础行情 / 估值 / 最新日线收益；
- 年度与当季健康总分、六维、红旗/警示、覆盖度、报告期；
- 年度派生指标与每项报告期；
- 技术评估、MACD、MA 金叉；
- 最新可用于区间与换手的压缩日线派生窗口（至少 252 个交易日：日期、收盘、成交量、流通股本/已算日换手）。

`build_stock_filter_snapshot.py` 只读取一次每种来源，按股票合并，输出 JSON 和 manifest（数据日期、股票数、缺失统计、生成时间、源版本）。数据更新管线增加“构建筛选快照”任务，位置在 RPS、技术评估、财务快照之后。

### 2.2 查询过程

`app/stock_filter.py`：

1. 缓存加载 current 快照；读取及校验请求参数。
2. 先处理所有无需窗口计算的条件（RPS、基础、财务、趋势、金叉）。
3. 仅对候选集合计算指定日期收益和 N 日换手。
4. 收集每条已启用条件的命中/缺失排除统计。
5. 排序，**再分页**，最后序列化 50 条。

性能目标：普通筛选 P95 < 1.5 秒；带日期/N 日窗口 P95 < 3 秒。若快照大到 JSON 加载/响应出现压力，第二阶段改为 Parquet，但第一版不可为此引入前端复杂度。

### 2.3 数据缺口处理

目前已确认存在 `dataset_technical_eval.json`、`dataset_macd_signals_current.json`；历史 RPS 与财务快照文件名/结构需在实现前进一步盘点。若年度/当季健康缺乏全市场预计算快照，先增加批处理，不允许 API 调用 `build_financial_health()` 逐只实时计算。

---

## 3. 实施任务

### Task 1: 定义请求、响应和数据快照 schema

**Files:**
- Create: `app/stock_filter.py`
- Create: `tests/test_stock_filter_contract.py`
- Create: `docs/stock-filter-api.md`

**Step 1:** 写失败测试：空条件返回 schema；每页固定最大 50；非法范围/日期/N 返回 400；排序白名单；`null` 不作为 0。

**Step 2:** 实现 dataclass/纯函数参数解析：`FilterRequest`、`parse_range`、`parse_multi_select`、`validate_sort`。

**Step 3:** 运行：
```bash
~/.venvs/moontdx-china-stock-data/bin/python -m unittest tests.test_stock_filter_contract
```

### Task 2: 建立全市场筛选快照构建器

**Files:**
- Create: `scripts/build_stock_filter_snapshot.py`
- Modify: `app/pipeline/commands.py`
- Test: `tests/test_stock_filter_snapshot.py`

**Step 1:** 用小型 fixture 测试：合并 RPS、技术评估、财务、日线窗口；年度和当季字段独立；缺失流通股本产生不可算状态。

**Step 2:** 盘点并固定读取来源。优先复用：`app/data/rps_history.py`、`app/data/tech_eval.py`、`app/financial/reports.py` 的底层数据和既有财务仓库；不得复制网页渲染逻辑。

**Step 3:** 生成 current + 带日期快照 + manifest；数据更新管线放到依赖源之后。

**Step 4:** 用一只正常工业股、一只金融/不可比行业、一只短历史股票验证字段、报告期与不可用理由。

### Task 3: 实现全量筛选和分页服务

**Files:**
- Modify: `app/stock_filter.py`
- Test: `tests/test_stock_filter_filters.py`

**Step 1:** 分别写失败测试：
- RPS 与基础行情 AND；
- 年度/当季六维不混用；
- 多选趋势与多选金叉组内 OR；
- 指定日期非交易日回退；
- N 日换手率累计和均值；
- 所有筛选先于分页，第二页仍准确；
- `page_size=50`。

**Step 2:** 逐组实现过滤器，返回 `excluded_missing` 审计计数。

**Step 3:** 运行：
```bash
~/.venvs/moontdx-china-stock-data/bin/python -m unittest tests.test_stock_filter_filters
```

### Task 4: 接入 HTTP API

**Files:**
- Modify: `app/handler.py`
- Test: `tests/test_stock_filter_api.py`

**Route:** `GET /api/stock-filter?...`

**Step 1:** 写失败测试：合法请求返回 JSON；固定 50/页；未知参数不改变结果；错误参数返回明确 `invalid_filter`；缓存快照缺失返回 `snapshot_unavailable` 和重建指引。

**Step 2:** 增加 `handle_stock_filter()`，只做参数/HTTP 转换，计算放在 `app/stock_filter.py`。

**Step 3:** 直接 curl 验收：无条件、RPS 条件、年度总分条件、日期涨跌幅、N 日换手率、第二页。

### Task 5: 新建页面和条件区

**Files:**
- Create: `web/stock-filter.html`
- Create: `web/stock-filter.js`
- Modify: `web/styles.css`（仅通用且可复用的筛选页样式）
- Modify: `web/nav.js`
- Test: `tests/test_stock_filter_page.py`

**Step 1:** 写失败静态测试：八个 fieldset、API URL、50 行分页、重置逻辑、无旧页面链接。

**Step 2:** 先实现页面骨架、八个条件组和无结果/加载/错误状态。

**Step 3:** 实现 `FormData -> URLSearchParams`：空值剔除，多选值逗号合并，筛选变化重置 `page=1`。

**Step 4:** 实现结果表、条件摘要、审计抽屉、分页。禁止前端再次筛选已有页数据。

**Step 5:** 添加 `nav.js` 入口；刷新页面确认当前导航 active 状态与缓存版本正确。

### Task 6: 全量构建、运行态与浏览器验收

**Files:** 无新增生产代码；必要时修复 Task 1–5 的缺陷。

**Step 1:** 使用指定解释器重建快照：
```bash
~/.venvs/moontdx-china-stock-data/bin/python scripts/build_stock_filter_snapshot.py
```

**Step 2:** 重启服务（仅后端变更后）：
```bash
fuser -k 8765/tcp 2>/dev/null || true
~/.venvs/moontdx-china-stock-data/bin/python scripts/serve_stock_dashboard.py --host 127.0.0.1 --port 8765
```

**Step 3:** 验收：
- API 每次最多 50 行；
- 组合 AND、组内多选 OR、无数据排除计数正确；
- 年度和当季六维/总分口径明确且独立；
- 区间日期回退可见；
- N 日换手累计/平均正确；
- 翻页总数、页码、结果不重不漏；
- 浏览器无 console error；
- 点击股票进入股票分析页并自动带入代码。

### Task 7: 提交与回滚

**Step 1:** 在任何生产改动前创建 `save-YYYYMMDD-HHMM` annotated tag。

**Step 2:** 通过定向测试、语法检查和浏览器验收后提交；推送 commit 与 annotated tag。

---

## 4. 已确认业务定义

1. **N 日换手率：** 同时支持 N 日累计换手率和 N 日平均换手率的区间过滤；N 取值 1–120，默认 5。
2. **基础行情：** 除现价、总市值、PE-TTM、PS-TTM、短期收益和市场范围外，第一版增加 PB、股息率、自由流通市值。
3. **年度派生财报指标：** 第一版固定使用 11 项：营收 CAGR、利润 CAGR、扣非 ROE、毛利率、净利率、经营现金流、自由现金流、资产负债率、商誉/资产、应收/营收、库存/营收。
4. **默认排序：** RPS 总分降序。
5. **日期区间：** 保持任意开始/结束自然日输入，自动回退到不晚于所选日的最近交易日，并回显实际使用日期。
6. **财务健康：** 严格保持五年完整年报与当季 TTM/最新披露监测隔离；成立期 2–4 年样本默认不混入严格五年样本的筛选结果，后续如需要必须提供明确开关和标识。

## 5. 风险与取舍

1. **数据来源：** PB、股息率、自由流通市值需要在实现前盘点本地快照是否已有稳定字段；缺失时必须在筛选快照 manifest 中记录来源和不可用原因，不能伪造或静默排除。
2. **性能：** 全市场财务健康必须日快照化。首次构建可能较慢，但查询不应实时逐只计算。
3. **样本口径：** 五年完整年报筛选结果不能和 2–4 年成立期样本混排，防止同一“总分”产生错误可比性。

## 6. 设计结论

建议采用“通用条件筛选器 + 预计算统一快照”而非恢复旧策略型筛选器。它严格覆盖八类条件、避免旧策略耦合，且通过先全量过滤再分页确保每页 50 条与总数准确。财务健康年度/当季口径、日期涨跌幅实际交易日、N 日换手率口径都会随每次结果一起可审计地展示。
