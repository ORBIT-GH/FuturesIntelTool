# OpenClaw 读取契约

## 数据目录

桌面版和定时采集统一使用：

`%LOCALAPPDATA%\FuturesIntelTool`

最新日报入口：

`%LOCALAPPDATA%\FuturesIntelTool\reports\latest.json`

先读取 `latest.json`，取得 `report_dir`。只在该目录存在 `success.ok` 时处理。

## 默认读取

默认只读三个文件：

1. `manifest.json`
2. `daily-brief.md`
3. `anomalies.json`

不要默认读取 `report.html`、原始网页、PDF、完整新闻正文或 SQLite 明细。它们会把大量无关内容塞进上下文。

## 异常优先

`anomalies.json` 中的 `error` 表示关键数据缺失，`warning` 表示口径冲突或可选数据缺失，`info` 表示主力切换等提示。

## 按需查询

只有简报不足时，才通过统一查询入口获取少量结构化结果：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query market --product SH --date 2026-09-10 --limit 10
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query news --product SH --limit 10
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query runs --limit 10
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query health --limit 30
```

查询时始终带日期、品种和 limit。不要把整个数据库或全量新闻返回给模型。

## 数据优先级

- 交易所行情和日K：主数据。
- 持仓排名：只作为前20席位口径，不等同于全市场净持仓。
- 基差：必须同时说明合约、现货来源、报价口径和数据日期。
- 报告主体合约和持仓/基差合约不同时，不得合并成一个结论。
