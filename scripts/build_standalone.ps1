# Local helper: build a Windows standalone binary with PyInstaller.
# CI uses the same approach. Not required for source installs.
#
# Usage:
# powershell -ExecutionPolicy Bypass -File .\scripts\build_standalone.ps1
#
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing PyInstaller (build-time only)..."
python -m pip install --upgrade pyinstaller

Write-Host "Building mira.exe ..."
python -m PyInstaller `
 --onefile `
 --name mira `
 --paths src `
 --hidden-import mira `
 --hidden-import mira.cli `
 --console `
 src\mira\__main__.py

$out = Join-Path $Root "dist\mira.exe"
if (Test-Path $out) {
 Write-Host "Binary: $out"
} else {
 Write-Error "Build finished but dist\mira.exe was not found."
}
