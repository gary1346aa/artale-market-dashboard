@echo off
title Artale Market Collector - Live Monitor
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Manual Collection Run
echo =======================================================
echo.
for /f %%a in ('powershell -Command "(@((Get-Content items_watchlist.json -Raw | ConvertFrom-Json).PSObject.Properties)).Count"') do set ITEM_COUNT=%%a
if "%ITEM_COUNT%"=="" set ITEM_COUNT=105

echo Target Watchlist: %ITEM_COUNT% items
echo.
echo Select collection mode (Runs in 100% Background Parallel ADB):
echo   [C] Both (Ask + Trade) [Default - Parallel All Emulators]
echo   [D] Due Items Only (Fastest - Scans only items due for update)
echo   [A] Ask Only (Active Listings)
echo   [B] Trade Only (Matched Trades)
echo   [R] Resume from Item #54 (Both)
echo   [Q] Quit
echo.
set /p mode="Enter choice [C, D, A, B, R, or Q, default=C]: "

if /i "%mode%"=="Q" (
    echo [Artale Tracker] Operation cancelled by user.
    exit /b
)
if /i "%mode%"=="D" (
    echo [Artale Tracker] Starting Due-Only Parallel Collection (Both: Asks + Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both -Due
) else if /i "%mode%"=="R" (
    echo [Artale Tracker] Resuming Full Collection from Item #54 (Both: Asks + Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both -StartIndex 54
) else if /i "%mode%"=="A" (
    echo [Artale Tracker] Starting Ask Only Collection (Active Listings)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab asks
) else if /i "%mode%"=="B" (
    echo [Artale Tracker] Starting Trade Only Collection (Matched Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab trades
) else (
    echo [Artale Tracker] Starting Full Parallel Collection (Both: Asks + Trades)...
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both
)

echo.
echo =======================================================
echo    Collection run completed. Press any key to exit.
echo =======================================================
pause
