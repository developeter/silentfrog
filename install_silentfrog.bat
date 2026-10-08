@echo off
setlocal
pushd %~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 install_silentfrog.py %*
) else (
  python install_silentfrog.py %*
)
set "SF_RC=%errorlevel%"
echo.
if "%SF_RC%"=="0" (
  echo Silentfrog install finished. You can close this window and start Silentfrog from the Desktop shortcut.
) else (
  echo Silentfrog install FAILED ^(exit code %SF_RC%^). Scroll up for the [install] error above.
)
if not defined SILENTFROG_NO_PAUSE if not defined CI pause
popd
exit /b %SF_RC%
