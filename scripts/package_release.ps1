param(
    [string]$Version = "dev"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Exe = Join-Path $Root "dist\FuturesIntelTool.exe"
$ReleaseDir = Join-Path $Root "dist\release"
$PackageDir = Join-Path $ReleaseDir "FuturesIntelTool-$Version"

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Executable not found: $Exe. Run scripts\build_desktop.ps1 first."
}

$ResolvedReleaseDir = [System.IO.Path]::GetFullPath($ReleaseDir)
$ResolvedPackageDir = [System.IO.Path]::GetFullPath($PackageDir)
if (-not $ResolvedPackageDir.StartsWith($ResolvedReleaseDir + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "Refusing to clean package directory outside dist\release: $ResolvedPackageDir"
}
if (Test-Path -LiteralPath $PackageDir) {
    Remove-Item -LiteralPath $PackageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
Copy-Item -LiteralPath $Exe -Destination (Join-Path $PackageDir "FuturesIntelTool.exe")
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination $PackageDir
Copy-Item -LiteralPath (Join-Path $Root "OPENCLAW.md") -Destination $PackageDir

$Zip = Join-Path $ReleaseDir "FuturesIntelTool-$Version-windows-x64.zip"
if (Test-Path -LiteralPath $Zip) {
    Remove-Item -LiteralPath $Zip -Force
}
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $Zip -CompressionLevel Optimal
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Zip).Hash
"$Hash  $(Split-Path -Leaf $Zip)" | Set-Content -LiteralPath (Join-Path $ReleaseDir "SHA256SUMS.txt") -Encoding ascii
Write-Output "Release package: $Zip"
Write-Output "SHA256: $Hash"
