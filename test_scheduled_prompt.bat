@echo off
cd /d "%~dp0"
echo [Artale Market Tracker] Testing prompt dialog...
powershell.exe -ExecutionPolicy Bypass -File "%~dp0schedule_prompt_daemon.ps1" -TestNow
