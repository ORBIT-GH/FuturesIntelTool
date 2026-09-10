param(
    [string]$TaskName = "FuturesIntelDaily",
    [string]$At = "18:05"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $PSScriptRoot "run_daily.ps1"
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Futures Intel daily collection and OpenClaw report delivery" `
    -Force | Out-Null
Write-Output "Scheduled task installed: $TaskName at $At"

