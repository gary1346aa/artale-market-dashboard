param (
    [string]$Query = "墜飾幸運卷軸30%",
    [int]$Pages = 2
)

$ErrorActionPreference = "Continue"
Set-Location "C:\Users\gary1\artale_market_tracker"
$python = "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"
$logFile = "C:\Users\gary1\collector_run.log"

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Starting collection for $Query..." | Out-File $logFile -Encoding utf8

& $python run_collector.py --mode auto --query $Query --pages $Pages *>> $logFile

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Finished with exit code $LASTEXITCODE." | Out-File $logFile -Append -Encoding utf8
