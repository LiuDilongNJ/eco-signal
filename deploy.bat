@echo off
setlocal

REM Windows CMD compatibility entrypoint. PowerShell contains the deployment logic.
set "ARGS="
:parse
if "%~1"=="" goto run
if /I "%~1"=="--pull" (
  set "ARGS=%ARGS% -Pull"
  goto next
)
if /I "%~1"=="--geo-db" (
  set "ARGS=%ARGS% -GeoDb"
  goto next
)
if /I "%~1"=="--dry-run" (
  set "ARGS=%ARGS% -DryRun"
  goto next
)
if /I "%~1"=="--force-unlock" (
  set "ARGS=%ARGS% -ForceUnlock"
  goto next
)
echo Unknown option: %~1 1>&2
exit /b 2

:next
shift
goto parse

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" %ARGS%
exit /b %ERRORLEVEL%
