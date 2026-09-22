@echo off
title Artale Market Collector - Live Monitor
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Due Collection Run
echo    Mode: Both (Asks + Trades) ^| Target: Due Items Only
echo    Engine: Parallel ADB
echo =======================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both -Due
echo.
echo =======================================================
echo    Collection run completed. Press any key to exit.
echo =======================================================
pause
