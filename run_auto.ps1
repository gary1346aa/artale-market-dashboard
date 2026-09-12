$ErrorActionPreference = "Continue"
Set-Location "C:\Users\gary1\artale_market_tracker"
$python = "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"
$logFile = "C:\Users\gary1\new_item_run.log"

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Running test_new_item..." | Out-File $logFile -Encoding utf8
& $python test_new_item.py *>> $logFile
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Finished with exit code $LASTEXITCODE." | Out-File $logFile -Append -Encoding utf8
