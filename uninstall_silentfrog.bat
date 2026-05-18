@echo off
setlocal
pushd %~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m tools.source_uninstall %*
) else (
  python -m tools.source_uninstall %*
)
popd
