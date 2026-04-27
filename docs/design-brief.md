# 新方案设计简表

## 1. 产品目标
- 待补充

## 2. 目标用户
- 待补充

## 3. 页面/模块范围
- 不预设固定四页面结构
- 由用户按功能重新定义模块与页面
- 当前仅保留“页面/模块范围待补充”
- 后续先定义功能模块，再决定是否映射为页面、标签页、工作台分区或独立流程

## 4. 数据源优先级
- 本地通达信数据
- 通达信接口数据
- 其他公开数据源
- 正式规则见：`docs/system-rules.md`

## 5. 规则输出
- 条件：待补充
- 风险：待补充
- 失效：待补充
- 周期规则：周线定方向、日线定结构、分钟线定触发
- 数据质量规则：统一复权口径，停牌与缺失数据必须降级处理
- 分层约束规则：指数定环境、板块定方向、个股定执行
- 执行规则：信号分级、动作分级、仓位上限、加减仓与退出必须成套输出
- 时间窗成交量指标草案见：`docs/intraday-volume-indicators.md`

## 6. AI 输出
- 摘要解释：待补充
- 边界规则：规则引擎先产出正式结论，AI 只负责解释、总结、提示风险
- 冲突处理：AI 与规则字段冲突时，以规则字段为准

## 7. 技术方案
- 前端：待补充
- 后端：待补充
- 缓存/数据库：待补充
- 刷新与缓存规则：实时层短缓存、短周期层滚动刷新、日级层正式固化、周级层参数校准
- API 规则：统一 snake_case、统一状态枚举、统一时间字段、统一错误结构
- 审计与回测规则：正式结果必须结构化留痕，回测/复盘只认 final 数据与规则字段
- 本地通达信接入规则：原始数据只读直连，系统只存标准化缓存、派生数据、正式快照与审计结果
- 分钟周期派生规则：沪深主市场可优先用已验证的 5 分钟线派生 15/30/60 分钟，1 分钟线保留为回退源
- 派生数据管理规则：支持多个派生数据集，按日计算、按日归档，供后续分析、复盘与回测使用

## 8. MVP 范围
- 先定义核心功能模块
- 再确定最小可行页面组织方式
- 不默认采用固定四页面方案
- 派生数据层目录结构草案见：`docs/derived-data-layout.md`
- 每日归档流程方案见：`docs/daily-archive-workflow.md`
- day_manifest 字段草案见：`docs/day-manifest-schema.md`
- day_manifest 示例文件见：`docs/day_manifest.example.json`
- success/failed 标记文件草案见：`docs/archive-marker-schema.md`
- success 标记示例见：`docs/_SUCCESS.example.json`
- failed 标记示例见：`docs/_FAILED.example.json`
- datasets_included 命名规范见：`docs/dataset-catalog-schema.md`
- 行业与概念标准化 schema 见：`docs/industry-concept-schema.md`
- 概念过滤规则 v1 见：`docs/concept-filter-rules.md`
- 过滤规则示例配置见：`config/concept_filter_rules.v1.json`
- 归档脚本执行顺序与伪代码见：`docs/archive-script-plan.md`
- 代码目录与运行数据目录边界见：`docs/code-data-boundary.md`
