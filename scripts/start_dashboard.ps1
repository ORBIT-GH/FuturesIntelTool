$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($env:FUTURES_INTEL_PYTHON) { $env:FUTURES_INTEL_PYTHON } else { "python" }
$env:PYTHONPATH = Join-Path $Root "src"
& $Python -m futures_intel --config (Join-Path $Root "config/default.json") serve
exit $LASTEXITCODE

