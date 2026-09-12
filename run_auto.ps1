param (
    [string]$Watchlist = "items_watchlist.json",
    [string]$Query = "",
    [int]$Pages = 2
)

$ErrorActionPreference = "Continue"
Set-Location "C:\Users\gary1\artale_market_tracker"
$python = "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"
$logFile = "C:\Users\gary1\collector_run.log"

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Starting collection run for watchlist: $Watchlist..." | Out-File $logFile -Encoding utf8

if ($Query -ne "") {
    & $python run_collector.py --mode auto --query $Query --pages $Pages *>> $logFile
} else {
    & $python run_collector.py --mode auto --watchlist $Watchlist --pages $Pages *>> $logFile
}

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Finished with exit code $LASTEXITCODE." | Out-File $logFile -Append -Encoding utf8
