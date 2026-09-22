@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_auto.ps1" -TargetTab both -Due
if %ERRORLEVEL% neq 0 (
    pause
)
