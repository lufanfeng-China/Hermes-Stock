# 行业与概念标准化 Schema 草案

## 目标
为系统中的“股票行业三级信息”和“股票概念标签”定义统一、可归档、可回测、可审计的标准 schema，满足：
- 原始通达信数据只读直连，不复制整库
- 系统内部保存标准化结果与每日快照
- 当前查询与历史回测使用同一套字段体系
- 后续财报分析模板、估值模板、行业排名、概念联动分析可直接复用

## 总体原则
1. 不复制通达信原始目录。
2. 运行时从通达信本地路径只读解析原始文件。
3. 系统只保存标准化结果，不保存原始整库副本。
4. 行业信息必须同时支持 `current` 与 `snapshot`。
5. 概念信息必须同时支持 `dictionary`、`current` 与 `snapshot`。
6. 所有结果必须保留 `source`、`source_file`、`parser_version`、`generated_at`、`data_cutoff_time`。
7. 进入规则引擎、归档、回测的结果必须使用系统标准化后的数据集，不直接读取通达信原始文本文件。

## 原始来源
### 行业
- 股票 -> 行业代码映射：`/mnt/c/new_tdx64/T0002/hq_cache/tdxhy.cfg`
- 行业代码 -> 行业名称映射：
  - `/mnt/c/new_tdx64/T0002/hq_cache/tdxzs3.cfg`
  - `/mnt/c/new_tdx64/T0002/hq_cache/tdxzs.cfg`

### 概念
- 股票 -> 概念标签映射：`/mnt/c/new_tdx64/T0002/signals/extern_sys.txt`
- 扩展概念资源（后续可选增强）：
  - `/mnt/c/new_tdx64/T0002/signals/gpextern.txt`
  - `/mnt/c/new_tdx64/T0002/signals/gpextern1.zip`
  - `/mnt/c/new_tdx64/T0002/signals/gpextern2.zip`

## 行业层级标准
### 推荐主口径
行业层级解析优先使用 `X...` 代码树：
- 一级：如 `X24 -> 家电`
- 二级：如 `X2401 -> 白色家电`
- 三级：如 `X240101 -> 空调`

### 原始字段保留
同时保留通达信原始 `T...` 行业代码，作为兼容与审计字段：
- 例如 `T0401 -> 家用电器`

## 数据集 1：dataset_stock_industry_current
### 用途
保存“当前最新可用”的股票行业三级映射，供页面/API/规则引擎快速读取。

### 推荐路径
```text
data/derived/datasets/final/dataset_stock_industry_current.parquet
```

### 主键语义
```text
market + symbol
```

### 建议字段
- `dataset_name`
- `trading_day`
- `market`
- `symbol`
- `stock_name`
- `source`
- `source_file`
- `industry_source`
- `industry_code_raw_t`
- `industry_code_raw_x`
- `industry_level_1_code`
- `industry_level_1_name`
- `industry_level_2_code`
- `industry_level_2_name`
- `industry_level_3_code`
- `industry_level_3_name`
- `analysis_template_id`
- `valuation_template_id`
- `mapping_confidence`
- `parser_version`
- `generated_at`
- `data_cutoff_time`
- `validation_status`

### 字段说明
- `industry_source`：建议固定为 `tdx_x_tree`
- `analysis_template_id`：财报分析模板映射结果，例如 `consumer_brand`
- `valuation_template_id`：估值模板映射结果，例如 `consumer_quality`
- `mapping_confidence`：行业映射置信度，默认可为 `1.0`

### 示例
```json
{
  "dataset_name": "dataset_stock_industry_current",
  "trading_day": "2026-04-27",
  "market": "sz",
  "symbol": "000333",
  "stock_name": "美的集团",
  "source": "tdx_local",
  "source_file": "T0002/hq_cache/tdxhy.cfg",
  "industry_source": "tdx_x_tree",
  "industry_code_raw_t": "T0401",
  "industry_code_raw_x": "X240101",
  "industry_level_1_code": "X24",
  "industry_level_1_name": "家电",
  "industry_level_2_code": "X2401",
  "industry_level_2_name": "白色家电",
  "industry_level_3_code": "X240101",
  "industry_level_3_name": "空调",
  "analysis_template_id": "consumer_brand",
  "valuation_template_id": "consumer_quality",
  "mapping_confidence": 1.0,
  "parser_version": "industry_parser_v1",
  "generated_at": "2026-04-27T13:10:00+08:00",
  "data_cutoff_time": "2026-04-27T13:10:00+08:00",
  "validation_status": "passed"
}
```

## 数据集 2：snapshot_stock_industry_membership
### 用途
保存按交易日归档的股票行业快照，供历史回测、复盘、审计、分位比较使用。

### 推荐路径
```text
data/archive/trading_day=YYYY-MM-DD/snapshots/snapshot_stock_industry_membership.parquet
```

### 主键语义
```text
trading_day + market + symbol
```

### 建议字段
建议保留 current 表中的全部关键字段，至少包括：
- `dataset_name`
- `trading_day`
- `market`
- `symbol`
- `stock_name`
- `source`
- `source_file`
- `industry_source`
- `industry_code_raw_t`
- `industry_code_raw_x`
- `industry_level_1_code`
- `industry_level_1_name`
- `industry_level_2_code`
- `industry_level_2_name`
- `industry_level_3_code`
- `industry_level_3_name`
- `analysis_template_id`
- `valuation_template_id`
- `parser_version`
- `generated_at`
- `data_cutoff_time`

## 概念主键标准
### 推荐做法
概念不要直接以中文名作为主键，建议生成稳定 `concept_id`：
- 方案 A：`sha1(source + normalized_name)`
- 方案 B：稳定 slug，例如 `tdx_deepseek_concept`

### 标准化字段
- `concept_name`：原始概念名
- `concept_name_normalized`：标准化后的概念名
- `concept_category`：可选，后续做主题聚类时使用

## 数据集 3：dataset_concept_dictionary
### 用途
保存概念主字典，统一概念命名、别名、状态与出现时间范围。

### 推荐路径
```text
data/derived/datasets/final/dataset_concept_dictionary.parquet
```

### 主键语义
```text
concept_id
```

### 建议字段
- `dataset_name`
- `concept_id`
- `concept_name`
- `concept_name_normalized`
- `concept_category`
- `source`
- `source_file`
- `first_seen_date`
- `last_seen_date`
- `is_active`
- `alias_names`
- `parser_version`
- `generated_at`

## 数据集 4：dataset_stock_concept_current
### 用途
保存股票“当前最新可用”的概念归属，供页面、规则引擎、热点分析快速读取。

### 推荐路径
```text
data/derived/datasets/final/dataset_stock_concept_current.parquet
```

### 主键语义
```text
market + symbol + concept_id
```

### 建议字段
- `dataset_name`
- `trading_day`
- `market`
- `symbol`
- `stock_name`
- `concept_id`
- `concept_name`
- `source`
- `source_file`
- `is_active`
- `concept_rank_in_stock`
- `concept_list_raw`
- `parser_version`
- `generated_at`
- `data_cutoff_time`

### 示例
```json
{
  "dataset_name": "dataset_stock_concept_current",
  "trading_day": "2026-04-27",
  "market": "sz",
  "symbol": "000063",
  "stock_name": "中兴通讯",
  "concept_id": "tdx_deepseek_concept",
  "concept_name": "DeepSeek概念",
  "source": "tdx_local",
  "source_file": "T0002/signals/extern_sys.txt",
  "is_active": true,
  "concept_rank_in_stock": 2,
  "concept_list_raw": "AI医疗概念,DeepSeek概念,AI智能体,...",
  "parser_version": "concept_parser_v1",
  "generated_at": "2026-04-27T13:10:00+08:00",
  "data_cutoff_time": "2026-04-27T13:10:00+08:00"
}
```

## 数据集 5：snapshot_stock_concept_membership
### 用途
保存按交易日归档的股票概念快照，供历史热点复盘、概念演变研究、题材回测使用。

### 推荐路径
```text
data/archive/trading_day=YYYY-MM-DD/snapshots/snapshot_stock_concept_membership.parquet
```

### 主键语义
```text
trading_day + market + symbol + concept_id
```

### 建议字段
- `dataset_name`
- `trading_day`
- `market`
- `symbol`
- `stock_name`
- `concept_id`
- `concept_name`
- `source`
- `source_file`
- `parser_version`
- `generated_at`
- `data_cutoff_time`

## 统一治理字段
行业与概念两类数据集都建议统一保留以下字段：
- `dataset_name`
- `trading_day`
- `source`
- `source_file`
- `parser_version`
- `generated_at`
- `data_cutoff_time`
- `validation_status`

股票基础字段统一建议：
- `market`
- `symbol`
- `stock_name`

## 推荐文件命名
### current 层
- `dataset_stock_industry_current.parquet`
- `dataset_concept_dictionary.parquet`
- `dataset_stock_concept_current.parquet`

### archive / snapshot 层
- `snapshot_stock_industry_membership.parquet`
- `snapshot_stock_concept_membership.parquet`

## 与 day_manifest 的推荐映射
### 行业 current
- `dataset_name`: `dataset_stock_industry_current`
- `dataset_category`: `dataset`
- `dataset_scope`: `stock`
- `subject_type`: `tabular_dataset`
- `storage_layer`: `derived_store`

### 行业 snapshot
- `dataset_name`: `snapshot_stock_industry_membership`
- `dataset_category`: `snapshot`
- `dataset_scope`: `stock`
- `subject_type`: `snapshot`
- `storage_layer`: `archive`

### 概念字典
- `dataset_name`: `dataset_concept_dictionary`
- `dataset_category`: `dataset`
- `dataset_scope`: `market`
- `subject_type`: `tabular_dataset`
- `storage_layer`: `derived_store`

### 概念 current
- `dataset_name`: `dataset_stock_concept_current`
- `dataset_category`: `dataset`
- `dataset_scope`: `stock`
- `subject_type`: `tabular_dataset`
- `storage_layer`: `derived_store`

### 概念 snapshot
- `dataset_name`: `snapshot_stock_concept_membership`
- `dataset_category`: `snapshot`
- `dataset_scope`: `stock`
- `subject_type`: `snapshot`
- `storage_layer`: `archive`

## 落地建议
### 第一步
先实现行业解析脚本：
- 读取 `tdxhy.cfg`
- 读取 `tdxzs3.cfg`
- 生成 `dataset_stock_industry_current`

### 第二步
再实现概念解析脚本：
- 读取 `extern_sys.txt`
- 生成 `dataset_concept_dictionary`
- 生成 `dataset_stock_concept_current`

### 第三步
接入每日归档：
- 在 `archive/trading_day=.../snapshots/` 中写入 snapshot
- 在 `day_manifest.json` 中登记这些数据集

## 正式结论
对于行业与概念信息，系统应采用“原始文件只读直连 + 标准化结果 current 化 + 每日 snapshot 化”的混合方案：
- 不复制通达信原始整库
- 当前查询使用 `current` 数据集
- 历史回测与复盘使用 `snapshot` 数据集
- 行业保留三级树结构与模板映射结果
- 概念保留字典、当前归属与历史快照三层结构
