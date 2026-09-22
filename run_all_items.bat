@echo off
title Artale Market Collector - Full Watchlist Scan (Both Mode)
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Full Watchlist Scan
echo    Mode: Both (Asks + Trades) ^| Target: All Tracked Items
echo    Engine: Parallel ADB
echo =======================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both
echo.
echo =======================================================
echo    Full collection completed. Press any key to exit.
echo =======================================================
pause
