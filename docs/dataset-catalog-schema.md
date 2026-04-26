# datasets_included 命名规范与分类字典

## 目标
统一 `day_manifest.json` 中 `datasets_included` 的命名方式、分类方式和最小语义集合，确保：
- 多个派生数据集命名一致
- 后续分析、归档、回测可以稳定索引
- 不同人/不同模块不会给同一类数据起不同名字
- 文件名、manifest、目录层级能够互相映射

## 总体原则
1. dataset_name 必须稳定，不能随意口语化命名。
2. dataset_name 应表达“数据类型 + 周期/主题”，而不是临时用途。
3. 同一概念只能保留一个主名称。
4. dataset_name 与文件路径、catalog、manifest 应一一对应。
5. 不把日期、状态、版本写进 dataset_name 本体；这些放到独立字段里。

## dataset_name 推荐结构
推荐统一采用：
```text
{category}_{subject}_{granularity?}
```

说明：
- category：大类
- subject：具体数据主题
- granularity：可选，表示周期/粒度

示例：
- bars_15m
- bars_30m
- bars_60m
- bars_custom_90m
- features_intraday_momentum
- features_daily_trend
- dataset_sector_strength
- dataset_stock_candidate_pool
- snapshot_market_overview
- audit_signal_events

## 一级分类字典
建议固定为 5 类：

1. bars_*
- 派生 K 线序列

2. features_*
- 派生指标/特征序列

3. dataset_*
- 更高层研究或业务数据集

4. snapshot_*
- 某时点业务快照

5. audit_*
- 审计、事件、执行、异常日志

## 各分类的命名规则

### 1. bars_*
用于派生 K 线。

推荐命名：
- bars_1m
- bars_5m
- bars_15m
- bars_30m
- bars_60m
- bars_custom_10m
- bars_custom_20m
- bars_custom_90m

规则：
- 标准周期直接写周期
- 自定义周期统一加 `custom`
- 不在名字里写市场、股票代码、日期

### 2. features_*
用于派生特征。

推荐命名：
- features_intraday_momentum
- features_intraday_volume
- features_intraday_structure
- features_daily_trend
- features_daily_reversal
- features_daily_volatility
- features_sector_heat
- features_market_breadth

推荐规则：
- 第二维优先写层级：intraday / daily / sector / market
- 第三维写主题：momentum / trend / volatility / breadth / volume / structure

### 3. dataset_*
用于更高层业务数据集。

推荐命名：
- dataset_stock_candidate_pool
- dataset_stock_watchlist
- dataset_stock_avoid_list
- dataset_sector_strength
- dataset_sector_rotation
- dataset_market_environment
- dataset_stock_diagnosis_input
- dataset_backtest_sample

规则：
- `dataset_` 后面优先写对象层级：stock / sector / market / portfolio / backtest
- 最后写用途

### 4. snapshot_*
用于业务快照。

推荐命名：
- snapshot_market_overview
- snapshot_sector_board
- snapshot_stock_diagnosis
- snapshot_portfolio_plan

规则：
- snapshot 表示“截面结果”
- 不表示可连续追加的时间序列

### 5. audit_*
用于审计日志。

推荐命名：
- audit_signal_events
- audit_rule_outputs
- audit_execution_changes
- audit_exceptions
- audit_archive_runs

规则：
- audit 表示追溯用日志
- 不与业务数据集混用

## dataset_name 与其他字段的职责边界
以下信息不要写入 dataset_name，而应放在独立字段：
- trading_day
- data_status
- run_id
- archive_revision
- market
- symbol
- version
- path

也就是说：
- dataset_name = 语义稳定名
- 其他字段 = 当次实例上下文

## datasets_included 单项建议字段
建议每个 dataset item 至少包含：
- dataset_name
- dataset_category
- dataset_scope
- storage_layer
- data_status
- base_interval
- target_interval
- subject_type
- partition
- path
- row_count
- generated_at
- data_cutoff_time
- validation_status

## dataset_category 建议枚举
- bars
- features
- dataset
- snapshot
- audit

## dataset_scope 建议枚举
- market
- sector
- stock
- portfolio
- archive
- backtest
- mixed

## subject_type 建议枚举
- time_series
- feature_series
- snapshot
- event_log
- tabular_dataset

## 示例 1：派生 bars
```json
{
  "dataset_name": "bars_15m",
  "dataset_category": "bars",
  "dataset_scope": "stock",
  "subject_type": "time_series",
  "storage_layer": "derived_store",
  "data_status": "final",
  "base_interval": "5m",
  "target_interval": "15m",
  "partition": "trading_day=2026-04-24",
  "path": "data/archive/trading_day=2026-04-24/bars/bars_15m.parquet",
  "row_count": 125600,
  "generated_at": "2026-04-24T18:10:22+08:00",
  "data_cutoff_time": "2026-04-24T15:00:00+08:00",
  "validation_status": "passed"
}
```

## 示例 2：派生 feature 数据集
```json
{
  "dataset_name": "features_intraday_momentum",
  "dataset_category": "features",
  "dataset_scope": "stock",
  "subject_type": "feature_series",
  "storage_layer": "derived_store",
  "data_status": "final",
  "base_interval": "5m",
  "target_interval": "15m",
  "partition": "trading_day=2026-04-24",
  "path": "data/archive/trading_day=2026-04-24/features/features_intraday_momentum.parquet",
  "row_count": 84500,
  "generated_at": "2026-04-24T18:12:10+08:00",
  "data_cutoff_time": "2026-04-24T15:00:00+08:00",
  "validation_status": "passed"
}
```

## 示例 3：业务数据集
```json
{
  "dataset_name": "dataset_stock_candidate_pool",
  "dataset_category": "dataset",
  "dataset_scope": "stock",
  "subject_type": "tabular_dataset",
  "storage_layer": "final_archive",
  "data_status": "final",
  "base_interval": null,
  "target_interval": "daily",
  "partition": "trading_day=2026-04-24",
  "path": "data/archive/trading_day=2026-04-24/datasets/dataset_stock_candidate_pool.parquet",
  "row_count": 236,
  "generated_at": "2026-04-24T18:20:11+08:00",
  "data_cutoff_time": "2026-04-24T15:00:00+08:00",
  "validation_status": "passed"
}
```

## 示例 4：审计日志
```json
{
  "dataset_name": "audit_signal_events",
  "dataset_category": "audit",
  "dataset_scope": "stock",
  "subject_type": "event_log",
  "storage_layer": "final_archive",
  "data_status": "final",
  "base_interval": null,
  "target_interval": null,
  "partition": "trading_day=2026-04-24",
  "path": "data/archive/trading_day=2026-04-24/audit/audit_signal_events.jsonl",
  "row_count": 1824,
  "generated_at": "2026-04-24T18:25:03+08:00",
  "data_cutoff_time": "2026-04-24T15:00:00+08:00",
  "validation_status": "passed"
}
```

## 文件命名与 dataset_name 的映射规则
推荐：
- parquet/json/jsonl 文件名直接复用 dataset_name

示例：
- `bars_15m.parquet`
- `features_intraday_momentum.parquet`
- `dataset_stock_candidate_pool.parquet`
- `audit_signal_events.jsonl`

优点：
- manifest 和文件系统能直接对照
- catalog 维护简单
- 降低命名漂移风险

## 推荐最小分类字典（V1）
建议第一版先固定以下常用名：

bars：
- bars_15m
- bars_30m
- bars_60m
- bars_custom_10m
- bars_custom_20m
- bars_custom_90m

features：
- features_intraday_momentum
- features_intraday_volume
- features_intraday_structure
- features_daily_trend
- features_daily_volatility
- features_market_breadth
- features_sector_heat

dataset：
- dataset_market_environment
- dataset_sector_strength
- dataset_sector_rotation
- dataset_stock_watchlist
- dataset_stock_candidate_pool
- dataset_stock_avoid_list
- dataset_stock_diagnosis_input
- dataset_backtest_sample

snapshot：
- snapshot_market_overview
- snapshot_sector_board
- snapshot_stock_diagnosis
- snapshot_portfolio_plan

audit：
- audit_signal_events
- audit_rule_outputs
- audit_execution_changes
- audit_exceptions
- audit_archive_runs

## 禁止事项
以下做法默认禁止：
- 同一数据集今天叫 `candidate_pool`，明天叫 `stock_candidates`
- 把日期写进 dataset_name
- 把状态写进 dataset_name
- 把版本写进 dataset_name
- 用临时口语化命名如 `good_stocks_today`
- 同一层既用 `dataset_` 又用 `table_` 表示同类东西

## 结论
`datasets_included` 里的每个数据集，应该有一个长期稳定的语义名。

推荐做法是：
- 先定 5 个一级分类：bars / features / dataset / snapshot / audit
- 再用稳定的 dataset_name 体系命名
- 让 manifest、目录、文件名、catalog 全部使用同一套名字

这样后面无论做归档、回测、复盘还是数据治理，都会清晰很多。