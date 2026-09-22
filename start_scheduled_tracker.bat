@echo off
cd /d "%~dp0"
echo [Artale Market Tracker] Starting background scheduler (Run immediately, then hourly)...
start "" powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0schedule_prompt_daemon.ps1"
echo Scheduler daemon is running in background.
echo Initial scan starting immediately, followed by hourly scans (:00).
echo Check logs at: %~dp0scheduler_daemon.log
ping 127.0.0.1 -n 3 >nul
