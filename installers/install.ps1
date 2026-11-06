# Mira installer for Windows (PowerShell)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\installers\install.ps1
#   powershell -ExecutionPolicy Bypass -File .\installers\install.ps1 -FromRelease
#   powershell -ExecutionPolicy Bypass -File .\installers\install.ps1 -Yes
#
param(
    [switch]$FromRelease,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Repo = "soroush-zendedel/Mira"
$MinMajor = 3
$MinMinor = 10

if ($env:MIRA_INSTALL_NONINTERACTIVE -eq "1") { $Yes = $true }

Write-Host "Mira installer (Windows)"
Write-Host "------------------------"

$InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\Mira"
$BinDir = Join-Path $InstallRoot "bin"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

function Test-UserPathContains([string]$Dir) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { return $false }
    $parts = $userPath -split ';' | ForEach-Object { $_.TrimEnd('\') }
    $target = $Dir.TrimEnd('\')
    return ($parts -contains $target)
}

function Ask-YesNo([string]$Prompt, [bool]$DefaultYes = $true) {
    if ($Yes) { return $true }
    if (-not [Environment]::UserInteractive) { return $false }
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $reply = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($reply)) { return $DefaultYes }
    return ($reply -match '^[Yy]')
}

function Configure-Path {
    if (Test-UserPathContains $BinDir) {
        Write-Host "User PATH already includes $BinDir — nothing to do."
        return
    }
    Write-Host ""
    Write-Host "Launcher directory: $BinDir"
    Write-Host "This directory is not on your user PATH."
    Write-Host ""
    if (-not (Ask-YesNo "Add this directory to your user PATH?" $true)) {
        Write-Host "Skipped. You can run Mira via full path under $BinDir"
        Write-Host "Or add $BinDir to PATH later from System Properties."
        return
    }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    [Environment]::SetEnvironmentVariable("Path", "$BinDir;$userPath", "User")
    $env:Path = "$BinDir;$env:Path"
    Write-Host "Added to user PATH: $BinDir"
    Write-Host "Open a NEW terminal so other apps see the updated PATH."
}

function Install-FromRelease {
    Write-Host "Downloading standalone EXE from latest GitHub Release..."
    $url = "https://github.com/$Repo/releases/latest/download/mira-windows-x86_64.exe"
    $dest = Join-Path $BinDir "mira.exe"
    try {
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    } catch {
        Write-Host "Release download failed: $_"
        return $false
    }
    if (-not (Test-Path $dest)) { return $false }
    $cmd = Join-Path $BinDir "mira.cmd"
    @"
@echo off
\"$dest\" %*
"@ | Set-Content -Path $cmd -Encoding ASCII
    Write-Host "Installed standalone: $dest"
    try { & $dest --version } catch {}
    return $true
}

function Find-Python {
    foreach ($c in @("python", "python3", "py")) {
        try {
            $p = Get-Command $c -ErrorAction SilentlyContinue
            if ($p) {
                $verOut = & $c -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
                if ($LASTEXITCODE -eq 0 -and $verOut) { return $c }
            }
        } catch {}
    }
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )
    foreach ($path in $paths) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Install-FromSource([string]$RepoRoot) {
    $Python = Find-Python
    if (-not $Python) {
        Write-Error "Python $MinMajor.$MinMinor+ required. Install from https://www.python.org/downloads/"
    }
    $major = [int](& $Python -c "import sys; print(sys.version_info.major)")
    $minor = [int](& $Python -c "import sys; print(sys.version_info.minor)")
    if ($major -lt $MinMajor -or ($major -eq $MinMajor -and $minor -lt $MinMinor)) {
        Write-Error "Python $MinMajor.$MinMinor+ required."
    }
    Write-Host "Using Python $major.$minor ($Python)"
    $verFile = Join-Path $RepoRoot "VERSION"
    if (Test-Path $verFile) {
        Write-Host "Package version: $((Get-Content $verFile -Raw).Trim())"
    }
    Write-Host "Installing from source: $RepoRoot"
    $destSrc = Join-Path $InstallRoot "src"
    if (Test-Path $destSrc) { Remove-Item -Recurse -Force $destSrc }
    New-Item -ItemType Directory -Force -Path $destSrc | Out-Null
    Copy-Item -Recurse (Join-Path $RepoRoot "src\mira") (Join-Path $destSrc "mira")
    if (Test-Path $verFile) {
        Copy-Item $verFile (Join-Path $InstallRoot "VERSION") -Force
    }
    $Launcher = Join-Path $BinDir "mira.cmd"
    @"
@echo off
set PYTHONPATH=$InstallRoot\src;%PYTHONPATH%
$Python -m mira %*
"@ | Set-Content -Path $Launcher -Encoding ASCII
    Write-Host "Installed source layout to $InstallRoot"
    try { & $Launcher --version } catch {}
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

if ($FromRelease) {
    if (-not (Install-FromRelease)) {
        if (Test-Path (Join-Path $RepoRoot "src\mira")) {
            Write-Host "Falling back to local source..."
            Install-FromSource $RepoRoot
        } else {
            Write-Error "Could not download release and no local source found."
        }
    }
} elseif (Test-Path (Join-Path $RepoRoot "src\mira")) {
    Install-FromSource $RepoRoot
} else {
    if (-not (Install-FromRelease)) {
        Write-Host ""
        Write-Host "Clone the repo or download the ZIP, then run this script from the extracted folder:"
        Write-Host "  git clone https://github.com/$Repo.git"
        Write-Host "  cd Mira"
        Write-Host "  powershell -ExecutionPolicy Bypass -File .\installers\install.ps1"
        Write-Error "No local source and release binary unavailable."
    }
}

Configure-Path

Write-Host ""
Write-Host "Done. Open a new terminal if PATH was updated, then run:"
Write-Host "  mira --version"
Write-Host "  mira update"
