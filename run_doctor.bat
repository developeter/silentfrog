@echo off
REM Run Silentfrog doctor checks from repo root.

pushd %~dp0
poetry run python tools/doctor.py %*
echo.
echo Doctor finished. Press any key to close this window.
pause >nul
popd
