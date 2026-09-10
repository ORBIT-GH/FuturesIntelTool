param([string]$TaskName = "FuturesIntelDaily")
$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Scheduled task removed: $TaskName"

