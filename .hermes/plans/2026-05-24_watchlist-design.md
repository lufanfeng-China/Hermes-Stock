# 自选股页面设计方案

**日期**: 2026-05-24  
**目标**: 新增「自选股」页面，支持从筛选器挑选股票加入清单，集中展示关键指标，点击弹窗看 K 线。

---

## 一、数据存储

**文件**: `data/derived/watchlist.json`

```json
{
  "stocks": [
    {"market": "sh", "symbol": "600519", "added_at": "2026-05-24T15:30:00"}
  ],
  "updated_at": "2026-05-24T15:30:00"
}
```

- 只存 `market + symbol + added_at`，不做排序字段（顺序 = 数组顺序，允许拖拽调整）。
- 所有展示字段实时从现有数据管线计算（复用 `build_stock_screener_response`），保证数据始终最新。

---

## 二、API 端点（服务端，`serve_stock_dashboard.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/watchlist` | 返回自选股清单 + 完整展示数据 |
| POST | `/api/watchlist/add` | 添加股票 `{market, symbol}` |
| POST | `/api/watchlist/remove` | 移除股票 `{market, symbol}` |
| POST | `/api/watchlist/reorder` | 调整顺序 `{stocks: [{market, symbol}, ...]}` |

**`GET /api/watchlist` 返回结构**:

```json
{
  "stocks": [
    {
      "market": "sh", "symbol": "600519", "stock_name": "贵州茅台",
      "current_price": 1680.00,
      "industry_level_1": "食品饮料",
      "industry_level_2": "白酒",
      "market_total_score": 72.5,
      "market_total_rank": 128,
      "market_total_universe_size": 5192,
      "industry_total_score": 68.3,
      "industry_total_rank": 3,
      "industry_total_universe_size": 42,
      "industry_temperature_label": "偏热",
      "industry_temperature_percentile_since_2022": 72.5,
      "tech_trend": 3,
      "tech_trend_label": "多头排列",
      "tech_momentum": 2,
      "tech_momentum_label": "强势",
      "tech_volume_signal": 1,
      "tech_volume_label": "放量",
      "tech_buy_trigger": true,
      "tech_buy_trigger_label": "突破买入",
      "tech_conclusion": 1,
      "tech_conclusion_label": "建议关注",
      "tech_conclusion_color": "#00e676",
      "tech_conclusion_reason": "趋势向上，量价配合良好",
      "dim_scores": { "profitability": 82, ... },
      "rps_20": 85.2, "rps_50": 78.1, "rps_120": 65.3, "rps_250": 55.0
    }
  ]
}
```

- 后端循环读取 watchlist.json，对每只股票调 `compute_stock_score(market, symbol)` 获取评分/排名/行业数据。
- 技术面数据从 `dataset_technical_eval.json` 读取。
- 行业温度从 `dataset_industry_valuation_current.json` 读取。
- 如果某只股票数据缺失（新上市、停牌等），标记 `_error` 字段而不崩溃。

---

## 三、前端页面（`web/watchlist.html` + `web/watchlist.js`）

### 3.1 页面布局

```
┌─────────────────────────────────────────────────────────┐
│ 顶部导航栏  [财务评分] [股票筛选] [实时选股] [RPS] [自选股] [回测] │
├─────────────────────────────────────────────────────────┤
│  WATCHLIST                             已选 12 只  [导出] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─ 股票名 / 代码 ───┬── 全市场 ──┬── 行业内 ──┬── 行业 ──┬ 温度 ┬ 趋势 ┬ 动向 ┬ 量价 ┬ 买入 ┬ 综合结论 ─┐
│  │ 贵州茅台          │ 72.5      │ 68.3       │ 白酒     │ 🟡偏热│🟢多头│🟢强势│🟢放量│✅触发│🟢建议关注  │
│  │ sh:600519         │ #128/5192 │ #3/42      │ 食品饮料  │ 72.5% │      │      │      │      │            │
│  ├───────────────────┼───────────┼────────────┼──────────┼──────┼──────┼──────┼──────┼──────┼────────────┤
│  │ 宁德时代          │ 68.1      │ 71.2       │ 电池     │ 🟢常温│🟡震荡│🔴弱势│🟡缩量│❌未触发│🟡观望      │
│  │ sz:300750         │ #312/5192 │ #1/28      │ 电力设备  │ 45.2% │      │      │      │      │            │
│  └───────────────────┴───────────┴────────────┴──────────┴──────┴──────┴──────┴──────┴──────┴────────────┘
│                                                         │
│  点击任意行 → 弹出 K 线弹窗                               │
│  拖拽行 → 调整排序（可选，MVP 可省略）                     │
│  行末 [✕] → 移出                                                    │
└─────────────────────────────────────────────────────────┘
```

### 3.2 表格列设计

| 列 | 数据源字段 | 显示格式 |
|----|-----------|---------|
| **股票** | stock_name + market:symbol | 贵州茅台 `sh:600519` |
| **全市场** | market_total_score, market_total_rank, market_total_universe_size | `72.5` / `#128/5192` |
| **行业内** | industry_total_score, industry_total_rank, industry_total_universe_size | `68.3` / `#3/42` |
| **行业** | industry_level_1, industry_level_2 | 白酒 / 食品饮料 |
| **温度** | industry_temperature_label, percentile | 🟡偏热 72.5%（信号灯颜色由 percentile 决定） |
| **趋势** | tech_trend_label | 🟢多头排列 |
| **动向** | tech_momentum_label | 🟢强势 |
| **量价** | tech_volume_label | 🟢放量 |
| **买入触发** | tech_buy_trigger_label | ✅触发 / ❌未触发 |
| **综合结论** | tech_conclusion_label + color | 🟢建议关注（颜色动态） |
| 操作 | — | [✕] 移除 |

**信号灯规则**（温度列）:
- `percentile ≥ 80%` → 🔴 过热
- `60% ≤ percentile < 80%` → 🟡 偏热
- `40% ≤ percentile < 60%` → 🟢 常温
- `20% ≤ percentile < 40%` → 🔵 偏冷
- `< 20%` → ⚪ 冰点
- 无数据 → `—`

**信号灯规则**（趋势/动向/量价列）:
- 直接用 `tech_xxx_label` 值 + 颜色；label 为 `"多头排列"`/`"强势"`/`"放量"` 等偏多词时绿色，偏空词时红色，中性词时灰色。

**综合结论列**: 直接用 `tech_conclusion_color` 着色，显示 `tech_conclusion_label`，hover tooltip 显示 `tech_conclusion_reason`。

### 3.3 空态

```
┌─────────────────────────────────────────┐
│                                         │
│         📋 自选股清单为空                │
│                                         │
│    前往 股票筛选 页面，勾选感兴趣的股票    │
│    然后点击「加入自选」即可在此查看        │
│                                         │
│         [前往股票筛选]                    │
│                                         │
└─────────────────────────────────────────┘
```

### 3.4 K 线弹窗

- 点击表格行 → 打开 `<dialog>` 弹窗。
- 完全复用 `stock-score.html` 的 K 线实现：`KlineChart` 类（来自 `kline-chart.js`）+ `/api/stock-kline` 端点。
- 弹窗尺寸：`width: 95vw; max-height: 90vh`（同 stock-score 页）。
- 弹窗内显示：股票名 + 代码 + K 线图（250 bar）+ 关闭按钮。
- K 线图包含：OHLC + 成交量 + RPS20/50/120/250 叠加线（同 stock-score 的实现）。
- 点击遮罩层或关闭按钮关闭弹窗。

---

## 四、从筛选器添加自选股

在 `stock-screener.html` 页面上新增：

### 4.1 「加入自选」按钮

- 位置：筛选结果表格上方工具栏区域（和「同步到AI股池」「方案回测」同级）。
- 按钮文案：`⭐ 加入自选 (已选 N 只)`
- 逻辑：收集所有勾选的 checkbox → POST `/api/watchlist/add`（支持批量）。
- 去重：后端自动跳过已存在的股票。

### 4.2 批量添加 API

```
POST /api/watchlist/add
Body: { "stocks": [{"market": "sh", "symbol": "600519"}, ...] }
Response: { "ok": true, "added": 3, "skipped": 1 }
```

### 4.3 从 stock-score 页也能加

- stock-score 页面选中某只股票后，在顶部名称区域旁边加一个小 ⭐ 按钮。
- 点击即 `POST /api/watchlist/add` 单只添加。

---

## 五、涉及的文件

### 新建
| 文件 | 说明 |
|------|------|
| `web/watchlist.html` | 自选股页面 HTML |
| `web/watchlist.js` | 自选股页面 JS（表格渲染、排序、弹窗、API 调用） |

### 修改
| 文件 | 改动 |
|------|------|
| `scripts/serve_stock_dashboard.py` | 新增 4 个 API 端点 + 路由注册 + watchlist 静态文件服务 |
| `web/stock-screener.html` | 新增「加入自选」按钮 |
| `web/stock-screener.js` | 按钮事件 + 批量添加逻辑 |
| `web/stock-score.html` | 新增 ⭐ 按钮 |
| `web/stock-score.js` | ⭐ 按钮事件 + 单只添加逻辑 |
| 各页面顶部导航栏 | 新增「自选股」链接（stock-score, stock-screener, realtime-screener, rps-pool, backtest） |

---

## 六、技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 数据存储 | 本地 JSON 文件 | 无后端数据库依赖，与项目现有一致 |
| 数据刷新 | 实时计算（每次 GET /api/watchlist 都跑 compute） | 股票数据本来就每次加载，无额外成本 |
| K 线组件 | 复用 kline-chart.js | 已有成熟实现，避免重复开发 |
| 排序 | MVP 先不做拖拽，按添加时间倒序 | 降低复杂度，后续可加 |
| 批量操作 | 支持批量添加/移除 | 筛选器勾选多只是常见场景 |
| 股票标识 | `market + symbol`（如 sh:600519） | 与系统其他模块一致 |

---

## 七、开发步骤

1. **后端 watchlist 存储** — `serve_stock_dashboard.py` 新增 watchlist CRUD 辅助函数 + 4 个 API 端点路由
2. **后端 GET /api/watchlist** — 核心：读取 watchlist.json → 批量调 `compute_stock_score` + 读技术面 → 组装返回
3. **前端 watchlist.html + watchlist.js** — 页面骨架 + 表格渲染 + 信号灯逻辑
4. **前端 K 线弹窗** — 复用 `KlineChart` + `/api/stock-kline`
5. **前端空态** — 空自选引导页
6. **stock-screener 加按钮** — 「加入自选」按钮 + 批量添加 JS
7. **stock-score 加 ⭐ 按钮** — 单只快速添加
8. **全站导航更新** — 6 个页面顶部加「自选股」链接
9. **端到端验证** — 启动服务 → 筛选页勾选 → 加入自选 → 自选页查看 → 点击弹 K 线

---

## 八、风险和注意事项

- **性能**：如果自选股数量很大（>50 只），`GET /api/watchlist` 可能较慢，因为每只股票都要调 `compute_stock_score`。可以在响应里加 loading 状态，前端逐步渲染。
- **数据一致性**：技术面数据（`dataset_technical_eval.json`）只在数据更新管线刷新时更新。如果用户当天看自选股但管线未跑，技术面数据可能是旧的。
- **去重**：后端 `POST /api/watchlist/add` 必须做去重，避免同一只股票重复添加。
