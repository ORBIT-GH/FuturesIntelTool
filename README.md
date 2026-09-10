# 期货资讯工具

本工具面向本地期货研究流程：采集行情、持仓和基差，写入 SQLite，生成精简日报，并把供 OpenClaw 使用的文件、CLI 和可视化看板放在同一套结构中。

## 当前功能

- Sina 实时行情和日K：自动按持仓量、成交量判定主力合约。
- 交易法门公开数据：前20席位持仓、基差历史。
- CCTD：秦皇岛、环渤海、综合交易、长协煤等煤价指标。
- RSS：可配置多源新闻抓取，按内容哈希去重。
- 本地导入：JSON、JSONL、CSV、TSV 新闻和现货价格。
- SQLite：`data/market.sqlite`，主键和 UNIQUE 约束保证重抓幂等。
- 日报：`daily-brief.md`、`anomalies.json`、`report.html`、`manifest.json` 和 `success.ok`。
- OpenClaw：默认只读简报和异常；需要细节时再调用 CLI 查询。
- 看板：查看品种快照、数据源健康、异常和日报，支持手动采集。

## 桌面窗口

主程序提供独立的 Windows 可视化窗口，不依赖浏览器。窗口内可以查看行情、数据源健康、异常和日报，也可以在“合约设置”页新增、删除、切换品种，或者为任意品种选择：

- 自动主力
- 固定合约，例如 `SH2701`

设置会保存到配置文件中。打包后的 EXE 首次启动时，会自动在 `%LOCALAPPDATA%\FuturesIntelTool` 创建配置、数据库、日报和日志目录。

## 快速开始

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m futures_intel --config config/default.json init
python -m futures_intel --config config/default.json run
python -m futures_intel --config config/default.json serve
```

浏览器打开 `http://127.0.0.1:8765`。

也可以使用包装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_daily.ps1
powershell -ExecutionPolicy Bypass -File scripts\start_dashboard.ps1
```

## 每天 18:05 自动运行

脚本只负责安装 Windows 计划任务，不会自动替你注册：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
```

默认任务名是 `FuturesIntelDaily`，每天 18:05 触发。非交易日和法定节假日会由 `scheduled-run` 自动跳过。卸载：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_task.ps1
```

## 修改合约

默认不写死合约，脚本每天按持仓量自动判定主力，持仓相同时比较成交量。

如果要固定某个品种的合约，在 `config/default.json` 的对应品种中增加 `contract_override`：

```json
{"code": "SH", "name": "烧碱", "exchange": "CZCE", "contract_override": "SH2701"}
```

修改后重新运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_daily.ps1
```

删除 `contract_override` 字段后，该品种恢复自动主力判定。持仓和基差如果来自另一个交易所主力合约，日报会在 `anomalies.json` 中提示口径不一致，不会把两者静默混用。

## OpenClaw 默认读取顺序

1. `reports/latest.json` 找到最新日报目录。
2. 检查该目录存在 `success.ok`。
3. 读取 `manifest.json`。
4. 默认只读 `daily-brief.md` 和 `anomalies.json`。
5. 需要细节时查询 SQLite，不要默认读取 HTML、PDF、原始网页或全部新闻正文。

查询示例：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m futures_intel --config config/default.json query market --product SH --date 2026-09-10
python -m futures_intel --config config/default.json query news --product SH --limit 10
```

## 新闻和现货数据

RSS 源配置在 `config/default.json` 的 `rss_feeds`。默认留空，避免直接绑定不稳定或未授权站点。

涛哥的 CSV/JSON 数据可以导入：

```powershell
python -m futures_intel --config config/default.json import-spot `
  --file data\taoge-spot.csv `
  --product SH `
  --spec "32%液碱" `
  --region 山东 `
  --source taoge
```

新闻文件也可以导入：

```powershell
python -m futures_intel --config config/default.json import-news `
  --file data\news.json `
  --source manual
```

## 数据口径

- 交易日使用日盘所在日期；夜盘属于下一交易日，`session` 字段预留 `day/night/full`。
- 主力按未到期合约的持仓量最大判定，持仓相同则比较成交量。
- 主力切换在收盘数据完整后生效，并在日报中标记。
- 基差来源目前是交易法门公开口径。现货价、期货价和基差是否齐全，取决于上游是否同时提供。
- 煤价是 CCTD 首页公开指标，页面结构变化时可能需要调整解析规则。

## 打包发给别人

首次安装 PyInstaller 并构建：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1 -InstallBuildDeps
```

后续重新构建：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
```

生成文件：

`dist\FuturesIntelTool.exe`

这是单文件 Windows 程序，可以直接发送给别人。对方首次运行时会在自己的用户目录创建数据文件，不需要安装 Python、浏览器或 OpenClaw。

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

本项目只做资讯整理，不构成投资建议。使用前应确认各数据源的访问条款和再分发限制。
