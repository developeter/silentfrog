@echo off
setlocal EnableDelayedExpansion
pushd %~dp0
(
  where py >nul 2>nul
  if !errorlevel!==0 (
    py -3 -m tools.source_uninstall --keep-launcher uninstall_silentfrog.bat %*
  ) else (
    python -m tools.source_uninstall --keep-launcher uninstall_silentfrog.bat %*
  )
  set "SF_RC=!errorlevel!"
  echo.
  if "!SF_RC!"=="0" (
    echo Silentfrog uninstall finished. You can close this window.
  ) else (
    echo Silentfrog uninstall FAILED ^(exit code !SF_RC!^). Scroll up for the [uninstall] error above.
  )
  if not defined SILENTFROG_NO_PAUSE if not defined CI pause
  popd
  exit /b !SF_RC!
)
