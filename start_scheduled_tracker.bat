@echo off
cd /d "%~dp0"
echo [Artale Market Tracker] Starting background scheduler (Hourly, Parallel ADB Mode)...
start "" powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0schedule_prompt_daemon.ps1"
echo Scheduler daemon is now running silently in the background (Hourly schedule).
echo Check logs at: %~dp0scheduler_daemon.log
ping 127.0.0.1 -n 3 >nul
