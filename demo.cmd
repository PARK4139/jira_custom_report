@echo off
setlocal
pushd "%~dp0"
rem Demo: the same dashboard with built-in dummy data. No Jira connection, user ID, or password is needed.
rem Prefer the bundled uv (tools\uv.exe); otherwise use uv from PATH.
set "UV=%~dp0tools\uv.exe"
if not exist "%UV%" set "UV=uv"
"%UV%" --version >nul 2>nul
if errorlevel 1 (
    echo uv is required: place uv.exe in tools\ or install it from https://docs.astral.sh/uv/ 1>&2
    popd
    exit /b 1
)
"%UV%" run --locked jira-demo %*
set "DEMO_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %DEMO_EXIT_CODE%
