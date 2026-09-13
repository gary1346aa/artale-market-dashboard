@echo off
title Artale Market Collector - Live Monitor
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Manual Collection Run
echo =======================================================
echo.
echo Target Watchlist: 84 items
echo.
echo Select collection mode:
echo   [A] Ask Only (Active Listings)   [ETA: ~10-12 mins]
echo   [B] Trade Only (Matched Trades)  [ETA: ~10-12 mins]
echo   [C] Both (Ask + Trade)           [ETA: ~20-25 mins] [Default]
echo   [D] Cancel
echo.
set /p mode="Enter choice [A, B, C, or D, default=C]: "

if /i "%mode%"=="D" (
    echo [Artale Tracker] Operation cancelled by user.
    exit /b
)
if /i "%mode%"=="A" (
    echo [Artale Tracker] Starting Ask Only Collection (Active Listings)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab asks
) else if /i "%mode%"=="B" (
    echo [Artale Tracker] Starting Trade Only Collection (Matched Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab trades
) else (
    echo [Artale Tracker] Starting Full Collection (Both: Asks + Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both
)

echo.
echo =======================================================
echo    Collection run completed. Press any key to exit.
echo =======================================================
pause
