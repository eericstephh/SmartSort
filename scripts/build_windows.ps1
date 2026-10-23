<#
.SYNOPSIS
    Builds the portable Windows bundle with PyInstaller.

.DESCRIPTION
    Produces dist\SmartSort containing:
      SmartSort.exe         the desktop application
      smartsort-host.exe    the browser native messaging host
      browser_extension\    the unpacked Chrome/Edge extension
      docs\                 documentation

    The build is not code signed. Windows SmartScreen will warn the first time
    an unsigned executable runs; see docs\installation.md.

.PARAMETER Clean
    Delete dist\ and build\ before building.

.EXAMPLE
    .\scripts\build_windows.ps1 -Clean
#>
[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "    $message" -ForegroundColor Green }

if (-not (Test-Path $venvPython)) {
    throw "No virtual environment found. Run scripts\install_windows.ps1 first."
}

Push-Location $root
try {
    Write-Step "Ensuring PyInstaller is available"
    & $venvPython -m pip install --quiet --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller." }

    if ($Clean) {
        Write-Step "Cleaning previous output"
        foreach ($folder in @("build", "dist")) {
            $path = Join-Path $root $folder
            if (Test-Path $path) { Remove-Item -LiteralPath $path -Recurse -Force }
        }
    }

    Write-Step "Generating icons"
    & $venvPython (Join-Path $root "scripts\generate_icons.py")

    Write-Step "Running PyInstaller"
    & $venvPython -m PyInstaller --noconfirm --clean (Join-Path $root "smartsort.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    $dist = Join-Path $root "dist\SmartSort"
    $gui = Join-Path $dist "SmartSort.exe"
    $host = Join-Path $dist "smartsort-host.exe"
    $extension = Join-Path $dist "browser_extension"

    Write-Step "Verifying the bundle"
    if (-not (Test-Path $gui)) { throw "SmartSort.exe is missing from the build." }
    if (-not (Test-Path $host)) { throw "smartsort-host.exe is missing from the build." }

    # PyInstaller puts bundled data under _internal\. The extension folder and the
    # documentation are also copied next to the executable, because that is where
    # a user looks for them and where "Open extension folder" points.
    foreach ($item in @("browser_extension", "docs")) {
        $target = Join-Path $dist $item
        if (-not (Test-Path $target)) {
            Copy-Item -Path (Join-Path $root $item) -Destination $target -Recurse
            Write-Host "    copied $item next to the executable" -ForegroundColor Yellow
        }
    }
    foreach ($file in @("README.md", "LICENSE", "CHANGELOG.md")) {
        $target = Join-Path $dist $file
        if (-not (Test-Path $target)) {
            Copy-Item -Path (Join-Path $root $file) -Destination $target
        }
    }

    $guiSize = [math]::Round((Get-Item $gui).Length / 1MB, 1)
    $hostSize = [math]::Round((Get-Item $host).Length / 1MB, 1)
    Write-Ok "SmartSort.exe ($guiSize MB)"
    Write-Ok "smartsort-host.exe ($hostSize MB)"
    Write-Ok "browser_extension\"
    Write-Ok "Total: $([math]::Round((Get-ChildItem $dist -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)) MB"

    Write-Step "Smoke test (version flag)"
    & $gui --version
    if ($LASTEXITCODE -ne 0) { throw "The packaged executable failed to start." }
    & $host --version
    if ($LASTEXITCODE -ne 0) { throw "The packaged native host failed to start." }

    Write-Host ""
    Write-Host "Build complete: $dist" -ForegroundColor Green
    Write-Host ""
    Write-Host "Run it:" -ForegroundColor White
    Write-Host "  $gui"
    Write-Host ""
    Write-Host "Register the browser integration from the packaged build:" -ForegroundColor White
    Write-Host "  .\scripts\register_native_host.ps1 -ExtensionId <ID>"
    Write-Host ""
}
finally {
    Pop-Location
}
