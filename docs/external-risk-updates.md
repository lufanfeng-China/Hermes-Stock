# 外部风险数据：独立手动更新

这两个任务**不进入日更、cron或策略**，互相独立，每次联网均重建完整快照，不是增量追加。

## 页面入口与独立任务

打开 `http://127.0.0.1:8765/data-update.html`，任务清单的“不定期更新”分组包含：

- `update_company_pledge`：更新公司整体质押，不冒充大股东个人持股质押率。
- `update_related_transactions`：更新2026年公告范围内关联交易明细，不生成未经核准的关联销售收入占比。

每行有独立“执行/重试”按钮，调用 `POST /api/data-update-task`，JSON为 `{"task_id":"对应任务ID"}`。两项不进入“启动更新”的常规流程或常规重试子集；若最近一次失败的是这两项之一，“重试失败项”只重跑该项。单项失败不禁用常规启动按钮。

状态API `GET /api/data-update-plan` 返回 `current_status.company_pledge`、`current_status.related_transactions`，以及任务的 `manual_only=true`、当前job的 `mode/task_name`。页面同时展示数据日期、入库时间、覆盖条数、旧记录条数及最近失败；服务重启后仍从JSON恢复可信快照和单项失败提示。运行时共享更新锁以防重复启动，其他任务暂时禁用不表示存在前置依赖。

新快照保存在项目内 `data/external_risk`（不纳入git），不会覆盖桌面的既有下载归档。失败保留旧可信快照及失败run证据。

## 命令

在项目根目录运行（仅 Python 标准库，Linux/WSL）：

```bash
python3 scripts/update_external_risk.py --dataset company_pledge
python3 scripts/update_external_risk.py --dataset related_transactions

# 已有归档导入，不联网、不执行归档中的任何脚本
python3 scripts/update_external_risk.py --dataset company_pledge --import-from /absolute/archive
python3 scripts/update_external_risk.py --dataset related_transactions --import-from /absolute/archive

# 隔离测试/演练根目录（就是 external_risk 目录本身，不是项目根）
python3 scripts/update_external_risk.py --dataset company_pledge --import-from /absolute/archive --root /tmp/external-risk-trial
```

退出码0成功、1失败；参数错误为argparse退出码2。阶段输出为`[1/3] 开始构建`、分页/首屏复核、`[2/3] 开始构建导出与逐行读回校验`、`[3/3] 完成/失败`，导出等待也有明确阶段。

默认存储位置由模块相对项目路径确定，与启动cwd、桌面、/tmp无关：

```text
data/external_risk/<dataset>/
  .update.lock                 # flock跨进程同数据集互斥，进程退出自动释放
  current.json                 # 仅成功时原子替换，小型状态+成功run绝对路径
  last_attempt.json            # 本次运行/失败信息，失败不覆盖current
  runs/<UTC时间戳_唯一后缀>/
    raw/page_0001.json ...     # 联网模式保存原始HTTP分页响应
    raw/*_request.json        # 请求URL/参数/时间
    raw/final_first_page_recheck.json
    config.json               # 联网模式冻结口径、总数、页数
    data.csv                  # UTF-8 BOM，全部源字段+精确换算/行hash
    data.jsonl.gz             # 全字段；NULL保留；Decimal以精确字符串序列化
    by_date/YYYY-MM-DD.jsonl   # 质押专用，各实际数据日期独立分表
    coverage.json             # 公司记录数、日期分布、币种、交易类型分布
    import_evidence/           # 导入时保留已校验源数据/JSON/CSV/gzip及源manifest
    metadata.json             # 最终验证通过才complete；失败则complete=false
    sha256_manifest.json      # 项目内产物哈希
```

不自动清理历史版本。失败run保留证据。`current.json`写入使用同目录临时文件和os.replace原子替换；只有全部验证成功才发布。提交后的最终进度通知属于非关键输出，通知失败不得改写已发布metadata或manifest，也不得把已发布快照标成失败。不同数据集可以独立运行，同数据集重复启动立即失败，不启动第二轮下载。

## Python接口

```python
from app.data.external_risk_updates import update_external_risk, load_external_risk_status

metadata = update_external_risk('company_pledge', root=None, import_from=None)
status = load_external_risk_status(root=None)
# status['company_pledge'] / status['related_transactions']
```

更新函数返回成功metadata；失败抛异常并保存last_attempt，旧current不变。测试可注入`fetcher(params)->API响应dict`及`progress(line)`，生产默认使用限速HTTP客户端。

状态入口**只读current.json和last_attempt.json，不扫描原始页、CSV或JSONL，也不创建缺失目录**。每个entry包含`updated_at,data_date,row_count,company_count,latest_date_rows,older_date_rows,snapshot_path,error,warning,source_scope,available`。此外成功结果包含`acquisition_mode,source_downloaded_at,started_at,date_distribution,complete`等。旧快照可用但最近更新失败时，`available=true`与`error`会同时存在，应同时展示旧数据和失败提示。

`acquisition_mode=import`只表示本次导入时间；`source_downloaded_at`保留归档来源下载时间，绝不冒充网络新拉取。导入额外记录`imported_from`。联网为`network_full_snapshot`。

## 来源与验证边界

公开接口：`https://datacenter-web.eastmoney.com/api/data/v1/get`；`columns=ALL`；每页真实最大500；请求起始至少相隔2秒（含重试），40秒超时、最多3次尝试。逐页验证count/pages、页码连续、每页期望条数及尾页，总条数精确匹配；最后重新请求冻结查询首屏，验证首屏内容和总数未变。发布前的完整性异常阻断发布，不将空返回发布为“全市场零风险”。它仍是公开聚合源快照，不冒充公告级审计。

### 公司整体质押

- 报表`RPT_CSDC_LIST_NEWEST`，稳定排序`SECURITY_CODE,SECUCODE`。
- 是公司整体未解押统计，**不是大股东个人质押率**。
- 数量保留源单位万股、市值万元、比例百分点（0.13即0.13%）。NULL不补0。
- 逐行`TRADE_DATE`分表，最新日期行数与较早行数分别统计，旧值不称为当前余额；下载时间不当数据日期。无源记录不等于无质押。

### 关联交易

- 报表`RPT_RELATED_TRADE`；仅`2026-01-01`起至本次最新2026公告日冻结。
- CLI/页面默认按月重建全年范围（`--strategy monthly`），不是只更新当月、不是缩减范围。每月分页/首屏独立校验，允许来源确实为空的月份；每月变化最多重试3次。最后复核各月count、全年count与各月总和，变化月份重取，最多3轮；未稳定仍失败保留旧current。避免一条新增记录导致整个全年六分钟下载全部作废。`--strategy full`保留原始全年单序列模式；Python接口显式使用`download_strategy='monthly'`选择同一分片路径。
- 分片原始响应保存在`partitions/YYYY-MM/attempt_N/raw/`；成功metadata的`partitions`指向每月最终通过的尝试，失败尝试也保留。根`raw/final_annual_recheck.json`记录年度总数复核。分片只改变抓取方式，不改变金额、公告范围、重复保留及CSV/JSONL完整读回要求。公开接口不提供原子快照，校验通过仍不等于公告级无遗漏证明。
- 稳定多列排序`NOTICE_DATE,SECURITY_CODE,EID,RELATED_PARTY,TRADE_WAY,END_DATE,TRADE_AMT`。
- `TRADE_AMT`是万原币，`Decimal(str(value))*10000`输出`_AMOUNT_UNITS`元原币；不换汇，币种缺失不猜人民币；NULL仍为NULL。
- `OPERATE_INCOME`、`NETPROFIT`是元，保持来源值不放大；财报期间不擅自解码。
- **公告年不是交易发生年**。混合销售、采购、担保、借款、资产交易、预计额度等，不求和除营收，不输出“关联销售收入占比”。
- EID不是唯一行键；精确重复也原样保留。原始页、CSV、JSONL通过Counter校验整行重复出现次数，不只比较hash集合。

## 既有归档导入契约

支持已核验桌面归档格式，但未来更新不依赖其位置：

- 必须有非空`sha256_manifest.json`（相对路径→SHA256）、`verification.json`且passed=true、连续`raw/page_NNN.json`；校验每一个manifest文件哈希、路径安全、count/pages/条数。
- 质押主文件`company_pledge_latest.json`的data必须逐行及重复次数与raw一致。
- 关联交易主文件`related_transactions_2026.jsonl.gz`必须与raw逐行及重复次数一致。使用`config.json`时，该文件也必须在源manifest中并通过哈希校验；公告截止必须是真实有效的2026年日期，且每条记录都独立受2026-01-01至2026-12-31硬边界约束，不能通过扩大config截止越过年度范围。
- 如归档带原始中文明细CSV，另核对所有已知源字段、行hash重复次数与金额单位，不只信CSV中自带的hash列。
- 在项目run重新导出CSV/JSONL并完整读回后才发布。归档脚本不复制、更不执行。导入行为不联网，不伪装增量或网络更新。

## 自动化验证

```bash
python3 -m unittest discover -s tests -p test_external_risk_updates.py -v
```

测试覆盖只读metadata、分页/尾页/空返回/总数变化/首屏漂移、失败保护旧current、日期分表、Decimal单位、NULL、公告范围、重复次数、源hash、CSV字段篡改、进程锁、HTTP限速重试超时和CLI导入。测试使用隔离临时根目录及明确的离线fixture，不下载全量、不启动服务。
