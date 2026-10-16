@echo off
setlocal
pushd "%~dp0"
rem Development dashboard with browser hot reload and Python source auto-restart.
rem Uses fictional demo data and does not connect to Jira.
set "UV=%~dp0tools\uv.exe"
if not exist "%UV%" set "UV=uv"
"%UV%" --version >nul 2>nul
if errorlevel 1 (
    echo uv is required: place uv.exe in tools\ or install it from https://docs.astral.sh/uv/ 1>&2
    popd
    exit /b 1
)
"%UV%" run --locked python cores\python\jira_dev.py %*
set "DEV_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %DEV_EXIT_CODE%
