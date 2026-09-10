param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($env:FUTURES_INTEL_PYTHON) { $env:FUTURES_INTEL_PYTHON } else { "python" }
$env:PYTHONPATH = Join-Path $Root "src"
$UserConfig = Join-Path $env:LOCALAPPDATA "FuturesIntelTool\config\default.json"
$Config = if (Test-Path -LiteralPath $UserConfig) { $UserConfig } else { Join-Path $Root "config/default.json" }
& $Python -m futures_intel --config $Config @CliArgs
exit $LASTEXITCODE
