@echo off
title Test Artale Market Prompt
cd /d "C:\Users\gary1\artale_market_tracker"
echo 正在觸發測試詢問視窗...
powershell -ExecutionPolicy Bypass -File "C:\Users\gary1\artale_market_tracker\schedule_prompt_daemon.ps1" -TestNow
