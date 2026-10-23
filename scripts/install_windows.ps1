<#
.SYNOPSIS
    Installs SmartSort from a source checkout (or from the portable build folder).

.DESCRIPTION
    Creates an isolated virtual environment, installs the pinned dependencies,
    generates the icon assets and optionally builds the portable Windows bundle
    with PyInstaller.

    No administrator rights are required and nothing outside the project folder
    and %LOCALAPPDATA%\SmartSort is modified.

.PARAMETER Python
    Path to a Python 3.10+ interpreter. Defaults to "python" on PATH.

.PARAMETER Build
    Also produce the portable build in dist\SmartSort.

.PARAMETER Launch
    Start SmartSort when the installation finishes.

.EXAMPLE
    .\scripts\install_windows.ps1

.EXAMPLE
    .\scripts\install_windows.ps1 -Build -Launch
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$Build,
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "    $message" -ForegroundColor Green }

Write-Host ""
Write-Host "SmartSort installer" -ForegroundColor White
Write-Host "Project: $root" -ForegroundColor DarkGray
Write-Host ""

Write-Step "Checking Python"
if (-not (Get-Command $Python -ErrorAction SilentlyContinue) -and -not (Test-Path $Python)) {
    throw "Python was not found. Install Python 3.10+ from https://www.python.org/downloads/windows/ and re-run."
}
$versionText = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
$version = [version]$versionText
if ($version -lt [version]"3.10") {
    throw "Python $versionText is too old. SmartSort needs Python 3.10 or newer."
}
Write-Ok "Python $versionText"

Write-Step "Creating the virtual environment"
if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
    Write-Ok "Created $venv"
} else {
    Write-Ok "Reusing $venv"
}

Write-Step "Installing dependencies"
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install --requirement (Join-Path $root "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
Write-Ok "Dependencies installed"

Write-Step "Generating icons"
& $venvPython (Join-Path $root "scripts\generate_icons.py")
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }

if ($Build) {
    Write-Step "Building the portable bundle"
    & (Join-Path $PSScriptRoot "build_windows.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Build failed." }
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "Start the app:" -ForegroundColor White
Write-Host "  .\scripts\run_dev.ps1"
Write-Host ""
Write-Host "Then enable the browser extension:" -ForegroundColor White
Write-Host "  1. Open chrome://extensions or edge://extensions and enable Developer mode"
Write-Host "  2. 'Load unpacked' -> $(Join-Path $root 'browser_extension')"
Write-Host "  3. Copy the extension ID and run:"
Write-Host "     .\scripts\register_native_host.ps1 -ExtensionId <ID>"
Write-Host ""

if ($Launch) {
    Write-Step "Starting SmartSort"
    Start-Process -FilePath $venvPython -ArgumentList @("-m", "smartsort.app.main") -WorkingDirectory $root
}
