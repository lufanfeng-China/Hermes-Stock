# 财务评分页进度存档（2026-04-30 10:31:38 CST）

## 1. 存档目的
用于在当前对话暂停前，固化 Project-Hermes-Stock 中与财务评分页、原始财报表、AI 财报解读、细分指标解释能力相关的当前进度、设计决策和后续待办，便于下一次继续开发时快速接续。

## 2. 当前代码仓库状态
- 工作目录：`/home/lufanfeng/Project-Hermes-Stock`
- 当前分支：`main`
- 当前存在未提交改动（含历史未提交项与本轮新增文件）

### 当前 `git status --short`
```text
 M app/archive/jobs.py
 M app/archive/validators.py
 M app/search/index.py
 M scripts/serve_stock_dashboard.py
 M tests/test_archive_pipeline.py
 M tests/test_search_index.py
 M web/app.js
 M web/index.html
 M web/styles.css
 M web/viewport.js
?? _test_builder.py
?? app/industry/
?? scripts/build_financial_snapshot.py
?? scripts/build_financial_snapshot_from_warehouse.py
?? scripts/fetch_latest_financial_online.py
?? scripts/financial_ts_builder.py
?? scripts/update_financial_ts.py
?? tests/industry_heatmap_utils.test.js
?? tests/test_industry_heatmap.py
?? tests/test_rps_page.py
?? tests/test_stock_score_adjustment.py
?? tests/test_stock_score_ai_report.py
?? tests/test_stock_score_page.py
?? web/industry-heatmap-utils.js
?? web/industry-heatmap.html
?? web/industry-heatmap.js
?? web/kline-chart.js
?? web/rps-pool.html
?? web/rps-pool.js
?? web/stock-score.html
?? web/stock-score.js
?? web/viewport.test.js
```

## 3. 已完成的财务评分页核心工作

### 3.1 页面能力与产品语义纠偏
已完成：
- 财务评分页整体 UI 向首页深色终端/仪表盘风格靠拢
- 搜索支持代码/名称/market:symbol，并支持候选下拉与鼠标点击选择
- 候选下拉不再被遮挡
- RPS 与“排名”语义彻底拆分
- 排名已改为“财报评分排名”，不再错误显示为 RPS 20D/50D 排名
- RPS 固定为 4 行：`RPS20 / RPS50 / RPS120 / RPS250`
- 行业区只保留：`申万一级 / 申万二级`
- Quick Picks 已删除，仅保留最近查询
- 最近查询限制为最近 6 条
- 查询按钮旁已加入 `财务明细` checkbox，只有勾选时才预加载最近 3 年原始财报
- AI 财报解读与原始财报时间线已解耦

### 3.2 财务评分与细分指标表
已完成：
- 细分指标表表头从“原始值”改为：`当期 / 上期 / 同比%`
- 细分指标表新增视觉分组：
  - `sub-period-current`
  - `sub-period-previous`
  - `sub-period-yoy`
- `全市场 / 行业内` 已改名为：`全市场分 / 行业内分`
- `自由现金流 (free_cf)` 已按“亿”为单位显示
- 细分指标的语义纠偏已完成：
  - `ROE行业排名` 更正为 `净资产收益率`
  - 内部 key 已从 `roe_rank_pct` 重构为 `roe_pct`

### 3.3 AI 财报解读与原始财报表
已完成：
- AI 财报解读区默认空态，点击按钮后再生成
- 后端通过本地 `hermes` CLI 生成 AI 财报解读
- 结构化 AI 输出字段：
  - `overall`
  - `highlights`
  - `risks`
  - `positive_factors`
  - `negative_factors`
- 原始财报时间线独立接口已完成：
  - `/api/stock-score-report-history`
- 原始财报表已删除：
  - 财报日期
  - 公告日期
  - 资产负债率
- 原始财报表已保留并增强：
  - 报告期
  - 营收(亿)
  - 营收同比
  - 净利润(亿)
  - 净利润同比
  - 扣非净利润(亿)
  - 扣非同比
  - 扣非ROE
  - 流动比率
  - 速动比率

## 4. 本轮新增/最近完成的 UI 细化

### 4.1 报告期 badge 强化
已完成：
- 原始财报表“报告期”由普通文本改为 badge
- 新增 `formatPeriodBadge(...)`
- 新增 badge 层级：
  - `ai-report-period-badge`
  - `ai-report-period-label`
  - `ai-report-period-year`
- 新增季度/年报差异化 class：
  - `ai-report-period-badge-quarter`
  - `ai-report-period-badge-annual`
  - `ai-report-period-badge-q1`
  - `ai-report-period-badge-q2`
  - `ai-report-period-badge-q3`
  - `ai-report-period-badge-q4`

### 4.2 金额 + 同比 的终端化联动增强
已完成：
- 原始财报表金额/同比采用显式结构类：
  - `ai-report-raw-cell`
  - `ai-report-raw-metric`
  - `ai-report-raw-trend`
- 金额与同比的主次关系更清楚，接近“终端指标块”效果

### 4.3 原始财报表 header 终端化增强
刚完成：
- 将原始财报表 `thead` 从单层表头改为“分组头”结构
- 新增表头类：
  - `ai-report-raw-group-head`
  - `ai-report-raw-head-main`
  - `ai-report-raw-head-sub`
- 示例：
  - `营收 / 亿`
  - `营收 / 同比`
  - `净利润 / 亿`
  - `净利润 / 同比`
  - `扣非净利润 / 亿`
  - `扣非 / 同比`
- 风格已向“terminal group header / grouped module bar”靠拢

## 5. 最近通过的验证

### 5.1 测试
最近多轮均通过，最新全量结果：
```text
Ran 47 tests in 0.101s
OK
```

### 5.2 静态检查
通过：
```bash
node --check web/stock-score.js
```

### 5.3 浏览器回归
已对 `http://127.0.0.1:8765/stock-score.html` 做多轮浏览器回归，重点验证：
- 查询 `601318`
- 勾选 `财务明细`
- 原始财报表报告期 badge 正常显示
- 原始财报表 header 分组结构存在
- 原始财报表金额/同比结构类存在
- 细分指标表已显示 `全市场分 / 行业内分`

## 6. 当前后端与数据层能力结论

### 6.1 当前通达信已能稳定支持的层
基于本地 `vipdoc/cw/*.dat` + 在线财务补齐链路，当前适合支撑：
- 财务主表字段
- 财务比率字段
- 同比字段
- 财报公告日期
- 行业/概念/板块标签
- 时间序列快照与衍生指标

### 6.2 当前已经明确的 18 个细分指标
当前核心细分指标包括：
- 盈利：`roe_ex`, `net_margin`, `roe_pct`
- 成长：`revenue_growth`, `profit_growth`, `ex_profit_growth`
- 运营：`ar_days`, `inv_days`, `asset_turn`
- 现金流：`ocf_to_profit`, `ocf_to_rev`, `free_cf`
- 偿债：`debt_ratio`, `current_ratio`, `quick_ratio`
- 资产质量：`ar_to_asset`, `inv_to_asset`, `goodwill_ratio`, `impair_to_rev`

### 6.3 已确认的能力边界
已形成当前产品判断：
- 通达信足够支撑“结构化归因层”
- 但“业务层真实原因”不应只依赖通达信
- 公告正文、MD&A、财报附注、新闻全文，不建议把通达信当唯一主源

## 7. 最新产品设计共识：4 层解释结构
已讨论并形成明确方向：

### 建议采用 4 层结构
1. 指标变化
2. 归因
3. 影响
4. 解释

### 含义
- 指标变化：变了多少
- 归因：从财务结构上为什么变了
- 影响：这种变化会导致哪些问题或正面结果
- 解释：业务层面可能发生了什么

### 为什么要增加“影响层”
这是用户最新明确认可的中间层，用于回答：
- 这个变化严重不严重？
- 会带来什么后果？
- 需要重点关注什么？

### 当前系统中已有可复用雏形
- `app/search/index.py` 中已有 `latest_report_analysis`、`strengths`、`risks`
- AI 财报解读结构中已有：
  - `highlights`
  - `risks`
  - `positive_factors`
  - `negative_factors`

说明下一步完全可以把“影响层”正式结构化，而不是从零开始。

## 8. 建议的下一步优先级

### P1：建立“18 个细分指标的影响层模板”
建议做成一张规则表，逐项定义：
- 指标变好意味着什么
- 指标变差意味着什么
- 哪些是强结论
- 哪些只是弱提示

### P2：建立“18 个细分指标的归因模板”
逐项定义：
- 指标公式
- 依赖底层字段
- 本期/上期的比较逻辑
- 可拆解的分子/分母

### P3：以后再接文本层
如果未来要做“业务层真实原因”，再补：
- 公告正文
- MD&A
- 财报附注
- 新闻/行业事件

## 9. 下一次继续时最推荐的切入点
建议下一次直接从下面这项开始：

### 任务标题
“18 个细分指标的 影响层 模板设计”

### 目标
输出一张结构化规则表，字段可包含：
- `indicator_key`
- `indicator_name`
- `direction`（变好/变差）
- `impact_level`（strong / medium / weak）
- `impact_summary`
- `impact_risks`
- `impact_positive`
- `needs_text_validation`

### 示例
- `free_cf` 下降 -> 分红/回购/扩产/偿债空间受压
- `ocf_to_profit` 下降 -> 利润含金量下降
- `ar_days` 上升 -> 回款变慢、现金流承压
- `goodwill_ratio` 上升 -> 后续减值敏感度增强

## 10. 本次存档文件位置
- `/home/lufanfeng/Project-Hermes-Stock/docs/stock-score-progress-archive-2026-04-30.md`
