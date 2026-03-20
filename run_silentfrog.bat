@echo off
REM Launch Silentfrog via Poetry from the repo root.
REM Usage: double-click this file (Windows) or run it from a terminal.

pushd %~dp0
poetry run python -m silentfrog.gui
echo.
echo Silentfrog exited. Press any key to close this window.
pause >nul
popd
