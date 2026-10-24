@echo off
setlocal
set "PYTHONUTF8=1"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Installation failed with exit code %RC%.
)

if "%~1"=="" (
    echo.
    pause
)

exit /b %RC%
