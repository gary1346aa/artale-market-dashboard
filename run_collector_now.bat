@echo off
title Artale Market Collector - Live Monitor
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Manual Collection Run
echo =======================================================
echo.
powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1"
echo.
echo =======================================================
echo    Collection run completed. Press any key to exit.
echo =======================================================
pause
