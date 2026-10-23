<#
.SYNOPSIS
    Uninstalls SmartSort.

.DESCRIPTION
    Removes only what SmartSort created:
      * the native messaging registry entries and manifest,
      * the optional "start with Windows" entry,
      * optionally the application data folder (history, settings, logs),
      * optionally the local virtual environment and build output.

    Your organized files are never touched.

.PARAMETER PurgeData
    Also delete %LOCALAPPDATA%\SmartSort (settings, history, logs). Asks for
    confirmation because the operation history cannot be recovered afterwards.

.PARAMETER RemoveBuild
    Also delete the local .venv and dist folders.

.EXAMPLE
    .\scripts\uninstall_windows.ps1

.EXAMPLE
    .\scripts\uninstall_windows.ps1 -PurgeData
#>
[CmdletBinding()]
param(
    [switch]$PurgeData,
    [switch]$RemoveBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "    $message" -ForegroundColor Green }

Write-Host ""
Write-Host "SmartSort uninstaller" -ForegroundColor White
Write-Host ""

Write-Step "Removing the native messaging host"
$registerScript = Join-Path $PSScriptRoot "register_native_host.ps1"
if (Test-Path $registerScript) {
    try {
        & $registerScript -Unregister
    } catch {
        Write-Host "    $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    $packaged = Join-Path $root "dist\SmartSort\SmartSort.exe"
    if (Test-Path $packaged) {
        $null = Start-Process -FilePath $packaged -ArgumentList @("--unregister-host") `
            -Wait -PassThru -NoNewWindow
    }
}

Write-Step "Removing the 'start with Windows' entry"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
try {
    if (Get-ItemProperty -Path $runKey -Name "SmartSort" -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $runKey -Name "SmartSort" -ErrorAction Stop
        Write-Ok "Removed HKCU Run entry"
    } else {
        Write-Ok "No Run entry present"
    }
} catch {
    Write-Host "    Could not remove the Run entry: $($_.Exception.Message)" -ForegroundColor Yellow
}

$dataDir = Join-Path $env:LOCALAPPDATA "SmartSort"
if ($PurgeData) {
    if (Test-Path $dataDir) {
        Write-Host ""
        Write-Host "This will permanently delete:" -ForegroundColor Yellow
        Write-Host "  $dataDir" -ForegroundColor Yellow
        Write-Host "including the operation history that Undo relies on." -ForegroundColor Yellow
        $answer = Read-Host "Type DELETE to continue"
        if ($answer -eq "DELETE") {
            Remove-Item -LiteralPath $dataDir -Recurse -Force
            Write-Ok "Application data removed"
        } else {
            Write-Ok "Kept application data"
        }
    } else {
        Write-Ok "No application data found"
    }
} else {
    Write-Ok "Application data kept at $dataDir"
}

if ($RemoveBuild) {
    foreach ($folder in @(".venv", "dist", "build")) {
        $path = Join-Path $root $folder
        if (Test-Path $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
            Write-Ok "Removed $folder"
        }
    }
}

Write-Host ""
Write-Host "Uninstall complete. Organized files were not modified." -ForegroundColor Green
Write-Host "Remove the extension manually from chrome://extensions if you added it." -ForegroundColor DarkGray
Write-Host ""
