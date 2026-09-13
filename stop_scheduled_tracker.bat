@echo off
title Stop Artale Market Scheduler
echo 正在停止所有背景運行的 Artale 排程程式...
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*schedule_prompt_daemon.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host '已停止進程 ID: ' $_.ProcessId }"
echo 排程守護程式已停止。
pause
