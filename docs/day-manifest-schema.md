# day_manifest.json 字段草案

## 目标
定义每日归档完成后生成的 `day_manifest.json` 结构，作为：
- 当日归档总索引
- 数据集清单
- 版本与口径说明
- 校验结果摘要
- 审计与重跑入口

## 文件位置
推荐位置：
```text
data/archive/trading_day=YYYY-MM-DD/manifests/day_manifest.json
```

## 设计原则
1. day_manifest 是“当日归档总目录”，不是明细数据本体。
2. 它必须能回答：
   - 这一天归档是否完成
   - 用了什么版本
   - 包含了哪些数据集
   - 数据截止到什么时候
   - 有没有异常
3. 必须支持重跑和版本追踪。
4. 应兼顾机器读取与人工排查。

## 顶层建议结构
```json
{
  "trading_day": "2026-04-24",
  "run_id": "archive_20260424_01",
  "archive_revision": 1,
  "archive_status": "success",
  "started_at": "2026-04-24T15:10:00+08:00",
  "completed_at": "2026-04-24T18:42:31+08:00",
  "generated_at": "2026-04-24T18:42:31+08:00",
  "data_cutoff_time": "2026-04-24T15:00:00+08:00",
  "source_summary": {},
  "versions": {},
  "datasets_included": [],
  "snapshot_summary": {},
  "validation_summary": {},
  "exception_summary": {},
  "rerun_info": {},
  "artifacts": {},
  "notes": []
}
```

## 顶层字段说明
### 1. trading_day
类型：string

说明：
- 当前归档对应的交易日
- 格式建议：`YYYY-MM-DD`

示例：
```json
"trading_day": "2026-04-24"
```

### 2. run_id
类型：string

说明：
- 本次归档任务唯一标识
- 每次重跑都必须变化

示例：
```json
"run_id": "archive_20260424_01"
```

### 3. archive_revision
类型：integer

说明：
- 当日归档修订版本
- 首次归档为 1
- 重跑后递增

### 4. archive_status
类型：string

推荐枚举：
- success
- partial_success
- failed
- superseded

说明：
- success：完整通过
- partial_success：有部分数据可用，但不是完整成功
- failed：归档失败
- superseded：已被更新 revision 替代

### 5. started_at / completed_at / generated_at
类型：string (ISO 8601)

说明：
- started_at：本次归档开始时间
- completed_at：归档完成时间
- generated_at：manifest 文件生成时间

### 6. data_cutoff_time
类型：string (ISO 8601)

说明：
- 归档所依据的数据截至时间
- 应与 final 数据口径一致

## source_summary 字段草案
类型：object

建议结构：
```json
"source_summary": {
  "primary_source": "local_tdx",
  "secondary_sources": ["tdx_api"],
  "data_status": "final",
  "price_mode_default": "qfq",
  "intraday_base_interval": "1m",
  "derived_base_interval": "5m",
  "fallback_enabled": true
}
```

字段说明：
- primary_source：主源
- secondary_sources：辅助源列表
- data_status：final / provisional
- price_mode_default：默认价格口径
- intraday_base_interval：最底层分钟源
- derived_base_interval：本次主派生基底
- fallback_enabled：是否允许回退链路

## versions 字段草案
类型：object

建议结构：
```json
"versions": {
  "api_version": "v1",
  "schema_version": "1.0.0",
  "rule_version": "1.0.0",
  "derivation_version": "1.0.0",
  "data_pipeline_version": "1.0.0",
  "model_version": "gpt-5.4"
}
```

说明：
- API、schema、规则、派生逻辑、数据管道、AI 模型版本统一放这里

## datasets_included 字段草案
类型：array

用途：
- 列出本次归档包含的所有核心数据集
- 这是 manifest 最重要的主体之一

建议每项结构：
```json
{
  "dataset_name": "bars_15m",
  "storage_layer": "derived_store",
  "data_status": "final",
  "base_interval": "5m",
  "target_interval": "15m",
  "scope": "stock",
  "partition": "trading_day=2026-04-24",
  "path": "data/archive/trading_day=2026-04-24/bars/bars_15m.parquet",
  "row_count": 125600,
  "symbol_count": 4521,
  "generated_at": "2026-04-24T18:10:22+08:00",
  "data_cutoff_time": "2026-04-24T15:00:00+08:00",
  "validation_status": "passed"
}
```

建议字段：
- dataset_name
- storage_layer
- data_status
- base_interval
- target_interval
- scope
- partition
- path
- row_count
- symbol_count / sector_count
- generated_at
- data_cutoff_time
- validation_status

## snapshot_summary 字段草案
类型：object

建议结构：
```json
"snapshot_summary": {
  "market_snapshot": "available",
  "sector_snapshot": "available",
  "stock_snapshot": "available",
  "portfolio_snapshot": "not_enabled"
}
```

说明：
- 用于快速判断各业务快照是否已产出

## validation_summary 字段草案
类型：object

建议结构：
```json
"validation_summary": {
  "overall_status": "passed",
  "checks_total": 12,
  "checks_passed": 12,
  "checks_failed": 0,
  "warnings": 1,
  "validation_items": [
    {
      "name": "final_data_status_check",
      "status": "passed"
    },
    {
      "name": "dataset_presence_check",
      "status": "passed"
    }
  ]
}
```

建议验证项：
- final_data_status_check
- dataset_presence_check
- version_presence_check
- archive_partition_check
- row_count_sanity_check
- timestamp_consistency_check
- snapshot_presence_check
- audit_log_presence_check

## exception_summary 字段草案
类型：object

建议结构：
```json
"exception_summary": {
  "has_exceptions": true,
  "exception_count": 2,
  "retryable_count": 1,
  "non_retryable_count": 1,
  "top_errors": [
    {
      "error_code": "DATASET_PARTIAL_MISSING",
      "count": 1
    }
  ]
}
```

说明：
- 即使归档 success，也可能有 warning/partial exception

## rerun_info 字段草案
类型：object

建议结构：
```json
"rerun_info": {
  "is_rerun": false,
  "rerun_of": null,
  "rerun_reason": null,
  "supersedes_revision": null
}
```

重跑时可变成：
```json
"rerun_info": {
  "is_rerun": true,
  "rerun_of": "archive_20260424_01",
  "rerun_reason": "late_final_data_arrival",
  "supersedes_revision": 1
}
```

## artifacts 字段草案
类型：object

建议结构：
```json
"artifacts": {
  "success_marker": "data/archive/trading_day=2026-04-24/_SUCCESS.json",
  "failure_marker": null,
  "manifest_path": "data/archive/trading_day=2026-04-24/manifests/day_manifest.json",
  "audit_root": "data/archive/trading_day=2026-04-24/audit/",
  "bars_root": "data/archive/trading_day=2026-04-24/bars/",
  "features_root": "data/archive/trading_day=2026-04-24/features/",
  "datasets_root": "data/archive/trading_day=2026-04-24/datasets/",
  "snapshots_root": "data/archive/trading_day=2026-04-24/snapshots/"
}
```

## notes 字段草案
类型：array[string]

用途：
- 记录人工备注、特殊情况说明、当天口径说明

示例：
```json
"notes": [
  "北交所 5m 派生未纳入本次正式主基底",
  "部分专题数据集因上游延迟未纳入 final 归档"
]
```

## 最小可落地字段集合
如果先做 MVP，建议最少先保留：
- trading_day
- run_id
- archive_revision
- archive_status
- started_at
- completed_at
- data_cutoff_time
- versions
- source_summary
- datasets_included
- validation_summary
- exception_summary
- rerun_info
- artifacts

## 命名与格式建议
1. 所有字段用 snake_case
2. 时间统一 ISO 8601
3. 枚举状态统一小写字符串
4. path 使用相对项目根目录路径
5. 数量字段统一 integer

## 结论
`day_manifest.json` 应该被视为“每日归档总索引文件”。

它的职责不是存明细，而是回答这几个问题：
- 今天归档完成了吗？
- 用了什么版本？
- 包含了哪些数据集？
- 数据截止到什么时候？
- 有没有异常？
- 如果重跑过，替代了谁？
