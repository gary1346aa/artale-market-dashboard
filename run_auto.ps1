param (
    [string]$Watchlist = "items_watchlist.json",
    [string]$Query = "",
    [int]$Pages = 2,
    [string]$TargetTab = "trades",
    [string]$Instance = "",
    [int]$Parallel = 0,
    [string]$Script = "",
    [int]$StartIndex = 1,
    [int]$Tier = 0,
    [switch]$Due,
    [switch]$AutoPowerSave,
    [switch]$ColdBoot,
    [switch]$Bootstrap
)

$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

Set-Location "C:\Users\gary1\artale_market_tracker"
$python = "C:\Users\gary1\AppData\Local\Programs\Python\Python314\python.exe"
$logFile = "C:\Users\gary1\collector_run.log"

function Format-Centered([string]$text, [int]$width) {
    $pad = [Math]::Max(0, $width - $text.Length)
    $leftPad = [Math]::Floor($pad / 2)
    $rightPad = $pad - $leftPad
    return (" " * $leftPad) + $text + (" " * $rightPad)
}

function Write-AppLog([string]$msg, [string]$level = "INFO", [string]$subsystem = "runner.auto_runner") {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $lvlStr = Format-Centered $level 9
    $subStr = $subsystem.PadRight(32)
    $formatted = "$ts [$lvlStr] [$subStr] $msg"
    $formatted | Out-File $logFile -Append -Encoding utf8
    Write-Host $formatted
}

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
        Write-AppLog "Failed to parse run_config.json: $_" "WARNING" "runner.auto_runner"
    }
}

if ($Script -ne "") {
    $parts = $Script -split '\s+'
    & $python $parts *>> $logFile
    exit $LASTEXITCODE
}

# Automated database backup before any collection/aggregation run
if (Test-Path "data\market.db") {
    $backupDir = "data\backups"
    if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir -Force | Out-Null }
    $ts = (Get-Date).ToString("yyyyMMdd_HHmmss")
    $backupFile = Join-Path $backupDir "market_backup_$ts.db"
    Copy-Item "data\market.db" $backupFile -Force
    # Retain the 30 most recent snapshots
    Get-ChildItem $backupDir -Filter "market_backup_*.db" | Sort-Object CreationTime -Descending | Select-Object -Skip 30 | Remove-Item -Force
}

$instLabel = if ($Instance -ne "") { " [Instance: $Instance]" } else { " [Instance: Auto-Rotate]" }
$resumeLabel = if ($StartIndex -gt 1) { " [Resuming from #$StartIndex]" } else { "" }
Write-AppLog "Starting collection run for: $Watchlist (Mode: $TargetTab)$instLabel$resumeLabel..." "INFO" "AutoRunner"

if ($Due) {
    try {
        $pyCmd = "import sys; sys.stdout.reconfigure(encoding='utf-8'); import json; from core.watchlist import get_due_items; due, wait_sec, next_item = get_due_items(); wl = json.load(open('$Watchlist', 'r', encoding='utf-8')); print(json.dumps({'due_count': len(due), 'total_count': len(wl), 'wait_min': round(wait_sec/60, 1), 'next_item': next_item, 'due_items': due}, ensure_ascii=False))"
        $dueInfo = & $python -c $pyCmd | ConvertFrom-Json
        $dueCount = $dueInfo.due_count
        $totalCount = $dueInfo.total_count
        $waitMin = $dueInfo.wait_min
        $nextItem = $dueInfo.next_item
        $dueItems = @($dueInfo.due_items)

        if ($dueCount -eq 0) {
            Write-AppLog "Watchlist Status: 0 of $totalCount items due. All up to date." "INFO" "AutoRunner"
        } else {
            $sample = if ($dueItems.Count -gt 6) { ($dueItems[0..5] -join ', ') + " (+$(($dueItems.Count - 6)) more)" } else { $dueItems -join ', ' }
            Write-AppLog "Watchlist Status: $dueCount of $totalCount item(s) due: [$sample]" "INFO" "AutoRunner"
        }
    } catch {
    }
}

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
if ($Parallel -gt 0) {
    $extraArgs += @("--parallel", $Parallel)
}
if ($ColdBoot -or $AutoPowerSave) {
    $extraArgs += @("--cold-boot")
}
if ($Bootstrap -or $AutoPowerSave) {
    $extraArgs += @("--bootstrap")
}
function Set-WindowsPowerPlan([string]$planName) {
    try {
        $targetGuid = $null
        $plans = powercfg /list
        foreach ($line in ($plans -split "`r?`n")) {
            if ($line -match 'Power Scheme GUID:\s+([a-f0-9\-]+)\s+\((.+)\)') {
                $guid = $matches[1].Trim()
                $name = $matches[2].Trim()
                if ($name -like "*$planName*") {
                    $targetGuid = $guid
                    break
                }
            }
        }
        if (-not $targetGuid) {
            if ($planName -like "*Ultimate*") { $targetGuid = "ee8b14d0-ad4d-4345-8f52-928a761433ff" }
            elseif ($planName -like "*Balanced*") { $targetGuid = "381b4222-f694-41f0-9685-ff5bb260df2e" }
        }
        if ($targetGuid) {
            powercfg /setactive $targetGuid
            Write-AppLog "Windows Power Scheme switched to: $planName" "INFO" "system.power_scheme"
        }
    } catch {
        Write-AppLog "Failed to switch Windows Power Scheme to: $planName" "WARNING" "system.power_scheme"
    }
}

if ($AutoPowerSave) {
    $extraArgs += @("--kill-after")
    Set-WindowsPowerPlan "Ultimate Performance"
}

try {
    if ($Query -ne "") {
        & $python -u run_collector.py --mode auto --query $Query --pages $Pages --target-tab $TargetTab @extraArgs 2>&1 | Tee-Object -FilePath $logFile -Append
    } else {
        & $python -u run_collector.py --mode auto --watchlist $Watchlist --pages $Pages --target-tab $TargetTab @extraArgs 2>&1 | Tee-Object -FilePath $logFile -Append
    }

    if ($LASTEXITCODE -ne 0) {
        Write-AppLog "Collector failed with exit code $LASTEXITCODE. Aborting subsequent steps." "ERROR" "runner.auto_runner"
        exit $LASTEXITCODE
    }

    Write-AppLog "Collector completed. Running aggregator..." "INFO" "runner.auto_runner"
    & $python -u -m storage.aggregator | Tee-Object -FilePath $logFile -Append

    Write-AppLog "Updating dashboard.html and docs/index.html..." "INFO" "runner.auto_runner"
    & $python -u dashboard.py | Tee-Object -FilePath $logFile -Append

    # Automated GitHub Pages sync (if git remote origin is configured)
    $hasRemote = git remote 2>$null
    if ($hasRemote -contains "origin") {
        Write-AppLog "Syncing docs/index.html to GitHub Pages..." "INFO" "runner.auto_runner"
        git add docs/index.html *>> $logFile
        git commit -m "Auto-update market dashboard: $((Get-Date).ToString('yyyy-MM-dd HH:mm'))" *>> $logFile
        git push origin master *>> $logFile
    } else {
        Write-AppLog "GitHub remote not configured; generated locally." "WARNING" "runner.auto_runner"
    }

    Write-AppLog "All tasks finished successfully!" "INFO" "runner.auto_runner"
} finally {
    if ($AutoPowerSave) {
        # Failsafe: Ensure emulators are terminated even if a script crash occurred
        try {
            if ($Instance -ne "") {
                $pyKill = "from driver.emulator_controller import EmulatorController; EmulatorController().quit_instance('$Instance')"
            } else {
                $pyKill = "from driver.emulator_controller import EmulatorController; EmulatorController().quit_all()"
            }
            & $python -c $pyKill 2>$null
        } catch {}

        # Revert Windows Power Scheme back to Balanced for idle power preservation
        Set-WindowsPowerPlan "Balanced"
    }
}
