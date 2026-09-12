@echo off
chcp 65001 >nul
cd /d "C:\Users\gary1\artale_market_tracker"
set "PYTHON_EXE=C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"

set "ITEM=%~1"
if "%ITEM%"=="" set "ITEM=墜飾幸運卷軸30%"

echo [%date% %time%] Starting collection for "%ITEM%"... > "C:\Users\gary1\collector_output.log"
"%PYTHON_EXE%" run_collector.py --mode auto --query "%ITEM%" --pages 2 >> "C:\Users\gary1\collector_output.log" 2>&1
echo [%date% %time%] Done with exit code %errorlevel% >> "C:\Users\gary1\collector_output.log"
