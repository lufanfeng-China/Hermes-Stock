# 归档脚本执行顺序与伪代码方案

## 目标
定义“每日归档脚本”在工程上的执行顺序、职责拆分和伪代码骨架，便于后续直接实现为：
- shell 调度入口
- Python 主脚本
- 分阶段任务函数
- 可重跑、可审计的归档任务

## 设计目标
脚本需要满足：
1. 先处理 provisional，再处理 final
2. 收盘后必须等待本地通达信 final 数据就绪
3. 失败必须写 `_FAILED.json`
4. 成功必须写 `day_manifest.json` 和 `_SUCCESS.json`
5. 支持 run_id、archive_revision、rerun_reason
6. 支持多个派生数据集统一归档

## 推荐脚本分层

### 1. 调度入口层
建议文件：
```text
scripts/run_daily_archive.sh
```

职责：
- 由 cron / 手工 / 调度器调用
- 传入 trading_day、rerun_reason 等参数
- 调用 Python 主脚本

### 2. 主控脚本层
建议文件：
```text
scripts/archive_daily.py
```

职责：
- 负责整个归档流程编排
- 生成 run_id
- 维护阶段状态
- 统一异常处理
- 输出 manifest 与 marker 文件

### 3. 任务函数层
建议文件：
```text
app/archive/jobs.py
app/archive/validators.py
app/archive/manifest.py
app/archive/markers.py
```

职责：
- jobs.py：各阶段任务
- validators.py：归档校验
- manifest.py：day_manifest 生成
- markers.py：_SUCCESS / _FAILED 写入

## 推荐执行顺序

### Step 0：解析参数与初始化上下文
输入参数建议：
- trading_day
- force_rerun
- rerun_reason
- dry_run
- target_scopes

初始化上下文应生成：
- run_id
- archive_revision
- work_dir
- archive_dir
- manifest_path
- success_marker_path
- failed_marker_path

### Step 1：锁定归档任务
目的：
- 避免同一 trading_day 并发归档

建议动作：
- 创建 lock file
- 若已存在有效锁，则退出

### Step 2：检查交易日与前置条件
需要检查：
- trading_day 是否合法
- 是否已过收盘时间
- 本地通达信 final 数据是否已更新完成
- 当前是否已有成功归档

若：
- 已有成功归档且非 force_rerun
  -> 直接退出

### Step 3：初始化运行目录与上下文文件
建议动作：
- 创建 `archive/trading_day=.../manifests/`
- 创建临时工作目录
- 写入 `run_context.json`
- 初始化审计日志入口

### Step 4：冻结盘中 provisional 结果
目的：
- 保留盘中最终状态，供复盘和审计

建议动作：
- 保存最后一轮 provisional datasets/snapshots 索引
- 记录收盘冻结时间

### Step 5：加载 final 数据源
核心动作：
- 从本地通达信读取 final 日线/分钟线
- 必要时重建 standardized final 输入层
- 校验关键标的数据完整性

如果失败：
- 进入失败处理流程

### Step 6：生成 final 派生数据
建议顺序：
1. final bars
2. final features
3. final datasets
4. final snapshots
5. final audit summaries

说明：
- bars 是基础
- features 依赖 bars
- datasets 依赖 bars/features/rules
- snapshots 依赖 datasets

### Step 7：执行校验
最少校验项：
- data_status 是否为 final
- datasets 是否齐全
- 关键文件是否存在
- row_count 是否合理
- 时间戳是否一致
- rule_version/schema_version 是否存在
- 归档分区是否正确

校验输出：
- validation_summary
- warnings
- exceptions

### Step 8：写入 archive 分区
将 final 结果正式写入：
```text
data/archive/trading_day=YYYY-MM-DD/
```

建议子目录：
- bars/
- features/
- datasets/
- snapshots/
- audit/
- manifests/

### Step 9：生成 day_manifest.json
由 manifest builder 统一汇总：
- 顶层元数据
- source_summary
- versions
- datasets_included
- validation_summary
- exception_summary
- rerun_info
- artifacts
- notes

### Step 10：写成功标记
写入：
- `_SUCCESS.json`

并确保：
- 如果存在旧 `_FAILED.json`，应移除或失效化处理

### Step 11：清理与释放锁
建议动作：
- 删除临时工作目录
- 释放锁文件
- 输出归档完成日志

## 失败处理顺序
在任意阶段失败时：

1. 捕获异常
2. 记录 failed_stage
3. 生成 error_code / error_summary
4. 写审计异常日志
5. 写 `_FAILED.json`
6. 若部分 manifest 已生成，则补充失败状态
7. 释放锁
8. 返回非 0 退出码

## 推荐主控伪代码
```python
from pathlib import Path
from archive.jobs import (
    freeze_intraday_state,
    load_final_inputs,
    build_final_bars,
    build_final_features,
    build_final_datasets,
    build_final_snapshots,
)
from archive.validators import run_archive_validations
from archive.manifest import build_day_manifest, write_day_manifest
from archive.markers import write_success_marker, write_failed_marker


def main(trading_day, force_rerun=False, rerun_reason=None, dry_run=False):
    ctx = init_context(trading_day, force_rerun, rerun_reason, dry_run)
    acquire_lock(ctx)
    try:
        check_preconditions(ctx)
        init_workdirs(ctx)
        freeze_intraday_state(ctx)

        final_inputs = load_final_inputs(ctx)
        final_bars = build_final_bars(ctx, final_inputs)
        final_features = build_final_features(ctx, final_bars)
        final_datasets = build_final_datasets(ctx, final_bars, final_features)
        final_snapshots = build_final_snapshots(ctx, final_datasets)

        validation_summary = run_archive_validations(
            ctx,
            final_bars=final_bars,
            final_features=final_features,
            final_datasets=final_datasets,
            final_snapshots=final_snapshots,
        )

        write_archive_partition(
            ctx,
            bars=final_bars,
            features=final_features,
            datasets=final_datasets,
            snapshots=final_snapshots,
        )

        manifest = build_day_manifest(
            ctx,
            validation_summary=validation_summary,
            datasets=[final_bars, final_features, final_datasets, final_snapshots],
        )
        write_day_manifest(ctx, manifest)
        write_success_marker(ctx, manifest)

    except Exception as e:
        handle_exception_log(ctx, e)
        write_failed_marker(ctx, e)
        raise
    finally:
        release_lock(ctx)
```

## 推荐任务函数顺序伪代码
```python
def build_final_bars(ctx, final_inputs):
    bars = {}
    bars['bars_15m'] = derive_bars(final_inputs, base='5m', target='15m')
    bars['bars_30m'] = derive_bars(final_inputs, base='5m', target='30m')
    bars['bars_60m'] = derive_bars(final_inputs, base='5m', target='60m')
    return bars


def build_final_features(ctx, final_bars):
    features = {}
    features['features_intraday_momentum'] = calc_intraday_momentum(final_bars)
    features['features_daily_trend'] = calc_daily_trend(ctx)
    return features


def build_final_datasets(ctx, final_bars, final_features):
    datasets = {}
    datasets['dataset_market_environment'] = build_market_environment(ctx)
    datasets['dataset_sector_strength'] = build_sector_strength(ctx, final_features)
    datasets['dataset_stock_candidate_pool'] = build_candidate_pool(ctx, final_features)
    return datasets
```

## 推荐 shell 入口示例
```bash
#!/usr/bin/env bash
set -euo pipefail

TRADING_DAY="${1:-$(date +%F)}"
FORCE_RERUN="${FORCE_RERUN:-false}"
RERUN_REASON="${RERUN_REASON:-}"

python3 scripts/archive_daily.py \
  --trading-day "$TRADING_DAY" \
  --force-rerun "$FORCE_RERUN" \
  --rerun-reason "$RERUN_REASON"
```

## 推荐上下文字段
主脚本运行时，建议统一维护 ctx：
- trading_day
- run_id
- archive_revision
- archive_root
- manifest_path
- success_marker_path
- failed_marker_path
- rule_version
- schema_version
- derivation_version
- started_at
- force_rerun
- rerun_reason

## 最小可落地版实现顺序
如果现在就要开始实现，建议最先做：

1. `scripts/archive_daily.py`
2. `archive.manifest.write_day_manifest()`
3. `archive.markers.write_success_marker()`
4. `archive.markers.write_failed_marker()`
5. `archive.validators.run_archive_validations()`
6. 再逐步接 bars/features/datasets 具体派生任务

## 结论
归档脚本最合理的顺序是：
- 先锁定
- 再检查前置条件
- 冻结盘中状态
- 加载 final 输入
- 生成 final 派生结果
- 校验
- 写 archive
- 写 manifest
- 写 success/failure marker
- 最后释放锁

后续真正编码时，只要照着这个顺序拆函数，整体实现会比较稳。