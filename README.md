# Hermes Stock

这是一个重新清空后的起始仓库，用于开始新的 A 股系统设计方案。

当前状态：
- 已保留 Git 仓库
- 已清空旧项目内容（当前仅保留基础说明与通用忽略规则）
- 后续设计文档统一放在 `docs/`
- 参考资料统一放在 `references/`

本地看盘页：
- 启动 `python3 scripts/serve_stock_dashboard.py`
- 页面保留原有 `/api/stock-window-volume` 图表能力
- 新增本地股票搜索（代码 / 中文名 / 首字母缩写）与概念搜索，数据分别来自 Tongdaxin `*.tnf` 和 `data/derived/datasets/final/*.json`

建议下一步：
1. 明确新的产品目标与页面范围
2. 输出主设计文档
3. 输出实施路线图
4. 再决定是否生成代码骨架
