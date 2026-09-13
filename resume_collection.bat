@echo off
title Artale Market Collector - Resume Collection
cd /d "%~dp0"

set START_INDEX=%1
if "%START_INDEX%"=="" set START_INDEX=42

set TARGET_TAB=%2
if "%TARGET_TAB%"=="" set TARGET_TAB=asks

echo =======================================================
echo    Artale Market Tracker - Resume Collection
echo    Starting from Item #%START_INDEX% (Mode: %TARGET_TAB%)
echo =======================================================
echo.
powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab %TARGET_TAB% -StartIndex %START_INDEX%
echo.
echo =======================================================
echo    Collection completed. Press any key to exit.
echo =======================================================
pause
