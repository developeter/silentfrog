@echo off
REM Launch Silentfrog from the local .venv when available.
REM Falls back to Poetry for developers.

pushd %~dp0
set "QT_API=pyside6"
set "LAUNCHER=%~dp0.venv\Scripts\silentfrog.exe"
if exist "%LAUNCHER%" (
  call "%LAUNCHER%" %*
) else (
  poetry run silentfrog %*
)
echo.
echo Silentfrog exited. Press any key to close this window.
pause >nul
popd
