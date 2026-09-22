@echo off
setlocal

set TARGET_FILE=C:\Users\gary1\artale_market_tracker\data\launch_target.txt
cd /d "C:\LDPlayer\LDPlayer9"

set TARGET=all
if exist "%TARGET_FILE%" (
    set /p TARGET=<"%TARGET_FILE%"
)

if "%TARGET%"=="all" goto :launch_all
if "%TARGET%"=="quit_all" goto :quit_all
if "%TARGET:~0,5%"=="quit_" goto :quit_single

:launch_single
call :sanitize_com
start "" "C:\LDPlayer\LDPlayer9\ldconsole.exe" launch --index %TARGET%
goto :done

:launch_all
call :sanitize_com
start "" "C:\LDPlayer\LDPlayer9\ldconsole.exe" launch --index 3
ping 127.0.0.1 -n 4 >nul
start "" "C:\LDPlayer\LDPlayer9\ldconsole.exe" launch --index 4
ping 127.0.0.1 -n 4 >nul
start "" "C:\LDPlayer\LDPlayer9\ldconsole.exe" launch --index 7
goto :done

:quit_single
set QIDX=%TARGET:~5%
"C:\LDPlayer\LDPlayer9\ldconsole.exe" quit --index %QIDX%
goto :done

:quit_all
"C:\LDPlayer\LDPlayer9\ldconsole.exe" quitall
ping 127.0.0.1 -n 4 >nul
taskkill /f /im dnplayer.exe >nul 2>&1
taskkill /f /im Ld9BoxHeadless.exe >nul 2>&1
taskkill /f /im Ld9BoxSVC.exe >nul 2>&1
ping 127.0.0.1 -n 3 >nul
goto :done

:sanitize_com
tasklist /fi "imagename eq dnplayer.exe" 2>nul | find /i "dnplayer.exe" >nul
if "%ERRORLEVEL%"=="1" (
    tasklist /fi "imagename eq Ld9BoxSVC.exe" 2>nul | find /i "Ld9BoxSVC.exe" >nul
    if "%ERRORLEVEL%"=="0" (
        taskkill /f /im Ld9BoxSVC.exe >nul 2>&1
        ping 127.0.0.1 -n 3 >nul
    )
)
exit /b 0

:done
exit /b 0
