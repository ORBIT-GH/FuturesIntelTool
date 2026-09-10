param(
    [string]$Date = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($env:FUTURES_INTEL_PYTHON) { $env:FUTURES_INTEL_PYTHON } else { "python" }
$env:PYTHONPATH = Join-Path $Root "src"
$UserRoot = Join-Path $env:LOCALAPPDATA "FuturesIntelTool"
$UserConfig = Join-Path $UserRoot "config\default.json"
$Config = if (Test-Path -LiteralPath $UserConfig) { $UserConfig } else { Join-Path $Root "config/default.json" }
$DataRoot = if (Test-Path -LiteralPath $UserConfig) { $UserRoot } else { $Root }
$LogDir = Join-Path $DataRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Day = if ($Date) { $Date } else { Get-Date -Format "yyyy-MM-dd" }
$LogFile = Join-Path $LogDir ("run-" + $Day + ".log")
$Arguments = @("-m", "futures_intel", "--config", $Config, "scheduled-run")
if ($Date) { $Arguments += @("--date", $Date) }
"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') =====" | Out-File -LiteralPath $LogFile -Append -Encoding utf8
$Output = & $Python @Arguments 2>&1
$Code = $LASTEXITCODE
$Output | Tee-Object -FilePath $LogFile -Append
exit $Code
