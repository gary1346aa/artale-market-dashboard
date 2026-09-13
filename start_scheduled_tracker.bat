@echo off
title Artale Market Tracker Scheduler
cd /d "C:\Users\gary1\artale_market_tracker"

echo 正在啟動 Artale 市場行情定時提醒排程 (12:00 PM / 12:00 AM)...
start "" powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\Users\gary1\artale_market_tracker\schedule_prompt_daemon.ps1"
echo 排程守護程式已於背景啟動！
echo 到達中午 12:00 或午夜 12:00 時將自動跳出詢問視窗。
pause
