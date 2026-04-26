# _SUCCESS / _FAILED 标记文件字段草案

## 目标
定义每日归档完成后使用的状态标记文件结构，用于：
- 快速判断某个 trading_day 是否归档成功
- 不读取完整 day_manifest 也能快速获知状态
- 为调度器、监控器、后续任务提供轻量状态入口
- 记录失败阶段与重跑关联信息

## 适用文件
推荐使用两个标记文件：

1. 成功标记
```text
data/archive/trading_day=YYYY-MM-DD/_SUCCESS.json
```

2. 失败标记
```text
data/archive/trading_day=YYYY-MM-DD/_FAILED.json
```

规则：
- `_SUCCESS.json` 与 `_FAILED.json` 不应同时作为当前有效状态共存
- 若发生重跑，旧状态文件应被替代或显式标记 superseded

## 设计原则
1. 标记文件是轻量状态入口，不替代 `day_manifest.json`
2. 标记文件必须能关联到 `run_id` 和 `day_manifest.json`
3. 成功与失败文件字段应尽可能对齐，便于机器读取
4. 标记文件必须足够短小，但要包含最关键的状态信息

## 成功标记文件字段草案

### 推荐结构
```json
{
  "trading_day": "2026-04-24",
  "archive_status": "success",
  "run_id": "archive_20260424_01",
  "archive_revision": 1,
  "started_at": "2026-04-24T15:10:00+08:00",
  "completed_at": "2026-04-24T18:42:31+08:00",
  "data_cutoff_time": "2026-04-24T15:00:00+08:00",
  "dataset_count": 27,
  "validation_passed": true,
  "manifest_path": "data/archive/trading_day=2026-04-24/manifests/day_manifest.json",
  "generated_at": "2026-04-24T18:42:31+08:00"
}
```

### 字段说明
- trading_day
  - 当前归档对应交易日
- archive_status
  - 固定为 `success`
- run_id
  - 本次归档运行 ID
- archive_revision
  - 当前归档修订号
- started_at
  - 本轮归档开始时间
- completed_at
  - 本轮归档完成时间
- data_cutoff_time
  - 本次归档数据截至时间
- dataset_count
  - 成功归档的数据集数量
- validation_passed
  - 是否通过最终校验
- manifest_path
  - 对应 day_manifest 路径
- generated_at
  - 成功标记文件写入时间

## 失败标记文件字段草案

### 推荐结构
```json
{
  "trading_day": "2026-04-24",
  "archive_status": "failed",
  "run_id": "archive_20260424_02",
  "archive_revision": 2,
  "started_at": "2026-04-24T19:05:00+08:00",
  "failed_at": "2026-04-24T19:07:12+08:00",
  "failed_stage": "phase_4_archive_finalize",
  "error_code": "DATASET_WRITE_FAILED",
  "error_summary": "final features parquet write failed",
  "retryable": true,
  "manifest_path": "data/archive/trading_day=2026-04-24/manifests/day_manifest.json",
  "generated_at": "2026-04-24T19:07:12+08:00"
}
```

### 字段说明
- trading_day
  - 当前归档对应交易日
- archive_status
  - 固定为 `failed`
- run_id
  - 本次失败归档运行 ID
- archive_revision
  - 本次失败对应修订号
- started_at
  - 本轮归档开始时间
- failed_at
  - 失败发生时间
- failed_stage
  - 失败所在阶段
- error_code
  - 结构化错误码
- error_summary
  - 人类可读错误摘要
- retryable
  - 是否允许重试
- manifest_path
  - 若 manifest 已生成，则指向对应路径
- generated_at
  - 失败标记文件写入时间

## 推荐失败阶段枚举
建议统一 `failed_stage`：
- phase_0_prepare
- phase_1_intraday_generation
- phase_2_market_close_freeze
- phase_3_final_recompute
- phase_4_archive_finalize
- phase_5_validation_publish
- manifest_write
- success_marker_write

## 最小必备字段集合

### _SUCCESS.json 最小集合
- trading_day
- archive_status
- run_id
- archive_revision
- completed_at
- dataset_count
- validation_passed
- manifest_path

### _FAILED.json 最小集合
- trading_day
- archive_status
- run_id
- archive_revision
- failed_at
- failed_stage
- error_code
- error_summary
- retryable

## 与 day_manifest 的关系
标记文件和 `day_manifest.json` 的关系应为：

- 标记文件：轻量状态入口
- day_manifest：完整当日归档总索引

默认规则：
1. 监控器/调度器可先读 `_SUCCESS.json` / `_FAILED.json`
2. 若需要更多信息，再读 `day_manifest.json`
3. 不应用标记文件替代完整 manifest

## 重跑规则
当某个 trading_day 重跑时：

1. 新 run_id 必须生成
2. archive_revision 必须递增
3. 旧成功/失败标记若失效，应：
   - 删除旧标记，或
   - 把旧状态写入 manifest 的 rerun_info 中
4. 最终只保留当前有效状态标记

## 命名与格式要求
1. 文件名固定：
- `_SUCCESS.json`
- `_FAILED.json`

2. 字段命名：
- 统一 snake_case

3. 时间字段：
- 统一 ISO 8601

4. 状态字段：
- success / failed 小写字符串

## 禁止事项
以下做法默认禁止：
- 用空文件 `_SUCCESS` 但不写结构化 JSON
- 失败时只打日志不写 `_FAILED.json`
- 成功和失败标记同时作为当前有效状态存在
- 标记文件里没有 run_id 与 trading_day
- 标记文件无法关联到 `day_manifest.json`

## 结论
`_SUCCESS.json` 和 `_FAILED.json` 应被视为“每日归档的轻量状态门牌”。

它们的职责是：
- 快速告诉系统和人：今天归档成功了还是失败了
- 指向完整 `day_manifest.json`
- 提供最关键的状态、时间、版本和错误信息

而完整的归档细节仍应由 `day_manifest.json` 承担。