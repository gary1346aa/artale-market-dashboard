@echo off
cd /d "%~dp0"
powershell.exe -NoExit -ExecutionPolicy Bypass -Command "Get-Content -Path '%~dp0scheduler_daemon.log' -Tail 40 -Wait"
