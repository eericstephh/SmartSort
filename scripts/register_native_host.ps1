<#
.SYNOPSIS
    Registers (or removes) the SmartSort native messaging host for Chrome and Edge.

.DESCRIPTION
    Writes the native messaging manifest and the per-user registry entries that
    Chrome/Edge need in order to launch SmartSort when the extension asks for
    it. Only HKCU entries owned by SmartSort are touched; no administrator
    rights are required.

    The extension ID is required. Load the extension first (chrome://extensions,
    Developer mode, "Load unpacked", pick the browser_extension folder), copy
    the ID shown on the card and pass it here.

.PARAMETER ExtensionId
    One or more Chrome/Edge extension IDs (32 characters, a-p).

.PARAMETER Unregister
    Remove the registration instead of creating it.

.EXAMPLE
    .\register_native_host.ps1 -ExtensionId abcdefghijklmnopabcdefghijklmnop

.EXAMPLE
    .\register_native_host.ps1 -ExtensionId abcdefghijklmnopabcdefghijklmnop,ponmlkjihgfedcbaponmlkjihgfedcba

.EXAMPLE
    .\register_native_host.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string[]]$ExtensionId = @(),
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "    $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "    $message" -ForegroundColor Yellow }

function Resolve-SmartSortCommand {
    $packaged = Join-Path $root "dist\SmartSort\SmartSort.exe"
    if (Test-Path $packaged) {
        return @{ Exe = $packaged; Args = @() }
    }
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{ Exe = $venvPython; Args = @("-m", "smartsort.app.main") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Exe = $python.Source; Args = @("-m", "smartsort.app.main") }
    }
    throw "Could not find SmartSort.exe or a Python interpreter. Run install_windows.ps1 first."
}

$command = Resolve-SmartSortCommand

# A windowed executable does not update $LASTEXITCODE when started with '&',
# and Start-Process -NoNewWindow can fail on machines with duplicated
# environment variables. .NET Process gives us a real exit code plus captured
# output, which is what the user needs to see.
function Invoke-SmartSortCli {
    param([string[]]$CliArgs)

    $arguments = @($command.Args) + $CliArgs
    $quoted = ($arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }) -join ' '

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $command.Exe
    $startInfo.Arguments = $quoted
    $startInfo.WorkingDirectory = $root
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    if ($stdout) { Write-Host $stdout.TrimEnd() }
    if ($stderr) { Write-Host $stderr.TrimEnd() -ForegroundColor Yellow }
    return $process.ExitCode
}

if ($Unregister) {
    Write-Step "Removing native messaging host registration"
    $exit = Invoke-SmartSortCli @("--unregister-host")
    if ($exit -ne 0) {
        Write-Warn "Removal reported a problem (exit code $exit)."
        exit $exit
    }
    Write-Ok "Done. Restart Chrome/Edge."
    exit 0
}

if ($ExtensionId.Count -eq 0) {
    Write-Host "An extension ID is required." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. Open chrome://extensions (or edge://extensions)"
    Write-Host "2. Enable Developer mode"
    Write-Host "3. Click 'Load unpacked' and select:"
    Write-Host "   $(Join-Path $root 'browser_extension')"
    Write-Host "4. Copy the ID from the extension card and run:"
    Write-Host "   .\register_native_host.ps1 -ExtensionId <ID>"
    exit 1
}

foreach ($id in $ExtensionId) {
    if ($id -notmatch '^[a-p]{32}$') {
        throw "'$id' is not a valid extension ID (expected 32 characters between a and p)."
    }
}

$joined = ($ExtensionId -join ",")
Write-Step "Registering native messaging host for: $joined"

$exit = Invoke-SmartSortCli @("--register-host", $joined)
if ($exit -ne 0) {
    Write-Warn "Registration failed (exit code $exit)."
    exit $exit
}

Write-Ok "Manifest and registry entries written."
Write-Ok "Restart Chrome/Edge, then open the SmartSort extension popup."
Write-Host ""
Write-Host "Note: the SmartSort desktop app must be running for downloads to be organized." -ForegroundColor DarkGray
exit 0
