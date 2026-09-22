@echo off
cd /d "%~dp0"

set START_INDEX=%1
if "%START_INDEX%"=="" set START_INDEX=42

set TARGET_TAB=%2
if "%TARGET_TAB%"=="" set TARGET_TAB=asks

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab %TARGET_TAB% -StartIndex %START_INDEX%
if %ERRORLEVEL% neq 0 (
    pause
)
