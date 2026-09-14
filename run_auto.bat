@echo off
chcp 65001 >nul
cd /d "C:\Users\gary1\artale_market_tracker"
if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\gary1\artale_market_tracker\run_auto.ps1" -TargetTab both -Due
    pause
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\gary1\artale_market_tracker\run_auto.ps1" %*
)
