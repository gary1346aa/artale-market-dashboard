@echo off
title Artale Market Collector - Live Monitor
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Manual Collection Run
echo =======================================================
echo.
echo Select collection mode:
echo   [1] Full Update (Both: Asks + Trades) (~5-6 mins) [Default]
echo   [2] Fast Update (Trades Only)         (~2.5 mins)
echo.
set /p mode="Enter choice [1 or 2, default=1]: "

if "%mode%"=="2" (
    echo [Artale Tracker] Starting Fast Update (Trades Only)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab trades
) else (
    echo [Artale Tracker] Starting Full Update (Both: Asks + Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both
)

echo.
echo =======================================================
echo    Collection run completed. Press any key to exit.
echo =======================================================
pause
