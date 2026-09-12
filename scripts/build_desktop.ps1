param(
    [string]$Name = "FuturesIntelTool",
    [switch]$InstallBuildDeps
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($env:FUTURES_INTEL_PYTHON) { $env:FUTURES_INTEL_PYTHON } else { "python" }
$Src = Join-Path $Root "src"
$Entry = Join-Path $Root "desktop_app.py"
$Resources = Join-Path $Src "futures_intel\resources"

if ($InstallBuildDeps) {
    & $Python -m pip install --upgrade pyinstaller -e $Root
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Re-run with -InstallBuildDeps."
}

Set-Location $Root
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $Name `
    --paths $Src `
    --collect-submodules futures_intel `
    --add-data "$Resources;futures_intel/resources" `
    $Entry
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Output = Join-Path $Root ("dist\" + $Name + ".exe")
if (-not (Test-Path -LiteralPath $Output)) {
    throw "Build finished but output was not found: $Output"
}
Write-Output "Built: $Output"
