# Relative Valuation Percentile System V1 Implementation Plan

> For Hermes: use Codex or subagent-driven-development to execute this plan task-by-task with strict TDD.

Goal: 为 Project-Hermes-Stock 落地一套“申万二级行业相对估值分位系统 V1”，用行业加权 PE 作为行业锚，用 PE/PS 分位做个股相对位置判断，并输出行业温度、样本质量与风险标签。

Architecture: 采用“日级离线派生 + 轻量查询 API + 终端式单页展示”的结构。先构建每日行业估值快照，再由查询接口按股票代码读取所属申万二级行业、匹配行业快照、组合个股分类结果和展示字段。行业锚采用加权口径，不使用中位数；个股分位采用经验分位，不使用 max-min 极值缩放。

Tech Stack: Python stdlib server, Python dataclasses, local Tongdaxin daily data, local financial_ts parquet warehouse, existing industry current/snapshot datasets, vanilla HTML/CSS/JS, unittest, node --check.

---

## 1. 本轮已确认的产品/规则决策

### 1.1 行业锚
- 申万二级行业主锚 = 行业加权 PE-TTM
- 口径 = `Σ自由流通市值 / Σ正的TTM净利润`
- 不使用中位数作为主锚

### 1.2 个股相对位置
- A 类正常盈利股：在同二级行业 A 类样本中计算 PE 经验分位
- B 类微盈利畸高股：改用 PS 经验分位
- C-I / C-II 类亏损股：改用 PS 经验分位
- C-III / C-IV：不输出估值得分分位，只输出风险/替代指标
- 不使用 `(x-min)/(max-min)` 极值法作为主分位算法

### 1.3 行业温度计
- V1 历史窗口先定为“自 2022 年以来”
- 不在 V1 中宣称“完整近 5 年”，除非后续补齐更早财报仓与历史行业成员快照

### 1.4 有效成分股过滤
行业加权 PE 与行业温度共用有效样本池：
- `ttm_net_profit <= 0` 排除
- `book_value_per_share <= 0` 排除
- 停牌排除（如当前系统能识别）
- 上市 < 60 个交易日排除

### 1.5 样本不足处理
- 有效成分股数 < 10：
  - 不输出行业 PE 分位
  - 不输出行业温度计
  - 个股只展示原始 PE/PS 与“样本不足”说明

### 1.6 动态 PE 失效阈值
- `raw_threshold = industry_weighted_pe_ttm * 5`
- `dynamic_pe_invalid_threshold = clamp(raw_threshold, 50, 200)`

---

## 2. 当前仓库条件与已知约束

### 2.1 当前可直接复用的数据
- `data/derived/financial_ts/by_quarter/*.parquet`
  - 已覆盖 `2022Q1` 到 `2026Q1`
- `data/derived/datasets/final/dataset_stock_industry_current.json`
  - 当前股票 -> 申万一级/二级映射
- 本地 Tongdaxin 日线
  - 样本验证已覆盖 2021-08 至 2026-04
- 现有项目逻辑中已可算出：
  - `dynamic_pe`
  - `a_share_market_cap`
  - `ttm_eps`
  - 财报字段提取

### 2.2 当前已知限制
- 北交所当前本地价格链路缺口明显，`_load_latest_daily_snapshot('bj', ...)` 读不到 `latest_close`
- 历史行业成员快照不是连续 5 年全量归档
- 因此 V1 先优先覆盖沪深主市场，并将行业温度计窗口定义为“自 2022 年以来”

### 2.3 自由流通市值口径待定
V1 必须先统一一个工程口径：
- 方案 A：`自由流通股(股) * close`
- 方案 B：`已上市流通A股 * close`

建议：优先复用当前项目中最稳定可得字段。如果两者都有，优先“自由流通股”，否则回退“已上市流通A股”。

---

## 3. V1 输出对象设计

### 3.1 行业快照输出字段
建议新增日级数据集：`dataset_industry_valuation_current`

每个二级行业一行，至少包含：
- `trading_day`
- `industry_level_1_name`
- `industry_level_2_code`
- `industry_level_2_name`
- `valid_member_count`
- `total_member_count`
- `loss_count`
- `new_listing_filtered_count`
- `invalid_book_value_count`
- `weighted_pe_ttm`
- `weighted_ps_ttm`
- `pe_invalid_threshold`
- `temperature_percentile_since_2022`
- `temperature_label`
- `sample_status` (`ok` / `insufficient` / `invalid_profit_pool`)

### 3.2 个股查询输出字段
建议新增 API：`/api/relative-valuation?market=sz&symbol=000333`

返回结构至少包含：
- `market`
- `symbol`
- `stock_name`
- `industry_level_1_name`
- `industry_level_2_name`
- `classification`
- `sub_classification`
- `current_price`
- `free_float_market_cap`
- `ttm_net_profit`
- `ttm_revenue`
- `revenue_yoy`
- `gross_margin`
- `book_value_per_share`
- `pe_ttm`
- `ps_ttm`
- `industry_weighted_pe_ttm`
- `dynamic_pe_invalid_threshold`
- `industry_temperature_percentile_since_2022`
- `industry_temperature_label`
- `industry_valid_member_count`
- `primary_percentile_metric` (`pe_ttm` / `ps_ttm` / `none`)
- `primary_percentile_value`
- `primary_percentile`
- `valuation_band_label`
- `band_warning`
- `sample_status`
- `risk_flags`
- `notes`

---

## 4. V1 分类规则（落地版）

### 4.1 主分类
输入：`ttm_net_profit`, `pe_ttm`, `dynamic_pe_invalid_threshold`

- 若 `ttm_net_profit > 0` 且 `0 < pe_ttm <= dynamic_pe_invalid_threshold`
  - `classification = A_NORMAL_EARNING`
- 若 `ttm_net_profit > 0` 且 (`pe_ttm <= 0` 或 `pe_ttm > dynamic_pe_invalid_threshold`)
  - `classification = B_THIN_PROFIT_DISTORTED`
- 若 `ttm_net_profit <= 0`
  - `classification = C_LOSS`

### 4.2 亏损子分类
输入：`book_value_per_share`, `ttm_revenue`, `revenue_yoy`, `gross_margin`

- 若 `book_value_per_share <= 0`
  - `sub_classification = C4_LIQUIDATION_RISK`
- 否则若 `ttm_revenue < 1_000_000`
  - `sub_classification = C3_NO_REVENUE_CONCEPT`
- 否则若 `gross_margin >= 0.10` 且 `revenue_yoy >= 0.20`
  - `sub_classification = C2_GROWTH_LOSS`
- 否则
  - `sub_classification = C1_REVENUE_LOSS`

### 4.3 次新股标记
- 上市 < 60 个交易日：
  - 不纳入行业有效样本池
  - 个股结果展示 `is_new_listing = true`
  - 不输出个股 PE/PS 分位

---

## 5. 分位规则（落地版）

### 5.1 经验分位算法
统一采用排序分位，不采用极值缩放。

建议函数：
- 对一组有效样本值按从低到高排序
- 当前值位置记为 `rank`
- 百分位 = `rank / count * 100`
- 同值可用稳定排序兜底

### 5.2 A 类
- 样本池：同二级行业、同日、A 类、有效 PE 样本
- 指标：`pe_ttm`
- 百分位越低 = 估值越低

### 5.3 B / C-I / C-II 类
- 样本池：同二级行业、同日、全部有营收样本
- 指标：`ps_ttm`
- 返回字段里显式标注：`PE invalid, fallback to PS percentile`

### 5.4 C-III 类
- 不输出估值得分分位
- 替代输出：
  - 行业内市值分位
  - 换手率（若当前系统可稳定拿到）
  - 主题博弈提示

### 5.5 C-IV 类
- 不输出任何估值分位
- 直接输出清算/退市风险提示

### 5.6 区间标签
先复用用户方案里的 5 档：
- 0% ~ 20%：低估区间
- 20% ~ 40%：合理偏低
- 40% ~ 60%：合理
- 60% ~ 80%：合理偏高
- 80% ~ 100%：高估区间

附加规则：
- `percentile > 80` 时追加：`80%以上分位风险非线性上升`

---

## 6. 行业温度计规则（V1）

### 6.1 时间窗口
- V1：`2022-01-01` 以来
- 字段命名中避免写死 `5y`
- 推荐命名：`temperature_percentile_since_2022`

### 6.2 历史序列构造
- 每个交易日收盘后，计算每个二级行业的 `weighted_pe_ttm`
- 形成行业日级历史序列
- 当前值在该历史序列中的经验分位 = 行业温度

### 6.3 标签
- 0% ~ 30%：行业偏冷
- 30% ~ 70%：行业温和
- 70% ~ 80%：行业偏热
- 80% ~ 100%：行业过热

附加规则：
- `temperature_percentile_since_2022 > 80` 时追加行业环境风险警告

---

## 7. 仓库落地建议（文件级）

### 7.1 后端新模块
Create:
- `app/relative_valuation/__init__.py`
- `app/relative_valuation/models.py`
- `app/relative_valuation/data_loader.py`
- `app/relative_valuation/classifier.py`
- `app/relative_valuation/percentiles.py`
- `app/relative_valuation/industry_snapshot.py`
- `app/relative_valuation/service.py`
- `app/relative_valuation/labels.py`

### 7.2 服务接线
Modify:
- `scripts/serve_stock_dashboard.py`
  - 新增 `/api/relative-valuation`
  - 后续若做页面，再补 `/relative-valuation.html`

### 7.3 数据集/归档
Create or extend:
- `scripts/build_industry_relative_valuation_snapshot.py`
- `data/derived/datasets/final/dataset_industry_valuation_current.json`
- `data/archive/trading_day=YYYY-MM-DD/snapshots/snapshot_industry_valuation_current.json`

### 7.4 测试文件
Create:
- `tests/test_relative_valuation_classifier.py`
- `tests/test_relative_valuation_percentiles.py`
- `tests/test_relative_valuation_service.py`
- `tests/test_industry_valuation_snapshot.py`

若后续有页面，再加：
- `tests/test_relative_valuation_page.py`

---

## 8. TDD 执行顺序（建议按这个顺序做）

### Task 1: 固化规则常量与分类枚举
Objective: 为 V1 建立稳定的配置和枚举层，避免逻辑散落在 service 中。

Files:
- Create: `app/relative_valuation/models.py`
- Create: `app/relative_valuation/labels.py`
- Test: `tests/test_relative_valuation_classifier.py`

Steps:
1. 写测试，锁定：
   - 分类枚举
   - 温度标签
   - 分位区间标签
2. 跑测试，确认失败
3. 最小实现
4. 重跑测试，确认通过

### Task 2: 实现个股分类器
Objective: 把 A/B/C-I/C-II/C-III/C-IV 规则做成纯函数。

Files:
- Create: `app/relative_valuation/classifier.py`
- Modify: `tests/test_relative_valuation_classifier.py`

Tests should cover:
- 正常盈利 A 类
- 微盈利畸高 B 类
- 亏损四子类
- 次新股标记优先级

### Task 3: 实现经验分位函数
Objective: 用稳定排序分位替代极值缩放。

Files:
- Create: `app/relative_valuation/percentiles.py`
- Test: `tests/test_relative_valuation_percentiles.py`

Tests should cover:
- 单调递增样本
- 重复值
- 空样本
- 单元素样本
- 80% 警告线

### Task 4: 实现行业有效样本过滤
Objective: 固化行业有效成分股筛选逻辑。

Files:
- Create: `app/relative_valuation/industry_snapshot.py`
- Test: `tests/test_industry_valuation_snapshot.py`

Tests should cover:
- 负 TTM 利润排除
- 净资产<=0 排除
- 次新股排除
- 样本不足处理

### Task 5: 实现行业加权 PE / PS 快照计算
Objective: 输出单日行业估值锚结果。

Files:
- Modify: `app/relative_valuation/industry_snapshot.py`
- Modify: `tests/test_industry_valuation_snapshot.py`

Tests should cover:
- `weighted_pe_ttm = sum(market_cap) / sum(profit)`
- `weighted_ps_ttm = sum(market_cap) / sum(revenue)`
- `pe_invalid_threshold = clamp(weighted_pe_ttm * 5, 50, 200)`
- 行业总净利润<=0 时失效

### Task 6: 实现行业温度计（V1: since 2022）
Objective: 基于历史行业加权 PE 序列计算温度分位。

Files:
- Modify: `app/relative_valuation/industry_snapshot.py`
- Modify: `tests/test_industry_valuation_snapshot.py`

Tests should cover:
- 当前值在历史序列中的经验分位
- 历史序列为空
- 历史序列只有 1 个值
- 标签映射

### Task 7: 实现单股 service 组装
Objective: 基于股票、行业和快照结果组装 API 输出。

Files:
- Create: `app/relative_valuation/service.py`
- Create: `app/relative_valuation/data_loader.py`
- Test: `tests/test_relative_valuation_service.py`

Tests should cover:
- A 类输出 PE 分位
- B 类输出 PS 分位
- C-III/C-IV 不输出估值分位
- 样本不足降级
- 行业温度带入

### Task 8: 服务接线
Objective: 暴露 `/api/relative-valuation`。

Files:
- Modify: `scripts/serve_stock_dashboard.py`
- Modify: `tests/test_relative_valuation_service.py`

Tests should cover:
- 缺参数 400
- 正常返回 JSON
- unknown symbol 降级错误结构

### Task 9: 生成行业估值 current/snapshot 数据集
Objective: 形成可查询的行业日级派生数据。

Files:
- Create: `scripts/build_industry_relative_valuation_snapshot.py`
- Possibly modify: `app/archive/jobs.py`
- Possibly modify: `app/archive/validators.py`
- Test: `tests/test_industry_valuation_snapshot.py`

### Task 10: 页面（可选，第二阶段）
Objective: 若用户确认需要独立页面，再补页面壳与前端渲染。

Files:
- Create: `web/relative-valuation.html`
- Create: `web/relative-valuation.js`
- Test: `tests/test_relative_valuation_page.py`

---

## 9. 验证命令（后续执行时使用）

后端单测：
- `python3 -m unittest tests.test_relative_valuation_classifier -v`
- `python3 -m unittest tests.test_relative_valuation_percentiles -v`
- `python3 -m unittest tests.test_industry_valuation_snapshot -v`
- `python3 -m unittest tests.test_relative_valuation_service -v`

综合回归：
- `python3 -m unittest tests.test_search_index tests.test_stock_score_page tests.test_rps_page tests.test_relative_valuation_classifier tests.test_relative_valuation_percentiles tests.test_industry_valuation_snapshot tests.test_relative_valuation_service -v`
- `python3 -m py_compile scripts/serve_stock_dashboard.py app/relative_valuation/*.py`

若有页面：
- `node --check web/relative-valuation.js`
- `python3 -m unittest tests.test_relative_valuation_page -v`

Live 验证：
- `/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python scripts/serve_stock_dashboard.py --host 127.0.0.1 --port 8765`
- `curl 'http://127.0.0.1:8765/api/relative-valuation?market=sz&symbol=000333'`

---

## 10. 风险与待定项

### 10.1 V1 必须明确但还没最终定死的点
- 自由流通市值到底优先取哪个字段
- 停牌识别是否已有稳定字段
- 换手率是否在本地链路中稳定可得
- 北交所在 V1 是否直接不纳入行业锚计算

### 10.2 推荐的 V1 范围控制
- 先只做 API，不做页面
- 先只做沪深主市场
- 先只做 since-2022 温度计
- 先只做 industry current，不急着补完整历史 5 年归档

### 10.3 V2 再做
- 完整 5 年行业温度
- 历史行业成员真实回溯
- 北交所价格链路补齐
- 东方财富行业估值映射并行校验
- 独立前端页面/工作台

---

## 11. 建议的下一步执行顺序

如果立刻进入开发，建议按下面顺序推进：
1. 先做 Task 1~3：规则、分类、经验分位
2. 再做 Task 4~6：行业过滤、行业锚、温度计
3. 再做 Task 7~8：单股 API
4. 最后做 Task 9：日级派生数据集
5. 页面放第二阶段，不和 API 首轮绑定

这样能最快把“规则是否对、数据是否够、口径是否稳”验证出来。
