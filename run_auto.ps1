param (
    [string]$Watchlist = "items_watchlist.json",
    [string]$Query = "",
    [int]$Pages = 2,
    [string]$TargetTab = "trades",
    [string]$Instance = "槍手",
    [string]$Script = ""
)

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\gary1\artale_market_tracker"
$python = "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"
$logFile = "C:\Users\gary1\collector_run.log"

# Support dynamic config overrides when executed via Task Scheduler
if (Test-Path "run_config.json") {
    try {
        $cfg = Get-Content "run_config.json" -Raw -Encoding utf8 | ConvertFrom-Json
        if ($cfg.Watchlist) { $Watchlist = $cfg.Watchlist }
        if ($cfg.Query) { $Query = $cfg.Query }
        if ($null -ne $cfg.Pages) { $Pages = $cfg.Pages }
        if ($cfg.TargetTab) { $TargetTab = $cfg.TargetTab }
        if ($cfg.Instance) { $Instance = $cfg.Instance }
        if ($cfg.Script) { $Script = $cfg.Script }
        if ($cfg.OneShot) { Remove-Item "run_config.json" -Force }
    } catch {
        "Failed to parse run_config.json: $_" | Out-File $logFile -Append -Encoding utf8
    }
}

if ($Script -ne "") {
    $parts = $Script -split '\s+'
    & $python $parts *>> $logFile
    exit $LASTEXITCODE
}

$instLabel = if ($Instance -ne "") { " [Instance: $Instance]" } else { " [Instance: Auto-Rotate]" }
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Starting collection run for: $Watchlist (Mode: $TargetTab)$instLabel..." | Out-File $logFile -Encoding utf8

$extraArgs = @()
if ($Instance -ne "") {
    $extraArgs += @("--instance", $Instance)
}

if ($Query -ne "") {
    & $python run_collector.py --mode auto --query $Query --pages $Pages --target-tab $TargetTab @extraArgs *>> $logFile
} else {
    & $python run_collector.py --mode auto --watchlist $Watchlist --pages $Pages --target-tab $TargetTab @extraArgs *>> $logFile
}

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Collector completed with exit code $LASTEXITCODE. Running aggregator..." | Out-File $logFile -Append -Encoding utf8
& $python -m src.aggregator *>> $logFile
"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Updating dashboard.html..." | Out-File $logFile -Append -Encoding utf8
& $python dashboard.py *>> $logFile

# Automated GitHub Pages sync (if git remote origin is configured)
$hasRemote = git remote 2>$null
if ($hasRemote -contains "origin") {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Syncing docs/index.html to GitHub Pages..." | Out-File $logFile -Append -Encoding utf8
    git add docs/index.html *>> $logFile
    git commit -m "Auto-update market dashboard: $(Get-Date -Format 'yyyy-MM-dd HH:mm')" *>> $logFile
    git push origin master *>> $logFile
} else {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') GitHub remote not yet configured; docs/index.html generated locally." | Out-File $logFile -Append -Encoding utf8
}

"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') All tasks finished." | Out-File $logFile -Append -Encoding utf8
