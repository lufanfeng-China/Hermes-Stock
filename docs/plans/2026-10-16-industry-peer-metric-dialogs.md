# 二级行业同业指标弹框 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 在股票分析页的全部柱状指标卡片上提供一致、可审计、毫秒级打开的二级行业同业对照弹框。

**Architecture:** 不在点击时逐股票计算。每日财务快照构建后，批量生成一份按二级行业分区的指标快照（JSON/Parquet）；页面点击只读取该快照中的一个行业分区，在浏览器排序与跳转。数据按指标性质严格分为年度、当季累计、TTM、期末时点四种口径，绝不把它们混写为同一种“当季”。

**Tech Stack:** Python stdlib/Pandas、现有 TDX 财报仓库、现有 `app/financial/reports.py` / `app/handler.py`、原生 HTML/JS/CSS、unittest。

---

## 1. 指标与口径契约

| 类别 | 指标 | 全年 | 当季 | 当季 TTM | 增长/变化 |
|---|---|---|---|---|---|
| 期间金额 | 营业收入、归母净利润、扣非归母净利润、经营现金流、自由现金流、资本开支 | 最近完整 A | 最新 Q1/Q2/Q3 累计值 | 可用 | 全年/当季/TTM 各自与上年同口径同比 |
| 期间比率 | 毛利率、净利率、扣非 ROE、现金利润比、FCF Margin、CapEx 强度 | 最近完整 A | 最新 Q1/Q2/Q3 累计口径 | 从 TTM 分子/分母重算；扣非 ROE 用 TTM 扣非利润/最新权益 | 同口径变化：百分点（现金利润比除外，显示 %） |
| 期末余额 | 商誉、应收账款、存货 | 最近完整 A 期末 | 最新季末 | 不适用，显示 `—` | 余额同比 |
| 期末比率 | 资产负债率 | 最近完整 A 期末 | 最新季末 | 不适用，显示 `—` | 变化：百分点 |
| 派生变化 | 营收增长率、应收增速差、存货增速差 | 由完整年报同比导出 | 同期累计同比/增速差 | 不适用（增速差） | 本身就是变化指标，不再额外生成增长率 |

统一公式与报告期必须同时作为 API 元数据返回。无有效分母、负/零利润导致比率不具经济可比性时，保留数值（若公式可算）但同比缺失显示 `—`，不可用值绝不变为 0。

## 2. 快照数据层

### Task 1: 定义全量行业指标快照 schema

**Files:**
- Create: `app/financial/industry_metric_snapshot.py`
- Test: `tests/test_industry_metric_snapshot.py`

**RED:** 测试一个行业内两只股票，断言每行含 `market/symbol/stock_name/industry_level_2/is_current_stock` 以及 `annual/quarter/ttm` 三种值、报告期和增长字段；时点指标 TTM 必为 `None`。

**GREEN:** 实现 `build_industry_metric_rows(reports_by_stock, metric_code)`，每个单元统一为：
```python
{"period": "2026Q2", "value": 1.23, "yoy_value": 5.6, "basis": "ttm"}
```

**验证:**
```sh
~/.venvs/moontdx-china-stock-data/bin/python -m unittest tests.test_industry_metric_snapshot -v
```

### Task 2: 单次扫描财报文件并批量生成快照

**Files:**
- Create: `scripts/build_industry_metric_snapshot.py`
- Modify: `app/pipeline/commands.py`
- Test: `tests/test_industry_metric_snapshot.py`

**RED:** 用小型 fixtures 验证财报文件每份只加载一次，而不是每个行业成员重复读取；验证光伏设备等行业可包含所有映射成员，数据不可用成员也保留一行及缺失原因。

**GREEN:**
1. 一次遍历 `_all_financial_files()`；
2. 按 `(market, symbol)` 收集近 6 年报告；
3. 一次生成全部指标、所有二级行业分区；
4. 原子写入 `data/derived/datasets/final/dataset_industry_metric_peers_current.json`，同时写入带日期版本；
5. 元数据含 `built_at`、`annual_anchor`、`quarter_anchor`、来源文件版本和每行业覆盖率。

**验收:** 不允许在浏览器点击时读取全市场原始财报文件。

### Task 3: 让快照成为财务数据更新的独立任务

**Files:**
- Modify: `app/pipeline/commands.py`
- Modify: `app/pipeline/runner.py`
- Modify: `web/data-update.html`
- Test: `tests/test_data_update_plan.py`（若存在；否则新建）

**行为:** `build_industry_metric_snapshot` 是财务快照后的独立任务；失败不阻断 RPS/MACD；任务状态独立；页面披露数据更新时间、覆盖率和错误信息。

## 3. 快速 API

### Task 4: 建立只读快照 API

**Files:**
- Modify: `app/handler.py`
- Create/Modify: `app/financial/industry_metric_snapshot.py`
- Test: `tests/test_industry_metric_peers_api.py`

**Endpoint:**
```text
GET /api/industry-metric-peers?market=sz&symbol=300724&metric=cash_profit_ratio
```

**返回:**
```json
{
  "ok": true,
  "metric": {"code":"cash_profit_ratio","label":"现金利润比","unit":"倍","formula":"经营现金流 ÷ 扣非归母净利润","growth_unit":"%","ttm_supported":true},
  "industry_level_2":"光伏设备",
  "snapshot_as_of":"2026-10-16T...",
  "coverage":{"members":92,"annual":85,"quarter":81,"ttm":79},
  "rows":[...]
}
```

**错误契约:** 无行业映射/无快照/未知指标返回结构化错误；绝不悄悄临时回退成全行业实时计算。

**性能验收:** 热路径只读一个快照分区，局部 HTTP 响应目标 < 200ms；用真实液态行业与小行业各测一次。

## 4. 通用弹框 UI

### Task 5: 以配置驱动全部指标卡片的点击入口

**Files:**
- Modify: `web/stock-analysis.js`
- Modify: `web/stock-analysis.html`
- Modify: `web/styles.css` 或页面内既有样式
- Test: `tests/test_stock_analysis_page.py`

**设计:**
- 将现有 `METRIC_CHARTS` 与 `HEALTH_SERIES_CHARTS` 扩展为共享 `PEER_METRIC_CONFIG`；
- 仅有可比行业快照的卡片使用 `data-industry-metric="metric_code"`；
- 点击卡片/标题都可打开同一个 `industry-metric-peer-dialog`；
- 弹框标题显示“二级行业｜指标｜公式｜单位｜快照时间”；
- 默认按当前口径值降序，当前股票高亮；
- 所有数值列可以升/降序；缺失值排在最后；
- 股票名称+代码是链接/按钮，跳转 `stock-analysis.html?market=...&symbol=...`；
- 余额/时点指标不渲染 TTM 列，而显式显示“TTM 不适用：期末时点值”；
- 列标题根据指标契约自动显示“同比”“变化（百分点）”或“—”。

### Task 6: 逐卡片可用性与无障碍行为

**Files:**
- Modify: `web/stock-analysis.js`
- Test: `tests/test_stock_analysis_page.py`

**RED/验收:**
- 现金利润比、FCF Margin、CapEx 强度、扣非 ROE；
- 营收、利润、现金流和资本开支；
- 商誉、应收、存货、负债率的 TTM 不适用展示；
- Enter/Space 打开弹框；Escape/遮罩/关闭按钮关闭；
- 排序从升到降稳定切换；点击当前行以外的股票跳转正确市场与代码。

## 5. 验收与发布

### Task 7: 数据和浏览器验收

**真实样本:** 至少一个大行业（光伏设备）、一个小行业、一个财报缺失或亏损样本。

**必须核验:**
1. API 的年度/当季/TTM值可由原始报告手算复核；
2. 当季同比只与上一年同季度/同累计期比较；
3. TTM 不对时点值伪造；
4. 全行业成员不因指标不可比而被静默移除；
5. 冷启动只加载快照，不触发逐股财报读取；
6. 浏览器截图确认排序、当前行高亮、缺失 `—`、股票跳转；
7. 前端资源 cache bust；
8. `py_compile`、`node --check`、focused unittest、`git diff --check` 全部通过。

## 实施顺序与现有慢样例的处理

1. 当前 `/api/industry-cash-profit-peers` 仅为样例，不应再作为最终通用数据层；
2. 先完成快照脚本与专用 API；
3. 迁移现金利润比弹框到新 API 并做冷启动性能验收；
4. 再按 `PEER_METRIC_CONFIG` 扩展其他卡片；
5. 最后移除/弃用慢路径，避免任何点击触发全行业逐股财报重算。
