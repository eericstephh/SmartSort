@echo off
rem ---------------------------------------------------------------------------
rem SmartSort native messaging host launcher (development builds only).
rem
rem Chrome/Edge start this file because the manifest "path" cannot contain
rem arguments. A packaged build registers smartsort-host.exe instead.
rem ---------------------------------------------------------------------------
setlocal
set "SMARTSORT_ROOT=%~dp0.."
set "PYTHONPATH=%SMARTSORT_ROOT%"
if exist "%SMARTSORT_ROOT%\.venv\Scripts\python.exe" (
  "%SMARTSORT_ROOT%\.venv\Scripts\python.exe" -m smartsort.app.browser.native_host %*
) else (
  python -m smartsort.app.browser.native_host %*
)
exit /b %ERRORLEVEL%
