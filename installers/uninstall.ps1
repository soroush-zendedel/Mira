# Uninstall Mira from Windows (user install + PATH cleanup)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\installers\uninstall.ps1
#   powershell -ExecutionPolicy Bypass -File .\installers\uninstall.ps1 -PurgeData
#   powershell -ExecutionPolicy Bypass -File .\installers\uninstall.ps1 -Yes
#
param(
    [switch]$PurgeData,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

Write-Host "Mira uninstaller (Windows)"
Write-Host "--------------------------"

$InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\Mira"
$BinDir = Join-Path $InstallRoot "bin"
$ConfigDir = Join-Path $env:APPDATA "Mira"
$DataDir = Join-Path $env:LOCALAPPDATA "Mira"

# Also remove common standalone copy locations
$ExtraCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Mira"),
    (Join-Path $env:USERPROFILE "bin\mira.exe"),
    (Join-Path $env:USERPROFILE ".local\bin\mira.exe"),
    (Join-Path $env:USERPROFILE ".local\bin\mira.cmd")
)

function Remove-FromUserPath([string]$Dir) {
    if (-not $Dir) { return }
    $target = $Dir.TrimEnd('\')
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { return }
    $parts = $userPath -split ';' | Where-Object {
        $_ -and ($_.TrimEnd('\') -ne $target)
    }
    $newPath = ($parts -join ';')
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    # Update current session
    $sessionParts = $env:Path -split ';' | Where-Object {
        $_ -and ($_.TrimEnd('\') -ne $target)
    }
    $env:Path = ($sessionParts -join ';')
    Write-Host "Removed from user PATH: $target"
}

if (-not $Yes) {
    $reply = Read-Host "Remove Mira application files from $InstallRoot ? [Y/n]"
    if ($reply -and $reply -notmatch '^[Yy]') {
        Write-Host "Aborted."
        exit 0
    }
}

# PATH first (BinDir)
Remove-FromUserPath $BinDir

# Remove install tree
if (Test-Path $InstallRoot) {
    Remove-Item -Recurse -Force $InstallRoot
    Write-Host "Removed: $InstallRoot"
} else {
    Write-Host "Install root not found: $InstallRoot"
}

# Stray launchers on PATH directories
Get-Command mira -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $p = $_.Source
        if ($p -and (Test-Path $p)) {
            # only remove if under user profile
            if ($p -like "$env:USERPROFILE*" -or $p -like "$env:LOCALAPPDATA*") {
                Remove-Item -Force $p -ErrorAction SilentlyContinue
                Write-Host "Removed launcher: $p"
            }
        }
    } catch {}
}

foreach ($c in $ExtraCandidates) {
    if (Test-Path $c) {
        Remove-Item -Force $c -ErrorAction SilentlyContinue
        Write-Host "Removed: $c"
    }
}

if ($PurgeData) {
    foreach ($d in @($ConfigDir, $DataDir)) {
        if (Test-Path $d) {
            Remove-Item -Recurse -Force $d
            Write-Host "Removed data: $d"
        }
    }
} else {
    Write-Host ""
    Write-Host "Config/data kept (if any):"
    Write-Host "  $ConfigDir"
    Write-Host "  $DataDir"
    Write-Host "To delete them too, re-run with -PurgeData"
}

Write-Host ""
Write-Host "Done. Open a new terminal so PATH changes fully apply."
