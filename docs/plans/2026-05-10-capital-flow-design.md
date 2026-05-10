# A股资金流向数据方案

> **Goal:** 从东方财富公开 API 拉取全市场个股每日资金流向，本地存储为派生数据集，每日增量更新，接入前端。

**数据源:** 东方财富 `push2his.eastmoney.com` 资金流向日线 API  
**跨度:** 每只股票最近 120 个交易日  
**规模:** 5510 只 × 120 条 × 15 字段，Parquet 约 30-60 MB

---

## 1. API 字段

每条 kline 为逗号分隔字符串，15 个字段：

| 字段 | 含义 | 单位 |
|------|------|------|
| f51 | 交易日期 | YYYY-MM-DD |
| f52 | 主力净流入 (超大单+大单) | 元 |
| f53 | 小单净流入 (<4万) | 元 |
| f54 | 中单净流入 (4万~20万) | 元 |
| f55 | 大单净流入 (20万~100万) | 元 |
| f56 | 超大单净流入 (≥100万) | 元 |
| f57 | 主力净流入占比 | % |
| f58 | 小单净流入占比 | % |
| f59 | 中单净流入占比 | % |
| f60 | 大单净流入占比 | % |
| f61 | 超大单净流入占比 | % |
| f62 | 收盘价 | 元 |
| f63 | 涨跌幅 | % |
| f64 | 预留 | — |
| f65 | 预留 | — |

接口: `https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=0&klt=1&secid={market}.{code}&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65`

market: 深市=0, 沪市=1

---

## 2. 数据存储

### 命名
```
dataset_stock_capital_flow_current
```

### 位置
```
data/derived/datasets/final/dataset_stock_capital_flow.parquet
data/archive/trading_day={YYYY-MM-DD}/datasets/dataset_stock_capital_flow.parquet
```

### Schema (Parquet 列)
```
trading_day: str      # YYYY-MM-DD
symbol: str            # 6位代码
stock_name: str        # 股票名称
market: str            # sh / sz / bj
net_main_force: float  # 主力净流入(元)
net_small: float       # 小单净流入
net_medium: float      # 中单净流入
net_large: float       # 大单净流入
net_super_large: float # 超大单净流入
pct_main_force: float  # 主力净流入占比
pct_small: float       # 小单净流入占比
pct_medium: float      # 中单净流入占比
pct_large: float       # 大单净流入占比
pct_super_large: float # 超大单净流入占比
close: float           # 收盘价
gain_pct: float        # 涨跌幅
data_source: str       # "eastmoney"
generated_at: str      # 抓取时间
```

注意：东方财富返回的单位是**元**（不是万元），存储时按元存，前端展示时转亿/万。

---

## 3. 同步策略

### 首次全量
5510 只股票，单股票查询，需强限速：
- 间隔：2-3 秒/次（避免断连）
- 总耗时：约 3-4.5 小时
- 分 3 批跑：每批 ~1800 只，间隔 1 小时
- 或：单脚本后台跑，带断点续传（已抓取的跳过）

### 每日增量
收盘后跑一次：
- 只拉每只股票最近 1-2 天
- 追加到 Parquet，去重
- 耗时：同样 3-4 小时（单股票查询不可避免）
- 优化：可考虑分多进程并行（需确认 IP 限速粒度）

### 容量控制
- 每只股票保留最近 120 天
- 更早数据自动滚动淘汰
- Parquet 保持 ~60MB 可控

---

## 4. 同步脚本

单文件自包含脚本，进入后台运行，不消耗对话 token：

```
scripts/sync_capital_flow.py
```

核心逻辑：
```
1. 读取 stock universe (从 industry_current 数据集)
2. 逐只调东方财富 API，限速 3s/次
3. 解析 klines，构建 DataFrame
4. 追加写入 Parquet (去重 by trading_day+symbol)
5. 滚动淘汰 >120 天的旧数据
6. 打印统计: OK N/5510, failed M, new rows K, duration Xh
7. 写入 _SUCCESS / _FAILED 标记
```

断点续传：每 100 只写一次 check point 文件，中断后可从断点继续。

---

## 5. Cron 配置

```bash
# 每个交易日 15:30 执行 (收盘后)
30 15 * * 1-5 ~/.venvs/moontdx-china-stock-data/bin/python \
  /home/lufanfeng/Project-Hermes-Stock/scripts/sync_capital_flow.py \
  --mode incremental --notify
```

`--notify` 参数跑完后通过 Hermes 通知结果。

---

## 6. 前端接入（后续阶段）

### API 端点
```
GET /api/stock-capital-flow?symbol=000001&days=20
```
返回最近 N 天的资金流向数据，JSON 格式。

### 可视化位置（三选一，后续确认）
- **K 线图下方叠加:** 量柱替换/叠加为资金流向柱（红流入绿流出）
- **独立资金流向页:** 个股资金流向详情 + 全市场资金流向排名
- **stock-score 页集成:** 在财务评分页增加资金流向维度的评分

---

## 7. 与现有体系的关系

| 现有数据集 | 关系 |
|-----------|------|
| dataset_stock_rps_current | 同类定位——派生数据资产，每日更新，前端查询 |
| dataset_stock_screener_strategies_current | 独立，不交叉 |
| financial_snapshot_2026Q1 | 财报维度，与资金流向互补 |

资金流向加入后，前端可做"财务面 + 资金面 + 技术面"三合一分析。

---

## 8. 风险点

| 风险 | 缓解 |
|------|------|
| 东方财富限速/封 IP | 3s 间隔 + 分批 + 断点续传 |
| API 字段变更 | 固定 fields2 参数，变更时脚本报错即停 |
| 北交所无数据 | 标记为 NA，不阻塞沪深同步 |
| 首次全量 4 小时 | 拆 3 批，或在周末/夜间跑 |
| token 消耗 | 全程脚本自包含，0 token |

---

## 9. 执行顺序

1. **方案确认** ← 当前
2. **写同步脚本** `scripts/sync_capital_flow.py`
3. **首次全量同步**（后台跑 3-4 小时）
4. **验证数据质量**（抽查 5-10 只股票）
5. **配 Cron** 每日增量
6. **加 API 端点** `/api/stock-capital-flow`
7. **前端接入** K 线叠加或独立页
