# 盘中时间窗成交量指标草案

## 目标
先固定两类基础时间窗成交量指标，用于后续：
- 派生数据层
- 每日归档
- 选股/监控规则
- 回测与复盘分析

## 指标 1：开盘 15 分钟成交量
- 中文名：开盘15分钟成交量
- indicator_name：open_15m_volume
- 建议字段名：open_15m_volume
- 指标类型：intraday_volume_window
- 统计对象：成交量
- 时间窗口：开盘后前 15 分钟
- 默认计算口径：1 分钟线求和
- 推荐状态：基础核心指标

### 默认定义
在当前系统中，`open_15m_volume` 表示：
- 交易日开盘后前 15 分钟窗口内的成交量总和

### 默认时间口径
若基于 1 分钟线：
- 默认窗口定义为 `09:31:00 ~ 09:45:00`

若后续切换为已验证稳定的 5 分钟线：
- 可对应聚合 `09:35 / 09:40 / 09:45` 三根 5 分钟 bar 的成交量之和
- 但前提是 5 分钟 bar 时间标签语义已验证一致

## 指标 2：14:30 到 14:45 成交量
- 中文名：14:30到14:45成交量
- indicator_name：window_1430_1445_volume
- 建议字段名：window_1430_1445_volume
- 指标类型：intraday_volume_window
- 统计对象：成交量
- 时间窗口：交易日 14:30 到 14:45
- 默认计算口径：1 分钟线求和
- 推荐状态：基础核心指标

### 默认定义
在当前系统中，`window_1430_1445_volume` 表示：
- 交易日 `14:30:00 ~ 14:45:00` 时间窗口内的成交量总和

### 默认时间口径
若基于 1 分钟线：
- 默认窗口定义为 `14:30:00 ~ 14:45:00`

若后续切换为已验证稳定的 5 分钟线：
- 可对应聚合 `14:35 / 14:40 / 14:45` 三根 5 分钟 bar 的成交量之和
- 但前提是 5 分钟 bar 时间标签语义已验证一致

## 推荐输出字段
每条指标结果建议至少包含：
- trading_day
- market
- symbol
- indicator_name
- indicator_label_cn
- window_start
- window_end
- base_interval
- volume_sum
- bar_count
- data_status
- data_source
- generated_at
- data_cutoff_time

## 指标命名规则说明
当前推荐命名采用：
- 开盘类窗口：`open_*`
- 通用固定时间窗：`window_HHMM_HHMM_*`

这样后续扩展时可以保持统一，例如：
- open_30m_volume
- window_1000_1030_volume
- window_1330_1400_volume
- window_1430_1445_volume

## 结论
当前先正式固定两项指标：
- `open_15m_volume`
- `window_1430_1445_volume`

这两个指标可作为后续盘中成交量特征、规则触发和归档数据集的基础字段。