# Debian packages can only be built on Linux (or WSL / Linux CI).
# On Windows this script explains the options.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_deb.ps1 1.0.0
#
param(
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$Version = ""
)

Write-Host "build_deb is a Linux-only packaging step (needs dpkg-deb)."
Write-Host ""
Write-Host "Options on Windows:"
Write-Host "  1) Rely on GitHub Actions (recommended):"
Write-Host "       git tag -a v1.0.0 -m `"Mira v1.0.0`""
Write-Host "       git push origin v1.0.0"
Write-Host "     The Release workflow builds the .deb on ubuntu-latest."
Write-Host ""
Write-Host "  2) Use WSL if you have it:"
if ($Version) {
    Write-Host "       wsl bash scripts/build_deb.sh $Version"
} else {
    Write-Host "       wsl bash scripts/build_deb.sh 1.0.0"
}
Write-Host ""
Write-Host "  3) Build only the Windows EXE locally:"
Write-Host "       powershell -ExecutionPolicy Bypass -File .\scripts\build_standalone.ps1"
exit 0
