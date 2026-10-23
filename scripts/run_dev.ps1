$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "No virtual environment found. Run scripts\install_windows.ps1 first."
}

Push-Location $root
try {
    & $venvPython -m smartsort.app.main @args
}
finally {
    Pop-Location
}
