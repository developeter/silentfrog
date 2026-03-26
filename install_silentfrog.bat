@echo off
setlocal
pushd %~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 install_silentfrog.py %*
) else (
  python install_silentfrog.py %*
)
popd
