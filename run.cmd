@echo off
setlocal
pushd "%~dp0"
rem Prefer the bundled uv (tools\uv.exe); otherwise use uv from PATH.
set "UV=%~dp0tools\uv.exe"
if not exist "%UV%" set "UV=uv"
"%UV%" --version >nul 2>nul
if errorlevel 1 (
    echo uv is required: place uv.exe in tools\ or install it from https://docs.astral.sh/uv/ 1>&2
    popd
    exit /b 1
)
"%UV%" run --locked jira-report %*
set "REPORT_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %REPORT_EXIT_CODE%
