@echo off
cd /d "%~dp0"
echo [Artale Market Tracker] Starting background scheduler (12:00 PM / 12:00 AM)...
start "" powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0schedule_prompt_daemon.ps1"
echo Scheduler is now running in the background.
timeout /t 3 >nul
