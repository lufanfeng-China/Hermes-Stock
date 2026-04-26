# 每日归档流程方案

## 目标
为派生数据层建立一套可重复、可审计、可回溯的每日归档流程，满足：
- 盘中滚动计算
- 收盘后正式固化
- 多个派生数据集统一归档
- 后续分析、复盘、回测可直接复用

## 总体原则
1. 盘中结果与盘后正式结果必须分离。
2. 每日归档必须以 final 数据为准。
3. 所有归档结果必须带版本、时间、来源、状态元数据。
4. 归档流程必须支持失败重跑，但不允许静默覆盖正式结果。
5. 归档结果必须可按 trading_day 回溯。

## 每日归档的六阶段流程

### Phase 0：准备阶段
时间：收盘前 / 当日初始化

目标：
- 建立当日运行上下文
- 确定 trading_day
- 初始化 provisional 工作区

建议动作：
- 创建运行标识：`run_id`
- 初始化目录：
  - `data/derived/.../provisional/`
  - `data/snapshots/.../`
  - `data/audit/.../`
- 写入当日 manifest 初始文件

最少元数据：
- trading_day
- run_id
- rule_version
- schema_version
- derivation_version
- started_at

### Phase 1：盘中滚动生成阶段
时间：交易时段内

目标：
- 持续生成 provisional 派生数据
- 支撑盘中监控与策略判断

输入：
- 本地通达信原始数据
- 通达信接口实时补齐数据
- 标准化层结果

输出：
- provisional bars
- provisional features
- provisional datasets
- provisional snapshots

写入位置：
- `data/derived/bars/provisional/`
- `data/derived/features/provisional/`
- `data/derived/datasets/provisional/`
- `data/snapshots/`

注意事项：
- 盘中只写 provisional
- 不得把 provisional 直接写入 final 归档区
- 每次更新都要刷新 `generated_at` 和 `data_cutoff_time`

### Phase 2：收盘冻结阶段
时间：收盘后、盘后正式数据更新前

目标：
- 冻结当日盘中 provisional 最终状态
- 保留盘中过程结果供审计与回看

建议动作：
- 停止盘中滚动更新
- 对最后一轮 provisional 结果打冻结标签
- 记录盘中结束时间
- 保存关键盘中快照索引

输出：
- intraday final provisional snapshot
- intraday event summary

写入位置：
- `data/archive/trading_day=YYYY-MM-DD/intraday/`
- `data/audit/signals/`
- `data/audit/executions/`

### Phase 3：盘后正式重算阶段
时间：本地通达信盘后正式数据更新完成后

目标：
- 使用 final 数据重新生成当日正式派生结果
- 替换盘中 provisional 口径

输入：
- 本地通达信 final 数据
- 必要的标准化 daily / intraday final 数据

重算内容：
- final bars
- final features
- final datasets
- final business snapshots
- final rule outputs

核心原则：
- 盘后正式重算必须以 final 数据为准
- 不允许直接把盘中 provisional 文件改名冒充 final
- final 结果必须重新计算或重新确认

写入位置：
- `data/derived/bars/final/`
- `data/derived/features/final/`
- `data/derived/datasets/final/`
- `data/snapshots/`

### Phase 4：正式归档阶段
时间：盘后正式重算完成后

目标：
- 将当日 final 结果按 trading_day 固化归档
- 形成后续分析与回测的正式输入样本

推荐归档目录：
```text
data/archive/
└─ trading_day=YYYY-MM-DD/
   ├─ bars/
   ├─ features/
   ├─ datasets/
   ├─ snapshots/
   ├─ audit/
   └─ manifests/
```

建议归档内容：
- final derived bars
- final derived features
- final datasets
- market/sector/stock snapshots
- rule outputs
- signal logs
- execution logs
- exception logs
- 当日 manifest

### Phase 5：校验与发布阶段
时间：正式归档后

目标：
- 确认归档完整性
- 对外发布“当日归档已完成”状态

建议校验项：
1. 关键数据集是否存在
2. trading_day 是否一致
3. data_status 是否为 final
4. rule_version / schema_version 是否齐全
5. bars / features / datasets 数量是否在合理范围
6. manifest 是否生成成功
7. 异常日志是否为空或已解释

校验通过后可：
- 写入归档完成标记
- 更新 dataset_catalog
- 发布归档完成事件

## 推荐 manifest 结构
建议每个 trading_day 生成：
- `archive/trading_day=YYYY-MM-DD/manifests/day_manifest.json`

至少包含：
- trading_day
- run_id
- archive_status
- generated_at
- completed_at
- data_cutoff_time
- source_summary
- datasets_included
- rule_version
- schema_version
- derivation_versions
- validation_summary
- exception_summary

## 失败重跑规则
每日归档必须允许重跑，但要有边界。

默认规则：
1. provisional 可覆盖重算
2. final 重跑必须保留版本或备份旧结果
3. 已归档 trading_day 若重跑，必须写新的 run_id
4. 必须记录重跑原因
5. 不允许无痕覆盖已发布的正式结果

建议字段：
- rerun_of
- rerun_reason
- archive_revision

## 归档对象分类
建议把每日归档对象固定成四类：

1. bars
- 派生 K 线

2. features
- 派生指标与特征

3. snapshots
- 业务快照

4. audit
- 日志、信号、异常、执行记录

这样后续：
- 复盘直接读 snapshots + audit
- 回测直接读 bars + features + final rule outputs
- 研究直接读 datasets + features

## 每日归档最小落地版
如果先不引入调度系统，建议最小落地流程是：

1. 白天写 provisional
2. 收盘后检测本地 final 数据是否完成更新
3. 触发正式重算
4. 输出 final bars/features/datasets
5. 按 trading_day 复制/固化到 archive/
6. 生成 day_manifest.json
7. 写归档成功标记

## 推荐成功标记文件
例如：
```text
data/archive/trading_day=2026-04-24/_SUCCESS.json
```

建议字段：
- trading_day
- archive_status=success
- run_id
- completed_at
- dataset_count
- validation_passed=true

## 推荐失败标记文件
例如：
```text
data/archive/trading_day=2026-04-24/_FAILED.json
```

建议字段：
- trading_day
- archive_status=failed
- run_id
- failed_at
- failed_stage
- error_summary

## 与你当前系统规则的关系
本流程和当前已定规则一致：
- 规则1：盘中 provisional 与盘后 final 分离
- 规则7：刷新、缓存与重算分层
- 规则9：审计、回测、复盘只认正式结构化结果
- 规则10：原始通达信只读直连，系统只存派生与归档结果

## 结论
对于“多个派生数据 + 每日归档”的场景，推荐采用：
- 盘中 provisional 滚动生成
- 收盘后 final 正式重算
- 按 trading_day 分区归档
- 通过 manifest + success/failure marker 管理每日结果状态

这会让后续分析、复盘、回测和审计都共享同一套正式日终结果。