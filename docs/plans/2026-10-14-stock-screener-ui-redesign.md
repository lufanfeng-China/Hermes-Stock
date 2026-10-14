# 股票筛选工作台 UI 重设计实施方案

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 把当前“策略按钮 + 超长高级筛选表单 + 宽结果表”的页面，重构为先选策略、再做少量关键收窄、最后审阅可行动结果的高密度研究工作台。

**Architecture:** 保持 `GET /api/stock-screener`、现有参数名、日期选择、保存方案、本地 JSON 方案、加入自选股、K 线和 PE 弹窗不变。只重构 `stock-screener-v2.html` 的语义布局和 `stock-screener-v2.css`，在 `stock-screener.js` 增加筛选摘要、分组折叠、结果列视图和移动端抽屉状态；不改后端筛选语义。

**Tech Stack:** Vanilla HTML/CSS/ES module JavaScript, existing local HTTP API, existing tests via Python unittest and Node syntax check.

---

## 设计结论

**设计定位：** A 股策略研究工作台，服务于需要快速从策略信号进入候选池、再用少量过滤器进行二次收窄的投资者。

- 设计方差：3。结构稳定、没有装饰性不对称布局。
- 动效强度：1。仅保留按钮、展开和抽屉的短状态反馈，支持 `prefers-reduced-motion`。
- 信息密度：8。数据和控制高度紧凑，但按决策顺序而不是按后端字段堆叠。
- 视觉语言：保留当前黑白基底、细边框、圆角、单一强调色。移除七种大面积粉彩筛选卡，颜色只表达筛选状态、风险或方向，不承担分组职责。

## 现状审计

1. 桌面端 `1280px` 下，标题与 10 项全局导航同时出现，导航已经折为两行，顶栏高度为 `109px`。
2. 筛选表单完全展开后高度为 `1414px`，执行筛选按钮位于页面约 `1808px`，用户需要穿过整张表单才能提交。
3. 七组条件平铺为四列不等高马赛克。技术面 `508px`、评分排名 `477px`、RPS `464px`，阅读路径不连续，用户难以分辨“核心条件”和“少用条件”。
4. 多选控件在有限高度内直接展示所有选项，行业、估值、技术信号区域都有滚动和换行竞争。
5. 策略、同步 AI 股池、保存方案和已存方案共处一行，但它们分别属于“开始筛选”“结果后操作”“方案管理”三种不同层级。
6. 结果表视觉上有 16 个可见列，实际 CSS 最小宽度 `1260px`，在 `1180px` 内容宽度下已发生横向滚动。行内没有按“决策优先级”分层。
7. HTML 使用 17 个表头（含选择框），但空状态和 JS 中 `colspan` 仍为 16，应在重构中统一清点，防止空状态错位。
8. `tests/test_stock_screener_page.py` 当前仍主要断言旧版 `stock-screener.html`，而线上入口是 `stock-screener-v2.html`，需要把 UI 契约测试迁到实际入口。

## 新信息架构

页面顺序固定为：

1. 紧凑顶栏
   - 左侧：`股票筛选` 和一句功能描述“从策略信号到候选池”。
   - 右侧：全局导航为单行横向滚动或“更多”菜单。不得换成第二行。

2. 固定研究上下文栏
   - `数据截至` 日期选择器和 5/10/20/60 天快捷日期。
   - 一行显示当前状态：最新数据或具体回测日期。
   - 日期改变后显示“已切换为 YYYY-MM-DD，点击运行更新结果”，不自动发起筛选。

3. 策略起点区
   - 标题：`1. 选择策略`。
   - 每个策略为可选择的紧凑卡或单选标签，显示策略名、1 行触发逻辑、候选数加载态。
   - 策略说明只展示当前选中策略，不在所有策略旁重复展示。
   - “已存方案”移动到此区的方案下拉；“保存方案”只有已有条件或策略时显示。

4. 条件摘要与核心收窄区
   - 策略选中后显示 `当前条件` 摘要条，使用可删除的文本 token，例如 `RPS首次`、`回测日 2026-09-24`、`PE分位 <= 30%`。
   - 紧接着展示 `2. 收窄候选池`，默认只显示四组高频条件：关键词/行业、排名与评分、RPS、估值位置。
   - 每组只保留常用字段，控制在 3-5 项；字段为空不占摘要。
   - 主按钮 `运行筛选` 始终位于条件摘要栏右侧或桌面端底部粘性操作条，不能落在 1400px 表单之后。
   - `重置` 是次级按钮，重置前保留回测日期，清空策略和人工条件。

5. 高级条件抽屉
   - 标题：`高级条件`，展示已启用数量。
   - 采用可折叠的分类面板，不再使用所有分类同时平铺。
   - 分类：技术面、财务质量、价格与新高、行业概念、其他评分维度。
   - 多选控件改为可搜索的选项弹层或折叠清单，必须能看到已选数量和清除入口。
   - 高级条件变动立刻更新摘要与“已启用 N 项”，但不自动查询。

6. 结果工作区
   - 标题：`3. 审阅候选池`，左侧为命中数和数据日期，右侧为当前排序、列视图和方案操作。
   - 无策略、加载、无结果、错误四种状态放在表格区域中央，分别给出下一步操作。
   - 默认“决策视图”保留 9 列：股票、现价、趋势、短趋势、RPS、PE 分位、排名（全/二级）、行业、动作。
   - “分析视图”显示完整指标表，并允许横向滚动。不得让默认视图承受 16+ 列。
   - `同步到AI股池` 和 `加入自选` 只在结果大于 0 且选择了行时出现，放在结果工具栏，不和策略选择器混排。
   - 点击股票后展开已有 K 线区域，K 线标题应带股票名和数据日期。

## 实施任务

### Task 1: 建立真实入口的 UI 契约测试

**Objective:** 把筛选页回归测试从旧入口转到实际使用的 V2 页面，并为新布局建立不可回退的语义锚点。

**Files:**
- Modify: `tests/test_stock_screener_page.py`
- Test: `tests/test_stock_screener_page.py`

**Step 1: 写失败测试**

断言 V2 HTML 包含以下稳定锚点：
- `stock-screener-strategy-stage`
- `stock-screener-active-filters`
- `stock-screener-core-filters`
- `stock-screener-advanced-filters`
- `stock-screener-run-bar`
- `stock-screener-column-view`
- `stock-screener-results-toolbar`

断言默认视图表头只有决策视图所需列，完整视图由 JS 显式切换。

**Step 2: 运行失败测试**

Run:
```bash
~/.venvs/moontdx-china-stock-data/bin/python -m unittest tests.test_stock_screener_page -v
```

Expected: FAIL，因为新语义锚点尚未创建。

**Step 3: 不修改旧筛选 API 的前提下补齐 HTML/JS/CSS 结构。**

**Step 4: 再运行测试，期望通过。**

**Step 5: Commit**
```bash
git add tests/test_stock_screener_page.py web/stock-screener-v2.html web/stock-screener-v2.css web/stock-screener.js
git commit -m "test: cover screener workbench layout contract"
```

### Task 2: 重组 HTML 为三步工作流

**Objective:** 在不改变任何 input `name` 或 API 参数的情况下，建立“策略、收窄、结果”三段结构。

**Files:**
- Modify: `web/stock-screener-v2.html`

**Step 1:** 保留现有所有字段 `name`、所有现有 ID、日期选择器、结果表和弹窗节点。

**Step 2:** 将策略按钮和已存方案组织到 `#stock-screener-strategy-stage`。

**Step 3:** 增加条件摘要容器：
```html
<div id="stock-screener-active-filters" aria-live="polite"></div>
```

**Step 4:** 将高频字段置于 `#stock-screener-core-filters`，将低频字段置于 `#stock-screener-advanced-filters` 的分类折叠区。字段仅移动，不改 `name`、option value 和多选属性。

**Step 5:** 增加结果列视图切换：
```html
<select id="stock-screener-column-view" aria-label="结果列视图">
  <option value="decision">决策视图</option>
  <option value="analysis">完整分析</option>
</select>
```

**Step 6:** 将同步到 AI 股池从策略行移至结果工具栏，初始隐藏。

### Task 3: 实现筛选摘要、高级条件和安全的状态管理

**Objective:** 让用户始终知道当前会怎样筛选，且每次控制操作有即时反馈。

**Files:**
- Modify: `web/stock-screener.js`
- Test: `tests/test_stock_screener_page.py`

**Step 1: 写失败测试**

断言 JS 包含：
- `renderActiveFilterSummary`
- `getActiveFilterEntries`
- `toggleAdvancedFilterGroup`
- `setResultsColumnView`

**Step 2:** 从 `FormData(form)` 构建可见摘要。策略、回测日期和非空条件都需要人类可读标签。多选值用单个摘要项表达，避免逐个 option 堆满。

**Step 3:** 每个摘要项带可访问的删除按钮。删除后同步表单值、摘要、启用数量，不自动发请求。

**Step 4:** 高级面板的折叠状态保存到 `localStorage`。仅保存 UI 展开状态和列视图，不保存筛选结果，避免数据口径误导。

**Step 5:** 修改 `runScreener()` 状态文案：加载时展示策略或条件摘要，成功时展示命中数和数据日期，失败时保留原条件以便重试。

**Step 6:** 只在结果存在时显示 AI 股池同步和批量自选操作；没有勾选时按钮禁用并显示说明。

### Task 4: 重做高密度 CSS 布局

**Objective:** 用稳定栅格和少量语义色，替代当前七张不等高彩色筛选卡。

**Files:**
- Modify: `web/stock-screener-v2.css`

**Step 1:** 保留已有字体和中性色，收敛色彩为画布、表面、分隔线、强调、成功/警示/风险状态五类 token。

**Step 2:** 桌面 `>= 1180px`：
- 研究上下文、策略区和摘要栏为全宽行。
- 核心筛选是 4 个等宽区块，不使用颜色区分类型。
- 高级筛选为单列 accordion，展开后内部使用 2-3 列字段栅格。
- `运行筛选` 所在操作栏 `position: sticky; bottom: 12px`，有实色背景和边框。

**Step 3:** 平板 `768-1179px`：核心筛选两列，高级内部两列，顶部导航横向滚动但不换行。

**Step 4:** 移动端 `<768px`：单列，日期快捷项横向滚动，结果默认仅显示股票、现价、趋势、RPS、动作五列，完整分析在单独列视图中横向滚动。

**Step 5:** 表格在决策视图不设置超过容器的固定最小宽度。完整分析视图允许横向滚动并显示“左右滑动查看完整指标”提示。

**Step 6:** 添加 `prefers-reduced-motion: reduce`，关闭展开过渡。

### Task 5: 重构结果列视图并修复表格列数契约

**Objective:** 默认视图优先支持选股决策，完整数据仍保留且不丢失。

**Files:**
- Modify: `web/stock-screener-v2.html`
- Modify: `web/stock-screener.js`
- Modify: `web/stock-screener-v2.css`
- Test: `tests/test_stock_screener_page.py`

**Step 1: 写失败测试**

对空状态、加载、错误和无结果四种 `tbody` 输出，断言 `colspan` 基于实际当前可见列数，而不是硬编码 `16`。

**Step 2:** 抽取 `RESULT_COLUMN_VIEWS` 元数据，每列定义：key、label、默认视图可见性、完整视图可见性、renderer。

**Step 3:** `renderScreenerRows()` 和 HTML header 都由相同列元数据生成。禁止只改一端。

**Step 4:** 决策视图按行显示：股票、现价、趋势、短期趋势、RPS、PE 分位、排名、行业、动作。动作包含单行勾选和查看 K 线。

**Step 5:** 完整分析视图保留现有全部数据字段，包含 GAP、均线距离、上次新高、估值位置、多头期数、行业维度和行业分数。

### Task 6: 浏览器验收和回归验证

**Objective:** 确认改版没有更改后端语义，且在三种宽度、四种状态下都能完成筛选工作。

**Files:**
- Test: `tests/test_stock_screener_page.py`
- Verify: `web/stock-screener-v2.html`, `web/stock-screener-v2.css`, `web/stock-screener.js`

**Step 1: 静态检查**
```bash
node --check web/stock-screener.js
~/.venvs/moontdx-china-stock-data/bin/python -m unittest tests.test_stock_screener_page -v
```

**Step 2: API 对照**

用同一个策略、同一个 `as_of_date` 分别在改版前后调用：
```bash
curl -s 'http://127.0.0.1:8765/api/stock-screener?strategy=rps_first&as_of_date=YYYY-MM-DD&page=1&page_size=50'
```

验证 `total`、`rows[].symbol` 和后端字段未因 UI 改版改变。

**Step 3: 浏览器交互验收**

- 初始：无 API 筛选请求，提示选择策略或条件。
- 选择策略：策略高亮、摘要出现、加载态出现、结果区更新。
- 添加核心条件：摘要即时更新，但只在点击运行后查询。
- 打开高级条件并选择多选值：启用数量与摘要正确，删除摘要项后控件同步恢复。
- 保存/加载方案：策略、日期、字段和摘要均恢复。
- 无结果/接口失败：保留用户条件并给出可操作提示。
- 选择结果：批量自选和 AI 股池操作仅在合法条件下可用。

**Step 4: 尺寸验收**

- 1440px：顶栏一行；默认结果表无横向滚动；运行按钮始终可见。
- 1024px：导航不换行，核心筛选两列；无重叠或字段裁切。
- 390px：单列条件，默认结果信息可读；完整视图横向滚动有提示。

**Step 5: Commit**
```bash
git add web/stock-screener-v2.html web/stock-screener-v2.css web/stock-screener.js tests/test_stock_screener_page.py
git commit -m "feat: redesign stock screener workbench"
```

## 不做的内容

- 不修改选股策略、过滤公式、回测算法或 API 参数语义。
- 不增加新的外部 UI 框架或构建工具。
- 不在无用户动作时加载全量筛选结果。
- 不把后端字段静默删除。完整分析视图保留当前字段。

## 验收标准

1. 用户可在首屏完成日期选择、策略选择和启动筛选。
2. 常用收窄条件不超过一个视觉区块，低频条件不会迫使用户浏览 1400px 表单。
3. 执行筛选操作在任何展开状态都可见。
4. 默认结果视图以股票判断为中心，没有不必要的横向滚动。
5. 当前 API、策略、日期回测、保存方案、K 线、PE 弹窗、自选和 AI 股池能力均可用。
6. 只有实际异常状态使用颜色，颜色之外同时有文字说明。
7. 测试针对真正的 V2 入口，表头、行渲染与空状态列数由同一契约控制。
