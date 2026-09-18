@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo  Starting Artale Market K-Line Image API Server...
echo ========================================================
python run_api.py --port 8080
pause
