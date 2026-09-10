---
name: futures-intel-reader
description: Read the local FuturesIntelTool daily report and query its SQLite database. Use when the user asks for futures news, market snapshots, daily briefs, positions, basis, coal prices, or the latest futures report.
---

# Futures Intel Reader

## Data Root

Use:

`$env:LOCALAPPDATA\FuturesIntelTool`

If that directory does not exist, fall back to:

`E:\咨询爬虫`

## Default Daily Read

1. Read `reports\latest.json` from the data root.
2. Resolve its `report_dir`.
3. Require `success.ok` in that directory before treating the report as complete.
4. Read only these files by default:
   - `manifest.json`
   - `daily-brief.md`
   - `anomalies.json`
5. Answer from the brief first. Do not open HTML, PDF, raw web pages, the full news corpus, or all SQLite tables unless the user explicitly asks for more detail.

## Refresh On Demand

If the latest report is missing or older than the date requested by the user, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\run_daily.ps1
```

Then re-read `reports\latest.json` and the default three files.

Do not refresh when the latest report already covers the requested trading date. Do not run the collector repeatedly.

## Deep Queries

Use the local query wrapper only when the brief is insufficient:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query market --product SH --date 2026-09-10 --limit 10
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query news --product SH --limit 10
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query runs --limit 10
powershell -NoProfile -ExecutionPolicy Bypass -File E:\咨询爬虫\scripts\query.ps1 query health --limit 30
```

Always include a date, product code, and a small limit when possible.

## Interpretation Rules

- Exchange quotes and daily bars are primary data.
- Position tables cover the exchange-reported top 20 seats, not the entire market.
- Basis records must state contract, source, pricing basis, and data date.
- If the report contract differs from the position or basis contract, never merge them into one conclusion.
- Optional data such as coal may be absent. Report it as missing rather than inventing a value.

