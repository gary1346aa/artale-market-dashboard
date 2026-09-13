@echo off
title Artale Market Collector - Live Monitor
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Manual Collection Run
echo =======================================================
echo.
for /f %%a in ('powershell -Command "(Get-Content items_watchlist.json -Raw | ConvertFrom-Json).Count"') do set ITEM_COUNT=%%a
if "%ITEM_COUNT%"=="" set ITEM_COUNT=84

echo Target Watchlist: %ITEM_COUNT% items
echo.
echo Select collection mode:
echo   [A] Ask Only (Active Listings)
echo   [B] Trade Only (Matched Trades)
echo   [C] Both (Ask + Trade) [Default]
echo   [R] Resume from Item #54 (Both)
echo   [D] Cancel
echo.
set /p mode="Enter choice [A, B, C, R, or D, default=C]: "

if /i "%mode%"=="D" (
    echo [Artale Tracker] Operation cancelled by user.
    exit /b
)
if /i "%mode%"=="R" (
    echo [Artale Tracker] Resuming Full Collection from Item #54 (Both: Asks + Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both -StartIndex 54
) else if /i "%mode%"=="A" (
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
