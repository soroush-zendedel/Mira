# Bump version (SemVer), sync all version fields, print git tag commands.
#
# Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -File .\scripts\make_release_tag.ps1 1.0.1
#   .\scripts\make_release_tag.ps1 1.0.0
#
# Rules (SemVer):
#   MAJOR.MINOR.PATCH
#   - PATCH: bugfixes only
#   - MINOR: new features, backward compatible
#   - MAJOR: breaking changes

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Version
)

$ErrorActionPreference = "Stop"

if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$') {
    Write-Error "Invalid SemVer: $Version (expected e.g. 1.0.0 or 1.0.0-rc.1)"
}

$Tag = "v$Version"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Single source of truth
Set-Content -Path (Join-Path $Root "VERSION") -Value $Version -NoNewline
Add-Content -Path (Join-Path $Root "VERSION") -Value ""

# Sync package metadata
$init = @"
"""Mira - Universal Software Repository Mirror Manager."""

__version__ = "$Version"
__author__ = "Soroush Zendedel"
"@
Set-Content -Path (Join-Path $Root "src\mira\__init__.py") -Value $init -Encoding UTF8

$constPath = Join-Path $Root "src\mira\constants.py"
$const = Get-Content $constPath -Raw
$const = [regex]::Replace($const, 'APP_VERSION = "[^"]*"', "APP_VERSION = `"$Version`"")
Set-Content -Path $constPath -Value $const -Encoding UTF8 -NoNewline

$pyprojectPath = Join-Path $Root "pyproject.toml"
$py = Get-Content $pyprojectPath -Raw
$py = [regex]::Replace($py, '(?m)^version = "[^"]*"', "version = `"$Version`"")
Set-Content -Path $pyprojectPath -Value $py -Encoding UTF8 -NoNewline

Write-Host "Synced package metadata to $Version"
Write-Host ""
Write-Host "Version set to $Version"
Write-Host "Next steps:"
Write-Host "  git add -A"
Write-Host "  git commit -m `"Release $Tag`""
Write-Host "  git tag -a $Tag -m `"Mira $Tag`""
Write-Host "  git push origin main"
Write-Host "  git push origin $Tag"
Write-Host ""
Write-Host "GitHub Actions will build binaries, .deb and attach them to the Release."
