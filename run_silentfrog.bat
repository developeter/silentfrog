@echo off
REM Launch Silentfrog from the local .venv when available.
REM Falls back to Poetry for developers.

setlocal
pushd %~dp0
set "QT_API=pyside6"
set "LAUNCHER=%~dp0.venv\Scripts\silentfrog.exe"
if exist "%LAUNCHER%" (
  REM Windowed gui-script exe: launch detached so this
  REM console does not linger for the whole session.
  start "" "%LAUNCHER%" %*
  popd
  exit /b 0
)
REM Developer fallback: keep the console open so errors
REM from the poetry-run session stay visible.
poetry run silentfrog %*
echo.
echo Silentfrog exited. Press any key to close this window.
pause >nul
popd
