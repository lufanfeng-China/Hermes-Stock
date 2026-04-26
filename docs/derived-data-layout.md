# 派生数据层目录结构方案

## 目标
用于承载多个派生数据集，并支持：
- 盘中滚动更新
- 每日 final 归档
- 后续分析
- 回测与复盘
- 审计追溯

## 总体原则
1. 原始通达信数据不写回本目录。
2. 本目录只存系统派生结果，不存通达信整库副本。
3. provisional 与 final 分开存放。
4. bars、features、snapshots、logs 分层存放。
5. 每个数据集都要能看出：来源、周期、日期、版本。

## 推荐目录
```text
/home/lufanfeng/Project-Hermes-Stock/
├─ data/
│  ├─ standardized/
│  │  ├─ intraday/
│  │  │  ├─ 1m/
│  │  │  └─ 5m/
│  │  └─ daily/
│  │
│  ├─ derived/
│  │  ├─ bars/
│  │  │  ├─ provisional/
│  │  │  │  ├─ 15m/
│  │  │  │  ├─ 30m/
│  │  │  │  ├─ 60m/
│  │  │  │  └─ custom/
│  │  │  └─ final/
│  │  │     ├─ 15m/
│  │  │     ├─ 30m/
│  │  │     ├─ 60m/
│  │  │     └─ custom/
│  │  │
│  │  ├─ features/
│  │  │  ├─ provisional/
│  │  │  │  ├─ intraday/
│  │  │  │  └─ daily/
│  │  │  └─ final/
│  │  │     ├─ intraday/
│  │  │     └─ daily/
│  │  │
│  │  ├─ datasets/
│  │  │  ├─ provisional/
│  │  │  └─ final/
│  │  │
│  │  └─ manifests/
│  │     ├─ dataset_catalog/
│  │     ├─ lineage/
│  │     └─ versions/
│  │
│  ├─ snapshots/
│  │  ├─ market/
│  │  ├─ sectors/
│  │  ├─ stocks/
│  │  └─ portfolios/
│  │
│  ├─ archive/
│  │  ├─ trading_day=2026-04-24/
│  │  ├─ trading_day=2026-04-25/
│  │  └─ ...
│  │
│  └─ audit/
│     ├─ signals/
│     ├─ rules/
│     ├─ executions/
│     └─ exceptions/
│
└─ docs/
   └─ derived-data-layout.md
```

## 各目录职责
### 1. data/standardized/
用于存放从本地通达信或接口读出后、已经统一字段但还不算“业务派生”的标准化结果。

例如：
- 统一后的 1m bars
- 统一后的 5m bars
- 统一后的日线 bars

特点：
- 可重复生成
- 偏中间层
- 可短期缓存

### 2. data/derived/bars/
用于存放派生 K 线数据。

适合放：
- 15m
- 30m
- 60m
- 自定义 10m / 20m / 90m / 120m

推荐分层：
- provisional：盘中滚动结果
- final：收盘后正式归档结果

### 3. data/derived/features/
用于存放派生特征数据。

适合放：
- MA / EMA
- MACD / RSI / KDJ
- 波动率
- 强弱分数
- 量能特征
- 结构标签
- 策略输入特征

### 4. data/derived/datasets/
用于存放更高层的数据集结果，而不是单一 K 线或单一指标。

适合放：
- 候选池基础数据集
- 板块评分基础数据集
- 个股诊断输入数据集
- 多特征融合后的研究数据集

### 5. data/derived/manifests/
用于存放数据目录的“说明文件”。

适合放：
- dataset_catalog：当前有哪些派生数据集
- lineage：每个数据集由什么源、什么版本规则、什么周期生成
- versions：派生逻辑版本信息

### 6. data/snapshots/
用于存放业务快照。

适合放：
- 市场环境快照
- 板块快照
- 个股诊断快照
- 组合建议快照

### 7. data/archive/
用于按交易日归档最终结果。

建议按交易日分区：
```text
archive/
└─ trading_day=2026-04-24/
   ├─ bars/
   ├─ features/
   ├─ snapshots/
   └─ audit/
```

### 8. data/audit/
用于存放审计和追溯相关结果。

适合放：
- 正式信号
- 规则日志
- 执行动作变化
- 异常日志

## 推荐命名规则
### 派生 bars 文件名
```text
{dataset_name}__market={market}__symbol={symbol}__interval={interval}__date={trading_day}__status={status}__v={version}.parquet
```

示例：
```text
bars__market=sh__symbol=600519__interval=15m__date=2026-04-24__status=final__v=1.parquet
```

### 派生 feature 文件名
```text
{feature_set}__market={market}__symbol={symbol}__interval={interval}__date={trading_day}__status={status}__v={version}.parquet
```

示例：
```text
momentum_pack__market=sz__symbol=000333__interval=60m__date=2026-04-24__status=final__v=3.parquet
```

## 推荐元数据字段
每个派生数据文件或表，至少应有：
- dataset_name
- market
- symbol 或 sector_id
- base_interval
- target_interval
- trading_day
- data_status
- data_source
- storage_layer
- derived_from
- derivation_version
- generated_at
- data_cutoff_time

## 对你当前场景的建议
你后续会有多个派生数据，并且要每天计算归档，因此推荐优先采用：

1. 盘中：
- 写 provisional
- 用于滚动分析

2. 收盘后：
- 统一固化为 final
- 按 trading_day 分区归档
- 供后续分析、复盘、回测使用

## 现阶段最实用的最小落地版
如果先不引入数据库，建议先这样落地：
```text
data/
├─ derived/
│  ├─ bars/
│  │  ├─ provisional/
│  │  └─ final/
│  ├─ features/
│  │  ├─ provisional/
│  │  └─ final/
│  └─ manifests/
├─ snapshots/
├─ archive/
└─ audit/
```

文件格式优先建议：
- parquet：分析友好，适合时间序列与归档
- json：适合 manifest、catalog、快照说明

## 结论
对于“多个派生数据 + 每日归档”的场景，最适合的是：
- 原始数据只读直连
- 系统内部建立独立的 derived 数据资产层
- provisional / final 分层
- bars / features / datasets / snapshots / audit 分层
- 按 trading_day 做归档分区
