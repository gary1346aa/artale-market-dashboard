@echo off
cd /d "%~dp0"
echo [Artale Market Tracker] Stopping scheduler process...
powershell.exe -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*schedule_prompt_daemon.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Terminated process ID:' $_.ProcessId }"
echo Scheduler stopped.
timeout /t 3 >nul
