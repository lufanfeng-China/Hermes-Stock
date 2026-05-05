# Project-Hermes-Stock 首页检查报告

检查时间：2026-05-05
URL：http://127.0.0.1:8765/
服务命令：/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python scripts/serve_stock_dashboard.py
测试股票：600519 贵州茅台

## 摘要

本次重点检查财务评分首页（当前 / 路由到 stock-score.html）。正常查询 600519 后，主数据加载成功，控制台没有 JS 错误，API 请求均为 200。但首页仍有几个明确问题：

1. 查询失败/无法识别股票后，多处仍残留上一只股票的数据，属于高优先级功能状态错误。
2. 首屏未查询状态空内容太多，且“待加载 / 暂无 / —”混用，用户容易误解为页面坏了。
3. 行业估值位置弹层与右侧摘要的口径不一致，并出现负 PS-TTM、估值分位缺失但仍排序靠前的问题。
4. AI 财报解读未生成时，结果卡片为空白，缺少明确空态提示。
5. 原始财报表展开后 summary 仍写“展开...”，状态文案与当前展开状态不一致。
6. 细分指标表和雷达图信息密度偏高；不是阻断问题，但有可读性优化空间。

## 问题详情

### 1. 无法识别股票后残留上一只股票数据

严重级别：High
类别：Functional / UX

复现步骤：
1. 打开 http://127.0.0.1:8765/
2. 输入 600519 并点击“查询评分”。
3. 页面加载贵州茅台数据。
4. 将输入框改为“不存在股票”并点击“查询评分”。

实际结果：
页面提示“无法识别股票代码，请输入如 600519 或 sh:600519”，顶部总分和标题被清空，但下面区域仍残留 600519 的数据：
- 核心概念：中华老字号 / 主要高管长期空缺 / 向下突破平台 / 国企改革
- 基础行情：1384.79元、-1.17%、PS-TTM 17.21、PE(动) 20.97倍等
- RPS 动量：RPS20/50/120/250 仍为上一只股票数据
- 相对估值摘要：行业加权 PE/PS、温度、样本、分位、区间标签仍为上一只股票数据
- 维度雷达图仍显示 75.2 / 77.7 及各维度值
- 六维拆分仍显示上一只股票分数
- 细分指标表仍保留完整上一只股票指标

预期结果：
任何无法识别、未找到评分、请求失败状态都应执行统一 reset，清空或隐藏所有股票相关区域，避免旧数据被误认为新输入的结果。

代码定位：
web/stock-score.js 的 invalid branch 约 1924-1932 只调用了 resetScoreHeaderSummary() 和 resetAiFinancialReport()，没有调用 resetProfileSummary()、清空雷达/维度/细分指标/概念摘要等完整 reset。

### 2. 首屏未查询空态过多且状态文案不统一

严重级别：Medium
类别：UX / Visual

现象：
页面初次打开时有大量“暂无 / 待加载 / — / 空白图表”混用：
- Score Snapshot 显示 “— —”
- RPS 动量全部“暂无”
- 相对估值摘要多处为空或待加载
- Score Map 和 Dimensions 大面积空白
- 细分指标只有表头，没有“查询后显示”提示
- AI 财报解读卡片为空

建议：
建立统一状态规则：
- 未查询：查询后显示
- 加载中：加载中...
- 无数据：暂无数据
- 请求失败：加载失败，请重试
并给 Score Map、Dimensions、Sub-Indicators 增加明确空态行/占位卡。

### 3. 行业估值位置弹层口径与摘要不一致，并出现异常估值数据

严重级别：High
类别：Data / Functional

复现步骤：
1. 查询 600519。
2. 点击右侧“行业内估值位置 33.33%”。

观察：
- 右侧摘要显示行业内估值位置 33.33%，relative-valuation API 的 primary_percentile_metric 为 pe_ttm。
- 估值位置弹层标题显示“ps_ttm估值分位对照（当前股票: 66.7%）”，与摘要口径和值不一致。
- /api/industry-valuation-percentile?market=sh&symbol=600519 返回 37 行，其中 valuation_percentile 全部为 null。
- 弹层中出现负 PS-TTM：五粮液 -40.19、洋河股份 -16.25、金种子酒 -324.37、山西汾酒 0.00；这些行显示估值分位为 “—”，但排序后可能排在最前面。

预期结果：
- 弹层标题、排序、主分位指标应与右侧摘要保持一致。
- 负/零 PS-TTM 应作为无效值处理，不应参与低估排序，也不应以正常估值数据显示。
- null 分位行应固定排到最后，或明确标记“估值不可比”。

### 4. AI 财报解读未生成时结果卡片为空白

严重级别：Medium
类别：UX

现象：
勾选“财务明细”并重新查询后，原始财报数据能加载，AI 模块状态提示也正确，但“总体评价 / 财报亮点 / 风险警示 / 加分项 / 减分项”内容框为空白。

建议：
未生成时在每个结果卡片内显示“点击生成AI财报解读后展示”或统一空态，而不是留空白。

### 5. 原始财报表展开后 summary 文案不变

严重级别：Low
类别：UX / Content

现象：
原始财报表已经展开后，summary 仍显示“展开最近3年报告期原始财报数据”。

建议：
展开时显示“收起最近3年报告期原始财报数据”，或使用中性标题“最近3年报告期原始财报数据”。

### 6. 首屏视觉和信息密度优化项

严重级别：Low
类别：Visual / Readability

观察：
- 顶部英文标题较大，右上更新时间区域略紧。
- 查询区输入框、查询按钮、财务明细按钮一行内略拥挤。
- 细分指标表说明列信息量大，formula / meaning 混排偏密。
- 雷达图中心总分和维度数值局部较密。

建议：
这些不是阻断问题，可放在第二优先级处理。

## 控制台和 API

- 浏览器控制台：未发现 JS error。
- 主要 API：/api/data-update-status、/api/search/stocks、/api/stock-score、/api/stock-profile、/api/relative-valuation、/api/stock-score-report-history 均返回 200。
- /api/stock-score?market=sh&symbol=600519 首次约 5.1s，后续缓存后约 77ms。

## 截图证据

截图路径：
- 初始首页：/home/lufanfeng/.hermes/cache/screenshots/browser_screenshot_7e17565dbe5246efa26ec31aa9af019a.png
- 查询 600519 后：首页：/home/lufanfeng/.hermes/cache/screenshots/browser_screenshot_8d14a14da72545ca9eab83000adfcfc4.png
- AI 原始财报表展开：/home/lufanfeng/.hermes/cache/screenshots/browser_screenshot_3049cfe487744a38ad92a4b53941540b.png
- 无法识别股票后的旧数据残留：/home/lufanfeng/.hermes/cache/screenshots/browser_screenshot_2bd6f8bcbcd0474896b74ba2351d22c9.png

## 建议修复优先级

P0 / P1：
1. 增加统一 resetDashboardState()，在无效输入、未找到评分、请求失败、开始新查询时清空所有旧数据。
2. 修复行业估值位置弹层口径和值：与 relative-valuation 的 primary_percentile_metric / primary_percentile 保持一致；负/零估值无效化；null 分位排最后。

P2：
3. 首屏统一空态文案，给图表/维度/细分表添加查询前占位。
4. AI 解读空白卡片增加“点击生成后展示”。
5. 原始财报 details 展开/收起文案同步。

P3：
6. 顶部、查询区、细分表说明列、雷达图做可读性微调。
