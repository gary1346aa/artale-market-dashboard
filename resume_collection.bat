@echo off
title Artale Market Collector - Resuming from Item #54
cd /d "%~dp0"
echo =======================================================
echo    Artale Market Tracker - Resume Collection
echo    Starting from Item #54 (Mode: Both)
echo =======================================================
echo.
powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both -StartIndex 54
echo.
echo =======================================================
echo    Collection completed. Press any key to exit.
echo =======================================================
pause
