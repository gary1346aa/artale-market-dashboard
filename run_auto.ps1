param (
    [string]$Watchlist = "items_watchlist.json",
    [string]$Query = "",
    [int]$Pages = 2,
    [string]$TargetTab = "trades",
    [string]$Instance = "槍手",
    [string]$Script = "",
    [int]$StartIndex = 1,
    [int]$Tier = 0,
    [switch]$Due,
    [switch]$AutoLoop
)

$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

Set-Location "C:\Users\gary1\artale_market_tracker"
$python = "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"
$logFile = "C:\Users\gary1\collector_run.log"

# Support dynamic config overrides ONLY for unset parameters
if (Test-Path "run_config.json") {
    try {
        $cfg = Get-Content "run_config.json" -Raw -Encoding utf8 | ConvertFrom-Json
        if ($cfg.Watchlist -and -not $PSBoundParameters.ContainsKey('Watchlist')) { $Watchlist = $cfg.Watchlist }
        if ($cfg.Query -and -not $PSBoundParameters.ContainsKey('Query')) { $Query = $cfg.Query }
        if ($null -ne $cfg.Pages -and -not $PSBoundParameters.ContainsKey('Pages')) { $Pages = $cfg.Pages }
        if ($cfg.TargetTab -and -not $PSBoundParameters.ContainsKey('TargetTab')) { $TargetTab = $cfg.TargetTab }
        if ($cfg.Instance -and -not $PSBoundParameters.ContainsKey('Instance')) { $Instance = $cfg.Instance }
        if ($cfg.Script -and -not $PSBoundParameters.ContainsKey('Script')) { $Script = $cfg.Script }
        if ($null -ne $cfg.StartIndex -and -not $PSBoundParameters.ContainsKey('StartIndex')) { $StartIndex = $cfg.StartIndex }
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
$resumeLabel = if ($StartIndex -gt 1) { " [Resuming from #$StartIndex]" } else { "" }
$startMsg = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Starting collection run for: $Watchlist (Mode: $TargetTab)$instLabel$resumeLabel..."
Write-Host $startMsg -ForegroundColor Cyan
$startMsg | Out-File $logFile -Append -Encoding utf8

$extraArgs = @()
if ($Instance -ne "") {
    $extraArgs += @("--instance", $Instance)
}
if ($StartIndex -gt 1) {
    $extraArgs += @("--start-index", $StartIndex)
}
if ($Tier -gt 0) {
    $extraArgs += @("--tier", $Tier)
}
if ($Due) {
    $extraArgs += @("--due")
}
if ($AutoLoop) {
    $extraArgs += @("--auto-loop")
}

if ($Query -ne "") {
    & $python -u run_collector.py --mode auto --query $Query --pages $Pages --target-tab $TargetTab @extraArgs | Tee-Object -FilePath $logFile -Append
} else {
    & $python -u run_collector.py --mode auto --watchlist $Watchlist --pages $Pages --target-tab $TargetTab @extraArgs | Tee-Object -FilePath $logFile -Append
}

$aggMsg = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Collector completed. Running aggregator..."
Write-Host $aggMsg -ForegroundColor Cyan
$aggMsg | Out-File $logFile -Append -Encoding utf8
& $python -u -m src.aggregator | Tee-Object -FilePath $logFile -Append

$dashMsg = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Updating dashboard.html and docs/index.html..."
Write-Host $dashMsg -ForegroundColor Cyan
$dashMsg | Out-File $logFile -Append -Encoding utf8
& $python -u dashboard.py | Tee-Object -FilePath $logFile -Append

# Automated GitHub Pages sync (if git remote origin is configured)
$hasRemote = git remote 2>$null
if ($hasRemote -contains "origin") {
    $syncMsg = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Syncing docs/index.html to GitHub Pages..."
    Write-Host $syncMsg -ForegroundColor Green
    $syncMsg | Out-File $logFile -Append -Encoding utf8
    git add docs/index.html
    git commit -m "Auto-update market dashboard: $((Get-Date).ToString('yyyy-MM-dd HH:mm'))"
    git push origin master
} else {
    $localMsg = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] GitHub remote not configured; generated locally."
    Write-Host $localMsg -ForegroundColor Yellow
    $localMsg | Out-File $logFile -Append -Encoding utf8
}

$finishMsg = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] All tasks finished successfully!"
Write-Host $finishMsg -ForegroundColor Green
$finishMsg | Out-File $logFile -Append -Encoding utf8
