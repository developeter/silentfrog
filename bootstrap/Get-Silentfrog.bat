@echo off
REM Double-click wrapper that runs Get-Silentfrog.ps1 with execution
REM policy bypassed for the current process only. This avoids asking
REM the user to flip the system-wide PowerShell policy.

setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%Get-Silentfrog.ps1"
exit /b %ERRORLEVEL%
