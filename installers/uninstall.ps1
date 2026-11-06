$InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\Mira"
$BinDir = Join-Path $InstallRoot "bin"
Write-Host "Removing $InstallRoot"
if (Test-Path $InstallRoot) { Remove-Item -Recurse -Force $InstallRoot }
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -and $userPath -like "*$BinDir*") {
    $parts = $userPath -split ';' | Where-Object { $_ -and $_ -ne $BinDir }
    [Environment]::SetEnvironmentVariable("Path", ($parts -join ';'), "User")
    Write-Host "Removed bin from user PATH."
}
Write-Host "Done. AppData config was kept."
Write-Host "To remove data: Remove-Item -Recurse `$env:APPDATA\Mira, `$env:LOCALAPPDATA\Mira -ErrorAction SilentlyContinue"
